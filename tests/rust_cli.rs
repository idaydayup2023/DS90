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
    let planned_stdout = String::from_utf8_lossy(&planned.stdout);
    let planned_line = planned_stdout.trim();
    assert!(planned_line.starts_with("plan_hash="), "{planned_line}");
    assert!(planned_line.contains(" items="), "{planned_line}");
    assert!(planned_line.contains(" pending="), "{planned_line}");

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
    assert!(output.contains("  reason:"));
    assert!(output.contains("  override key: "));
}

#[test]
fn json_channel_reports_plan_and_pending_without_replacing_the_plan_file() {
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
    let human_plan = root.path().join("human.json");
    let json_plan = root.path().join("json.json");

    let human = subtrans()
        .args(["migrate", "plan", "--config"])
        .arg(&config_path)
        .arg("--output")
        .arg(&human_plan)
        .output()
        .unwrap();
    assert!(human.status.success(), "{:?}", human);
    let human_stdout = String::from_utf8_lossy(&human.stdout);
    assert!(human_stdout.contains("plan_hash="));
    assert!(!human_stdout.contains("\"event\""));

    let json_after = subtrans()
        .args(["migrate", "plan", "--config"])
        .arg(&config_path)
        .arg("--output")
        .arg(&json_plan)
        .arg("--json")
        .output()
        .unwrap();
    assert!(json_after.status.success(), "{:?}", json_after);
    let events = json_lines(&json_after.stdout);
    let ready = events
        .iter()
        .find(|value| value["event"] == "plan.ready")
        .expect("plan.ready event");
    let written: serde_json::Value =
        serde_json::from_slice(&fs::read(&json_plan).unwrap()).unwrap();
    assert_eq!(ready["plan_hash"], written["plan_hash"]);
    assert_eq!(ready["items"], written["items"].as_array().unwrap().len());
    assert!(ready["pending"].is_number());
    let stdout = String::from_utf8_lossy(&json_after.stdout);
    assert!(!stdout.contains("plan_hash="), "{stdout}");
    assert!(json_after.stderr.is_empty(), "{:?}", json_after);

    let json_before = subtrans()
        .args(["--json", "migrate", "plan", "--config"])
        .arg(&config_path)
        .arg("--output")
        .arg(&json_plan)
        .output()
        .unwrap();
    assert!(json_before.status.success(), "{:?}", json_before);
    assert!(json_lines(&json_before.stdout).iter().any(|value| {
        value["event"] == "plan.ready" && value["plan_hash"] == written["plan_hash"]
    }));

    let human_doc: serde_json::Value =
        serde_json::from_slice(&fs::read(&human_plan).unwrap()).unwrap();
    assert_eq!(human_doc["plan_hash"], written["plan_hash"]);

    let reviewed = subtrans()
        .args(["--json", "migrate", "review", "--config"])
        .arg(&config_path)
        .arg("--plan")
        .arg(&json_plan)
        .output()
        .unwrap();
    assert!(reviewed.status.success(), "{:?}", reviewed);
    let review_stdout = String::from_utf8_lossy(&reviewed.stdout);
    assert!(!review_stdout.contains("PENDING "), "{review_stdout}");
    assert!(!review_stdout.contains("plan_hash="), "{review_stdout}");
    let pending = json_lines(&reviewed.stdout)
        .into_iter()
        .find(|value| value["event"] == "migrate.pending")
        .expect("migrate.pending event");
    assert_eq!(pending["source"], video);
    assert!(
        pending["reason"]
            .as_str()
            .is_some_and(|reason| !reason.is_empty())
    );
    assert_eq!(
        pending["override_key"],
        r#"[migration.overrides."Anime.Title.[01].1080p.HEVC.mkv"]"#
    );
}

#[test]
fn json_channel_reports_an_empty_directory_without_changing_the_sentence() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    let local = root.path().join("local");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    fs::create_dir_all(&local).unwrap();
    let config = support::config(root.path(), &source, &destination);
    let config_path = root.path().join("subtrans.toml");
    fs::write(&config_path, toml::to_string_pretty(&config).unwrap()).unwrap();

    let human = subtrans()
        .args(["subtitles", "--config"])
        .arg(&config_path)
        .arg("--local-dir")
        .arg(&local)
        .arg("--dry-run")
        .output()
        .unwrap();
    assert!(human.status.success(), "{:?}", human);
    let stdout = String::from_utf8_lossy(&human.stdout);
    assert!(stdout.contains("scan empty_dir path=(root)"));
    assert!(stdout.contains("subtitles local_mode root="));

    let json = subtrans()
        .args(["subtitles", "--config"])
        .arg(&config_path)
        .arg("--local-dir")
        .arg(&local)
        .arg("--dry-run")
        .arg("--json")
        .output()
        .unwrap();
    assert!(json.status.success(), "{:?}", json);
    let events = json_lines(&json.stdout);
    assert!(
        events
            .iter()
            .any(|value| { value["event"] == "scan.empty_dir" && value["path"] == "(root)" })
    );
    let json_stdout = String::from_utf8_lossy(&json.stdout);
    assert!(
        !json_stdout.contains("scan empty_dir path="),
        "{json_stdout}"
    );
}

fn json_lines(stdout: &[u8]) -> Vec<serde_json::Value> {
    String::from_utf8_lossy(stdout)
        .lines()
        .filter(|line| !line.is_empty())
        .map(|line| serde_json::from_str(line).unwrap_or_else(|error| panic!("{error} in {line}")))
        .collect()
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
