use std::fs;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use serde::Serialize;

pub struct StateStore {
    conn: Connection,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClaimResult {
    Acquired,
    AlreadyComplete,
}

struct EventRecord<'a> {
    job_id: &'a str,
    kind: &'a str,
    from_state: Option<&'a str>,
    to_state: &'a str,
    payload_json: &'a str,
    owner: &'a str,
    now: i64,
}

impl StateStore {
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
        {
            fs::create_dir_all(parent).with_context(|| {
                format!("failed to create state directory {}", parent.display())
            })?;
        }
        let conn = Connection::open(path)
            .with_context(|| format!("failed to open state database {}", path.display()))?;
        conn.busy_timeout(std::time::Duration::from_secs(30))?;
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "synchronous", "FULL")?;
        conn.execute_batch(
            r#"
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                state TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                revision INTEGER NOT NULL,
                owner TEXT,
                lease_until INTEGER,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                from_state TEXT,
                to_state TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                owner TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS job_actions (
                job_id TEXT NOT NULL,
                action_index INTEGER NOT NULL,
                source_path TEXT NOT NULL,
                destination_path TEXT NOT NULL,
                destination_key TEXT NOT NULL,
                expected_sha256 TEXT NOT NULL,
                state TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(job_id, action_index)
            );
            CREATE INDEX IF NOT EXISTS idx_events_job_id ON events(job_id, event_id);
            "#,
        )?;
        ensure_column(&conn, "jobs", "owner", "TEXT")?;
        ensure_column(&conn, "jobs", "lease_until", "INTEGER")?;
        ensure_column(&conn, "events", "owner", "TEXT")?;
        ensure_column(&conn, "job_actions", "destination_key", "TEXT")?;
        conn.execute(
            "UPDATE job_actions SET destination_key=destination_path WHERE destination_key IS NULL",
            [],
        )?;
        conn.execute("DROP INDEX IF EXISTS idx_job_actions_destination", [])?;
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_job_actions_destination ON job_actions(destination_key COLLATE NOCASE)",
            [],
        )?;
        Ok(Self { conn })
    }

    pub fn current_state(&self, job_id: &str) -> Result<Option<String>> {
        Ok(self
            .conn
            .query_row(
                "SELECT state FROM jobs WHERE job_id = ?1",
                [job_id],
                |row| row.get(0),
            )
            .optional()?)
    }

    pub fn claim<T: Serialize>(
        &mut self,
        job_id: &str,
        kind: &str,
        owner: &str,
        lease_seconds: u64,
        complete_state: &str,
        payload: &T,
    ) -> Result<ClaimResult> {
        validate_identity(job_id, kind, owner)?;
        let payload_json = serde_json::to_string(payload)?;
        let now = now_epoch_seconds()?;
        let lease_until = now.saturating_add(i64::try_from(lease_seconds).unwrap_or(i64::MAX));
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: Option<(String, Option<String>, Option<i64>, i64)> = tx
            .query_row(
                "SELECT state, owner, lease_until, revision FROM jobs WHERE job_id = ?1",
                [job_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .optional()?;

        if current
            .as_ref()
            .is_some_and(|(state, _, _, _)| state == complete_state)
        {
            return Ok(ClaimResult::AlreadyComplete);
        }
        if let Some((state, Some(current_owner), Some(until), _)) = &current
            && *until >= now
            && current_owner != owner
        {
            bail!("job {job_id} is leased by {current_owner} until {until} while in state {state}");
        }

        let from_state = current.as_ref().map(|(state, _, _, _)| state.as_str());
        let revision = current
            .as_ref()
            .map_or(1, |(_, _, _, revision)| revision + 1);
        tx.execute(
            r#"
            INSERT INTO jobs(job_id, kind, state, payload_json, revision, owner, lease_until, updated_at)
            VALUES(?1, ?2, 'CLAIMED', ?3, ?4, ?5, ?6, ?7)
            ON CONFLICT(job_id) DO UPDATE SET
                kind=excluded.kind,
                state=excluded.state,
                payload_json=excluded.payload_json,
                revision=excluded.revision,
                owner=excluded.owner,
                lease_until=excluded.lease_until,
                updated_at=excluded.updated_at
            "#,
            params![job_id, kind, payload_json, revision, owner, lease_until, now],
        )?;
        append_event(
            &tx,
            &EventRecord {
                job_id,
                kind,
                from_state,
                to_state: "CLAIMED",
                payload_json: &payload_json,
                owner,
                now,
            },
        )?;
        tx.commit()?;
        Ok(ClaimResult::Acquired)
    }

    pub fn renew(&mut self, job_id: &str, owner: &str, lease_seconds: u64) -> Result<()> {
        let now = now_epoch_seconds()?;
        let until = now.saturating_add(i64::try_from(lease_seconds).unwrap_or(i64::MAX));
        let changed = self.conn.execute(
            "UPDATE jobs SET lease_until=?1, updated_at=?2 WHERE job_id=?3 AND owner=?4",
            params![until, now, job_id, owner],
        )?;
        if changed != 1 {
            bail!("job {job_id} lease is not owned by {owner}");
        }
        Ok(())
    }

    pub fn transition<T: Serialize>(
        &mut self,
        job_id: &str,
        kind: &str,
        owner: &str,
        expected_state: &str,
        next_state: &str,
        payload: &T,
    ) -> Result<u64> {
        if !valid_transition(kind, expected_state, next_state) {
            bail!("illegal {kind} state transition {expected_state} -> {next_state}");
        }
        let payload_json = serde_json::to_string(payload)?;
        let now = now_epoch_seconds()?;
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let revision: Option<i64> = tx
            .query_row(
                "SELECT revision FROM jobs WHERE job_id=?1 AND kind=?2 AND state=?3 AND owner=?4 AND lease_until>=?5",
                params![job_id, kind, expected_state, owner, now],
                |row| row.get(0),
            )
            .optional()?;
        let revision = revision.with_context(|| {
            format!(
                "job {job_id} state/owner/lease changed before {expected_state} -> {next_state}"
            )
        })? + 1;
        if is_terminal(next_state) {
            tx.execute(
                "UPDATE jobs SET state=?1, payload_json=?2, revision=?3, owner=NULL, lease_until=NULL, updated_at=?4 WHERE job_id=?5",
                params![next_state, payload_json, revision, now, job_id],
            )?;
        } else {
            tx.execute(
                "UPDATE jobs SET state=?1, payload_json=?2, revision=?3, updated_at=?4 WHERE job_id=?5",
                params![next_state, payload_json, revision, now, job_id],
            )?;
        }
        append_event(
            &tx,
            &EventRecord {
                job_id,
                kind,
                from_state: Some(expected_state),
                to_state: next_state,
                payload_json: &payload_json,
                owner,
                now,
            },
        )?;
        tx.commit()?;
        Ok(revision as u64)
    }

    pub fn fail<T: Serialize>(
        &mut self,
        job_id: &str,
        kind: &str,
        owner: &str,
        payload: &T,
    ) -> Result<()> {
        let Some(current) = self.current_state(job_id)? else {
            bail!("cannot fail missing job {job_id}");
        };
        if current == "FAILED" {
            return Ok(());
        }
        self.transition(job_id, kind, owner, &current, "FAILED", payload)?;
        Ok(())
    }

    pub fn register_action(
        &mut self,
        job_id: &str,
        index: usize,
        source: &str,
        destination: &str,
        destination_key: &str,
        expected_sha256: &str,
    ) -> Result<()> {
        let now = now_epoch_seconds()?;
        self.conn.execute(
            r#"
            INSERT INTO job_actions(job_id, action_index, source_path, destination_path, destination_key, expected_sha256, state, updated_at)
            VALUES(?1, ?2, ?3, ?4, ?5, ?6, 'PLANNED', ?7)
            ON CONFLICT(job_id, action_index) DO NOTHING
            "#,
            params![
                job_id,
                index as i64,
                source,
                destination,
                destination_key,
                expected_sha256,
                now
            ],
        )
        .with_context(|| {
            format!(
                "destination {destination} is already reserved by another migration action"
            )
        })?;
        let actual: (String, String, String, String) = self.conn.query_row(
            "SELECT source_path, destination_path, destination_key, expected_sha256 FROM job_actions WHERE job_id=?1 AND action_index=?2",
            params![job_id, index as i64],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )?;
        if actual
            != (
                source.to_owned(),
                destination.to_owned(),
                destination_key.to_owned(),
                expected_sha256.to_owned(),
            )
        {
            bail!("job {job_id} action {index} does not match its persisted identity");
        }
        Ok(())
    }

    pub fn action_state(&self, job_id: &str, index: usize) -> Result<Option<String>> {
        Ok(self
            .conn
            .query_row(
                "SELECT state FROM job_actions WHERE job_id=?1 AND action_index=?2",
                params![job_id, index as i64],
                |row| row.get(0),
            )
            .optional()?)
    }

    pub fn set_action_state(
        &mut self,
        job_id: &str,
        index: usize,
        expected: &str,
        next: &str,
    ) -> Result<()> {
        if !matches!(
            (expected, next),
            ("PLANNED", "PROMOTED") | ("PROMOTED", "SOURCE_REMOVED")
        ) {
            bail!("illegal action transition {expected} -> {next}");
        }
        let changed = self.conn.execute(
            "UPDATE job_actions SET state=?1, updated_at=?2 WHERE job_id=?3 AND action_index=?4 AND state=?5",
            params![next, now_epoch_seconds()?, job_id, index as i64, expected],
        )?;
        if changed != 1 {
            let actual = self.action_state(job_id, index)?;
            if actual.as_deref() != Some(next) {
                bail!(
                    "job {job_id} action {index} state changed; expected {expected}, found {actual:?}"
                );
            }
        }
        Ok(())
    }

    pub fn event_count(&self, job_id: &str) -> Result<u64> {
        let count: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM events WHERE job_id = ?1",
            [job_id],
            |row| row.get(0),
        )?;
        Ok(count as u64)
    }
}

