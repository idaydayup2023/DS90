mod support;

use std::fs;

use rusqlite::Connection;
use subtrans::config::{MigrationOverride, OverrideKind, StorageConfig};
use subtrans::migration::{PlanStatus, apply_plan, build_plan};
use tempfile::tempdir;

#[test]
fn translation_artifact_is_a_hard_gate_unless_explicitly_overridden() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let video = "Movie.2026.WEB-DL.mkv";
    fs::write(source.join(video), b"video").unwrap();
    let mut cfg = support::config(root.path(), &source, &destination);

    let pending = build_plan(&cfg, None).unwrap();
    assert_eq!(pending.pending_count(), 1);
    assert!(matches!(
        pending.items[0].status,
        PlanStatus::Pending { .. }
    ));
    assert!(pending.items[0].proposed_destination.is_some());
    assert!(pending.items[0].destination.is_none());
    assert!(pending.items[0].source_fingerprint.content_sha256.is_none());

    support::write_ready_artifact(&source, video);
    assert_eq!(build_plan(&cfg, None).unwrap().pending_count(), 0);

    fs::remove_file(source.join(format!("{video}.not-used"))).ok();
    let other = "Ambiguous.Title.2026.2160p.mkv";
    fs::write(source.join(other), b"other").unwrap();
    cfg.migration.overrides.insert(
        other.into(),
        MigrationOverride {
            kind: OverrideKind::Movie,
            title: "Ambiguous Title".into(),
            year: Some(2026),
            season: None,
            episode: None,
            is_4k: Some(true),
            allow_untranslated: true,
        },
    );
    let plan = build_plan(&cfg, None).unwrap();
    assert_eq!(
        plan.items
            .iter()
            .filter(|item| item.source == other && !item.is_pending())
            .count(),
        1
    );
}

#[test]
fn plan_is_bound_to_configuration_and_recovers_when_sources_are_already_promoted() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    let other_destination = root.path().join("other-destination");
    fs::create_dir_all(source.join("incoming")).unwrap();
    fs::create_dir_all(&destination).unwrap();
    fs::create_dir_all(&other_destination).unwrap();
    let video = "incoming/Supergirl.2026.2160p.WEB-DL.mkv";
    fs::write(source.join(video), b"video bytes").unwrap();
    support::write_ready_artifact(&source, video);
    let cfg = support::config(root.path(), &source, &destination);
    let plan = build_plan(&cfg, None).unwrap();
    assert_eq!(plan.pending_count(), 0);

    let mut swapped = cfg.clone();
    swapped.destination = StorageConfig::Local {
        root: other_destination,
    };
    assert!(apply_plan(&swapped, &plan, &plan.plan_hash).is_err());

    apply_plan(&cfg, &plan, &plan.plan_hash).unwrap();
    let item = &plan.items[0];
    assert!(!source.join(video).exists());
    assert!(
        destination
            .join(item.destination.as_ref().unwrap())
            .exists()
    );

    // Simulate a crash after every file reached the destination but before the
    // final job commit became durable. A rerun must converge forward.
    let conn = Connection::open(&cfg.state.database).unwrap();
    conn.execute(
        "UPDATE jobs SET state='FAILED', owner=NULL, lease_until=0",
        [],
    )
    .unwrap();
    apply_plan(&cfg, &plan, &plan.plan_hash).unwrap();
    assert!(
        destination
            .join(item.destination.as_ref().unwrap())
            .exists()
    );
}

#[test]
fn destination_collisions_are_detected_before_apply() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(source.join("a")).unwrap();
    fs::create_dir_all(source.join("b")).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let name = "Same.Movie.2026.WEB-DL.mkv";
    fs::write(source.join("a").join(name), b"one").unwrap();
    fs::write(source.join("b").join(name), b"two").unwrap();
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.migration.require_translated_subtitle = false;
    cfg.migration.generic_source_directories = vec!["a".into(), "b".into()];
    let plan = build_plan(&cfg, None).unwrap();
    assert_eq!(plan.pending_count(), 2);
    assert!(plan.items.iter().all(|item| item.destination.is_none()));
}

#[test]
fn active_download_markers_block_migration_until_removed() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let video = "Movie.2026.2160p.WEB-DL.mkv";
    fs::write(source.join(video), b"video").unwrap();
    fs::write(source.join(format!("{video}.aria2")), b"active").unwrap();
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.migration.require_translated_subtitle = false;

    let blocked = build_plan(&cfg, None).unwrap();
    assert!(blocked.items[0].is_pending());
    assert!(blocked.items[0].source_fingerprint.content_sha256.is_none());
    let PlanStatus::Pending { reason } = &blocked.items[0].status else {
        unreachable!()
    };
    assert!(reason.contains("incomplete download marker"));

    fs::remove_file(source.join(format!("{video}.aria2"))).unwrap();
    let ready = build_plan(&cfg, None).unwrap();
    assert!(!ready.items[0].is_pending());
    assert!(ready.items[0].source_fingerprint.content_sha256.is_some());
}
