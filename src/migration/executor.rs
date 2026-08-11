use std::fs::File;
use std::io::{BufReader, Seek, SeekFrom};

use anyhow::{Context, Result, bail};
use serde_json::json;
use sha2::{Digest, Sha256};
use tempfile::NamedTempFile;

use crate::config::{Config, StorageConfig};
use crate::state::{ClaimResult, StateStore, process_owner};
use crate::storage::{Storage, open_storage, try_ftp_streaming_copy, try_server_side_rename};

use super::planner::{FileAction, PlanDocument, PlanItem, PlanStatus, SourceFingerprint};

#[derive(Clone, Copy)]
struct BoundStorage<'a> {
    storage: &'a dyn Storage,
    config: &'a StorageConfig,
    namespace: &'a str,
}

pub fn apply_plan(config: &Config, plan: &PlanDocument, approval: &str) -> Result<()> {
    plan.verify_hash()?;
    plan.verify_config(config)?;
    if approval != plan.plan_hash {
        bail!("approval hash does not match the migration plan");
    }
    if plan.pending_count() != 0 {
        bail!(
            "migration plan contains {} pending item(s); resolve them in configuration and build a new plan",
            plan.pending_count()
        );
    }
    let source = open_storage(&config.source).context("failed to open source storage")?;
    let destination =
        open_storage(&config.destination).context("failed to open destination storage")?;
    preflight_plan(source.as_ref(), destination.as_ref(), plan)?;

    let mut state = StateStore::open(&config.state.database)?;
    let owner = process_owner();
    let destination_namespace = serde_json::to_string(&plan.destination_binding)?;
    for item in &plan.items {
        if let Err(error) = apply_item(
            &mut state,
            BoundStorage {
                storage: source.as_ref(),
                config: &config.source,
                namespace: "",
            },
            BoundStorage {
                storage: destination.as_ref(),
                config: &config.destination,
                namespace: &destination_namespace,
            },
            &owner,
            config.state.lease_seconds,
            &plan.plan_hash,
            item,
        ) {
            let job_id = job_id(&plan.plan_hash, &item.source);
            let _ = state.fail(
                &job_id,
                "migration",
                &owner,
                &json!({"source": item.source, "error": format!("{error:#}")}),
            );
            return Err(error);
        }
    }
    Ok(())
}

fn preflight_plan(
    source: &dyn Storage,
    destination: &dyn Storage,
    plan: &PlanDocument,
) -> Result<()> {
    for item in &plan.items {
        if !matches!(item.status, PlanStatus::Ready) {
            bail!("refusing to preflight pending item {}", item.source);
        }
        for action in item.actions() {
            let source_exists = source.exists(&action.source)?;
            let destination_exists = destination.exists(&action.destination)?;
            if !source_exists && !destination_exists {
                bail!(
                    "neither source {} nor destination {} exists",
                    action.source,
                    action.destination
                );
            }
            if source_exists {
                verify_source(source, &action.source, &action.source_fingerprint)?;
            }
            if destination_exists {
                verify_destination(destination, &action)?;
            }
        }
    }
    Ok(())
}