fn append_event(tx: &rusqlite::Transaction<'_>, event: &EventRecord<'_>) -> Result<()> {
    tx.execute(
        "INSERT INTO events(job_id, kind, from_state, to_state, payload_json, owner, created_at) VALUES(?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        params![
            event.job_id,
            event.kind,
            event.from_state,
            event.to_state,
            event.payload_json,
            event.owner,
            event.now
        ],
    )?;
    Ok(())
}

fn valid_transition(kind: &str, from: &str, to: &str) -> bool {
    if to == "FAILED" && !matches!(from, "COMMITTED" | "READY") {
        return true;
    }
    match kind {
        "migration" => matches!(
            (from, to),
            ("CLAIMED", "STAGING")
                | ("STAGING", "VERIFIED")
                | ("VERIFIED", "REMOVING_SOURCE")
                | ("REMOVING_SOURCE", "COMMITTED")
        ),
        "subtitle" => matches!(
            (from, to),
            ("CLAIMED", "ACQUIRING")
                | ("ACQUIRING", "TRANSLATING")
                | ("TRANSLATING", "VERIFIED")
                | ("VERIFIED", "READY")
        ),
        _ => false,
    }
}

fn is_terminal(state: &str) -> bool {
    matches!(state, "COMMITTED" | "READY" | "FAILED")
}

