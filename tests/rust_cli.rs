mod support;

use std::fs;
use std::process::Command;

use tempfile::tempdir;

fn subtrans() -> Command {
    Command::new(env!("CARGO_BIN_EXE_subtrans"))
}

#[test]
fn single_binary_reports_name_version_and_help() {
    let version = subtrans().arg("--version").output().unwrap();
    assert!(version.status.success());
    assert_eq!(
        String::from_utf8_lossy(&version.stdout).trim(),
        "subtrans 3.1.0"
    );

    let help = subtrans().arg("--help").output().unwrap();
    assert!(help.status.success());
    let help = String::from_utf8_lossy(&help.stdout);
    assert!(help.contains("Subtitle translation and safe media migration"));
    assert!(help.contains("subtitles"));
    assert!(help.contains("migrate"));
}

#[test]
fn pending_review_prints_reason_evidence_and_exact_override_key() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let video = "Anime.Title.[01].1080p.HEVC.mkv";
    fs::write(source.join(video), b"video").unwrap();

    let mut config = support::config(root.path(), &source, &destination);
    config.migration.require_translated_subtitle = false;
    let config_path = root.path().join("subtrans.toml");
    fs::write(&config_path, toml::to_string_pretty(&config).unwrap()).unwrap();
    let plan_path = root.path().join("migration.json");

    let planned = subtrans()
        .args(["migrate", "plan", "--config"])
        .arg(&config_path)
        .arg("--output")
        .arg(&plan_path)
        .output()
        .unwrap();
    assert!(planned.status.success(), "{:?}", planned);

    let reviewed = subtrans()
        .args(["migrate", "review", "--config"])
        .arg(&config_path)
        .arg("--plan")
        .arg(&plan_path)
        .output()
        .unwrap();
    assert!(reviewed.status.success(), "{:?}", reviewed);
    let output = String::from_utf8_lossy(&reviewed.stdout);
    assert!(output.contains("PENDING Anime.Title.[01].1080p.HEVC.mkv"));
    assert!(output.contains("reason:"));
    assert!(output.contains(r#"[migration.overrides."Anime.Title.[01].1080p.HEVC.mkv"]"#));
}