fn apply_item(
    state: &mut StateStore,
    source: BoundStorage<'_>,
    destination: BoundStorage<'_>,
    owner: &str,
    lease_seconds: u64,
    plan_hash: &str,
    item: &PlanItem,
) -> Result<()> {
    let job_id = job_id(plan_hash, &item.source);
    let actions = item.actions(); // sidecars first, primary video last
    match state.claim(
        &job_id,
        "migration",
        owner,
        lease_seconds,
        "COMMITTED",
        &json!({"source": item.source, "plan_hash": plan_hash}),
    )? {
        ClaimResult::AlreadyComplete => {
            verify_all_destinations(destination.storage, &actions)?;
            return Ok(());
        }
        ClaimResult::Acquired => {}
    }
    for (index, action) in actions.iter().enumerate() {
        let expected_hash = action
            .source_fingerprint
            .content_sha256
            .as_deref()
            .context("executable migration action is missing a content hash")?;
        state.register_action(
            &job_id,
            index,
            &action.source,
            &action.destination,
            &destination_reservation_key(destination.namespace, &action.destination),
            expected_hash,
        )?;
    }
    state.transition(
        &job_id,
        "migration",
        owner,
        "CLAIMED",
        "STAGING",
        &json!({"files": actions.len()}),
    )?;

    for (index, action) in actions.iter().enumerate() {
        state.renew(&job_id, owner, lease_seconds)?;
        let action_state = state
            .action_state(&job_id, index)?
            .context("registered migration action disappeared")?;
        if action_state == "SOURCE_REMOVED" || action_state == "PROMOTED" {
            verify_destination(destination.storage, action)?;
            continue;
        }
        promote_action(source, destination, action)?;
        state.set_action_state(&job_id, index, "PLANNED", "PROMOTED")?;
    }

    verify_all_destinations(destination.storage, &actions)?;
    state.transition(
        &job_id,
        "migration",
        owner,
        "STAGING",
        "VERIFIED",
        &json!({"files": actions.len()}),
    )?;
    state.transition(
        &job_id,
        "migration",
        owner,
        "VERIFIED",
        "REMOVING_SOURCE",
        &json!({"files": actions.len()}),
    )?;

    for (index, action) in actions.iter().enumerate() {
        state.renew(&job_id, owner, lease_seconds)?;
        let action_state = state
            .action_state(&job_id, index)?
            .context("registered migration action disappeared")?;
        verify_destination(destination.storage, action)?;
        if source.storage.exists(&action.source)? {
            verify_source(source.storage, &action.source, &action.source_fingerprint)?;
            source
                .storage
                .remove(&action.source)
                .with_context(|| format!("failed to remove verified source {}", action.source))?;
        }
        if action_state == "PROMOTED" {
            state.set_action_state(&job_id, index, "PROMOTED", "SOURCE_REMOVED")?;
        } else if action_state != "SOURCE_REMOVED" {
            bail!(
                "unexpected action state {action_state} while committing {}",
                action.source
            );
        }
    }

    verify_all_destinations(destination.storage, &actions)?;
    state.transition(
        &job_id,
        "migration",
        owner,
        "REMOVING_SOURCE",
        "COMMITTED",
        &json!({"source": item.source, "files": actions.len()}),
    )?;
    Ok(())
}

fn promote_action(
    source: BoundStorage<'_>,
    destination: BoundStorage<'_>,
    action: &FileAction,
) -> Result<()> {
    if destination.storage.exists(&action.destination)? {
        verify_destination(destination.storage, action)?;
        if source.storage.exists(&action.source)? {
            verify_source(source.storage, &action.source, &action.source_fingerprint)?;
        }
        return Ok(());
    }
    verify_source(source.storage, &action.source, &action.source_fingerprint)?;
    if let Some(parent) = storage_parent(&action.destination) {
        destination.storage.create_dir_all(parent)?;
    }

    if try_server_side_rename(
        source.config,
        destination.config,
        &action.source,
        &action.destination,
    )? {
        verify_destination(destination.storage, action)?;
        return Ok(());
    }

    if try_ftp_streaming_copy(
        source.config,
        destination.storage,
        &action.source,
        &action.destination,
    )? {
        verify_destination(destination.storage, action)?;
        return Ok(());
    }

    if let (Some(source_path), Some(destination_path)) = (
        source.storage.local_path(&action.source)?,
        destination
            .storage
            .local_path_for_write(&action.destination)?,
    ) {
        match std::fs::hard_link(&source_path, &destination_path) {
            Ok(()) => {
                verify_destination(destination.storage, action)?;
                return Ok(());
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                return Err(error).with_context(|| {
                    format!(
                        "destination appeared while publishing {}",
                        destination_path.display()
                    )
                });
            }
            Err(_) => {
                // Separate mounted NAS shares are normally different devices.
                // Stream directly from the mounted source into the target's
                // atomic temporary file instead of consuming equally large
                // staging space on the Apple host.
            }
        }
        let mut reader = BufReader::new(
            File::open(&source_path)
                .with_context(|| format!("failed to open {}", source_path.display()))?,
        );
        destination
            .storage
            .upload_atomic(&action.destination, &mut reader)?;
        verify_destination(destination.storage, action)?;
        return Ok(());
    }
    copy_and_verify(source.storage, destination.storage, action)
}
fn copy_and_verify(
    source: &dyn Storage,
    destination: &dyn Storage,
    action: &FileAction,
) -> Result<()> {
    let available = fs2::available_space(std::env::temp_dir())?;
    let required = action
        .source_fingerprint
        .size_bytes
        .saturating_add(64 * 1024 * 1024);
    if available < required {
        bail!(
            "insufficient local staging space for {}: need {}, available {}",
            action.source,
            required,
            available
        );
    }
    let mut temporary = NamedTempFile::new().context("failed to create local staging file")?;
    source.download(&action.source, temporary.path())?;
    temporary.as_file_mut().seek(SeekFrom::Start(0))?;
    let staged_hash = hash_reader(temporary.as_file_mut())?;
    let expected_hash = expected_content_hash(&action.source_fingerprint)?;
    if staged_hash != expected_hash {
        bail!("staged copy hash mismatch for {}", action.source);
    }
    temporary.as_file_mut().seek(SeekFrom::Start(0))?;
    destination.upload_atomic(&action.destination, temporary.as_file_mut())?;
    verify_destination(destination, action)
}