fn validate_identity(job_id: &str, kind: &str, owner: &str) -> Result<()> {
    if job_id.trim().is_empty() || kind.trim().is_empty() || owner.trim().is_empty() {
        bail!("job_id, kind, and owner must not be empty");
    }
    Ok(())
}

fn ensure_column(conn: &Connection, table: &str, column: &str, definition: &str) -> Result<()> {
    let mut statement = conn.prepare(&format!("PRAGMA table_info({table})"))?;
    let existing: Vec<String> = statement
        .query_map([], |row| row.get(1))?
        .collect::<rusqlite::Result<_>>()?;
    if !existing.iter().any(|name| name == column) {
        conn.execute(
            &format!("ALTER TABLE {table} ADD COLUMN {column} {definition}"),
            [],
        )?;
    }
    Ok(())
}

fn now_epoch_seconds() -> Result<i64> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .context("system clock is before Unix epoch")?
        .as_secs() as i64)
}

pub fn process_owner() -> String {
    format!(
        "{}-{}-{}",
        std::env::var("HOSTNAME").unwrap_or_else(|_| "host".to_owned()),
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::tempdir;

    #[test]
    fn lease_prevents_a_second_writer_and_transitions_are_strict() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("state.sqlite3");
        let mut first = StateStore::open(&path).unwrap();
        let mut second = StateStore::open(&path).unwrap();
        assert_eq!(
            ClaimResult::Acquired,
            first
                .claim("job", "migration", "owner-a", 60, "COMMITTED", &json!({}))
                .unwrap()
        );
        assert!(
            second
                .claim("job", "migration", "owner-b", 60, "COMMITTED", &json!({}))
                .is_err()
        );
        first
            .transition(
                "job",
                "migration",
                "owner-a",
                "CLAIMED",
                "STAGING",
                &json!({}),
            )
            .unwrap();
        assert!(
            first
                .transition(
                    "job",
                    "migration",
                    "owner-a",
                    "STAGING",
                    "COMMITTED",
                    &json!({}),
                )
                .is_err()
        );
        assert_eq!(2, first.event_count("job").unwrap());
    }

    #[test]
    fn terminal_subtitle_job_releases_lease_for_force_or_source_change() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("state.sqlite3");
        let mut first = StateStore::open(&path).unwrap();
        first
            .claim("subtitle", "subtitle", "owner-a", 600, "never", &json!({}))
            .unwrap();
        first
            .transition(
                "subtitle",
                "subtitle",
                "owner-a",
                "CLAIMED",
                "ACQUIRING",
                &json!({}),
            )
            .unwrap();
        first
            .transition(
                "subtitle",
                "subtitle",
                "owner-a",
                "ACQUIRING",
                "TRANSLATING",
                &json!({}),
            )
            .unwrap();
        first
            .transition(
                "subtitle",
                "subtitle",
                "owner-a",
                "TRANSLATING",
                "VERIFIED",
                &json!({}),
            )
            .unwrap();
        first
            .transition(
                "subtitle",
                "subtitle",
                "owner-a",
                "VERIFIED",
                "READY",
                &json!({}),
            )
            .unwrap();

        let mut second = StateStore::open(&path).unwrap();
        assert_eq!(
            ClaimResult::Acquired,
            second
                .claim("subtitle", "subtitle", "owner-b", 600, "never", &json!({}))
                .unwrap()
        );
    }

    #[test]
    fn action_identity_and_progress_are_persisted() {
        let dir = tempdir().unwrap();
        let mut store = StateStore::open(&dir.path().join("state.sqlite3")).unwrap();
        store
            .register_action("job", 0, "a", "b", "library-a-b", "hash")
            .unwrap();
        store
            .set_action_state("job", 0, "PLANNED", "PROMOTED")
            .unwrap();
        assert_eq!(
            Some("PROMOTED".into()),
            store.action_state("job", 0).unwrap()
        );
        assert!(
            store
                .register_action("job", 0, "x", "b", "library-a-b", "hash")
                .is_err()
        );
        assert!(
            store
                .register_action("other-job", 0, "other", "B", "LIBRARY-A-B", "other-hash")
                .is_err(),
            "destination reservations are case-insensitive across plans"
        );
        store
            .register_action(
                "different-library",
                0,
                "other",
                "b",
                "library-b-b",
                "other-hash",
            )
            .unwrap();
    }
}
