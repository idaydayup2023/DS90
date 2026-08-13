mod support;

use std::fs;
use std::process::Command;

use subtrans::config::StorageConfig;
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
        format!("subtrans {}", env!("CARGO_PKG_VERSION"))
    );

    let help = subtrans().arg("--help").output().unwrap();
    assert!(help.status.success());
    let help = String::from_utf8_lossy(&help.stdout);
    assert!(help.contains("TMDB metadata, subtitle translation, and safe media migration"));
    assert!(help.contains("subtitles"));
    assert!(help.contains("metadata"));
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

#[test]
fn local_directory_subtitles_override_ftp_without_enabling_migration() {
    let root = tempdir().unwrap();
    let configured_source = root.path().join("configured-source");
    let destination = root.path().join("destination");
    let local = root.path().join("local-media");
    fs::create_dir_all(&configured_source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    fs::create_dir_all(&local).unwrap();
    let stem = "Local.Movie.2026.WEB-DL";
    fs::write(local.join(format!("{stem}.mkv")), b"video").unwrap();
    let srt = (1..=10)
        .map(|index| {
            format!(
                "{index}\n00:00:{index:02},000 --> 00:00:{index:02},900\nEnglish line {index}.\n\n"
            )
        })
        .collect::<String>();
    fs::write(local.join(format!("{stem}.en.srt")), &srt).unwrap();
    fs::write(local.join(format!("{stem}.emb.srt")), &srt).unwrap();

    let mut config = support::config(root.path(), &configured_source, &destination);
    config.source = StorageConfig::Ftp {
        host: "127.0.0.1".into(),
        port: 65534,
        username_env: "SUBTRANS_TEST_MISSING_USERNAME".into(),
        password_env: "SUBTRANS_TEST_MISSING_PASSWORD".into(),
        root: "/Downloads".into(),
        timeout_seconds: 1,
        allow_plaintext: true,
    };
    let config_path = root.path().join("subtrans.toml");
    fs::write(&config_path, toml::to_string_pretty(&config).unwrap()).unwrap();

    let output = subtrans()
        .args(["subtitles", "--config"])
        .arg(&config_path)
        .arg("--local-dir")
        .arg(&local)
        .arg("--dry-run")
        .env_remove("SUBTRANS_TEST_MISSING_USERNAME")
        .env_remove("SUBTRANS_TEST_MISSING_PASSWORD")
        .output()
        .unwrap();
    assert!(output.status.success(), "{:?}", output);
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("subtitles local_mode root="));
    assert!(stdout.contains("migration=disabled"));
    assert!(stdout.contains(&format!("subtitles plan video={stem}.mkv")));
    assert!(!stdout.contains("plan_hash="));
}