fn verify_source(storage: &dyn Storage, path: &str, expected: &SourceFingerprint) -> Result<()> {
    let metadata = storage
        .metadata(path)?
        .with_context(|| format!("planned source disappeared: {path}"))?;
    if metadata.is_dir || metadata.size != expected.size_bytes {
        bail!("planned source size or type changed: {path}");
    }
    let hash = storage.sha256(path)?;
    if hash != expected_content_hash(expected)? {
        bail!("planned source content changed: {path}");
    }
    Ok(())
}

fn verify_destination(storage: &dyn Storage, action: &FileAction) -> Result<()> {
    let metadata = storage
        .metadata(&action.destination)?
        .with_context(|| format!("verified destination disappeared: {}", action.destination))?;
    if metadata.is_dir || metadata.size != action.source_fingerprint.size_bytes {
        bail!("destination size or type differs: {}", action.destination);
    }
    if storage.sha256(&action.destination)? != expected_content_hash(&action.source_fingerprint)? {
        bail!("destination content differs: {}", action.destination);
    }
    Ok(())
}

fn expected_content_hash(fingerprint: &SourceFingerprint) -> Result<&str> {
    fingerprint
        .content_sha256
        .as_deref()
        .context("executable migration action is missing a content hash")
}

fn verify_all_destinations(storage: &dyn Storage, actions: &[FileAction]) -> Result<()> {
    for action in actions {
        verify_destination(storage, action)?;
    }
    Ok(())
}

fn job_id(plan_hash: &str, source: &str) -> String {
    let mut digest = Sha256::new();
    digest.update(b"subtrans-migration-job-v2\0");
    digest.update(plan_hash.as_bytes());
    digest.update(b"\0");
    digest.update(source.as_bytes());
    hex::encode(digest.finalize())
}

fn destination_reservation_key(namespace: &str, destination: &str) -> String {
    let mut digest = Sha256::new();
    digest.update(b"subtrans-destination-reservation-v1\0");
    digest.update(namespace.to_lowercase().as_bytes());
    digest.update(b"\0");
    digest.update(destination.to_lowercase().as_bytes());
    hex::encode(digest.finalize())
}

fn storage_parent(path: &str) -> Option<&str> {
    path.rsplit_once('/')
        .map(|(parent, _)| parent)
        .filter(|value| !value.is_empty())
}

fn hash_reader(reader: &mut dyn std::io::Read) -> Result<String> {
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 128 * 1024];
    loop {
        let count = reader.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(hex::encode(digest.finalize()))
}
