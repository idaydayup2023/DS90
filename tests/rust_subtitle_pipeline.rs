mod support;

use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::thread;
use std::time::Duration;

use subtrans::artifact::read_ready_artifact;
use subtrans::migration::build_plan;
use subtrans::storage::{LocalStorage, Storage};
use tempfile::tempdir;

#[cfg(unix)]
fn executable_script(path: &std::path::Path, contents: &str) {
    fs::write(path, contents).unwrap();
    let mut permissions = fs::metadata(path).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(path, permissions).unwrap();
}

#[test]
fn translated_artifact_unlocks_migration_and_is_reused_without_llm() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let video = "Supergirl.2026.2160p.WEB-DL.mkv";
    fs::write(source.join(video), b"video").unwrap();
    fs::write(
        source.join("Supergirl.2026.2160p.WEB-DL.en.srt"),
        "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n2\n00:00:03,000 --> 00:00:04,000\nGoodbye\n\n",
    )
    .unwrap();
    fs::write(
        source.join("Supergirl.2026.2160p.WEB-DL.emb.srt"),
        "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n2\n00:00:03,000 --> 00:00:04,000\nGoodbye\n\n",
    )
    .unwrap();
    let (base_url, server) =
        ollama_server(vec![Reply::Translations(vec![(1, "你好"), (2, "再见")])]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();
    let storage = LocalStorage::new(&source).unwrap();
    let entry = storage.metadata(video).unwrap().unwrap();
    assert!(read_ready_artifact(&storage, &entry).unwrap().is_some());
    assert_eq!(build_plan(&cfg, None).unwrap().pending_count(), 0);

    // The server is gone; a second run succeeds only by validating the complete artifact.
    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
}

#[test]
fn one_translation_failure_is_repaired_by_review_and_later_videos_publish() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    for name in ["A.Movie.2026.WEB-DL", "B.Movie.2026.WEB-DL"] {
        fs::write(source.join(format!("{name}.mkv")), name.as_bytes()).unwrap();
        fs::write(
            source.join(format!("{name}.en.srt")),
            "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n",
        )
        .unwrap();
        fs::write(
            source.join(format!("{name}.emb.srt")),
            "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n",
        )
        .unwrap();
    }
    let (base_url, server) = ollama_server(vec![
        Reply::Error(500),
        Reply::Corrections(vec![(1, "你好")]),
        Reply::Translations(vec![(1, "你好")]),
    ]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;
    cfg.translation.max_retries = 0;
    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();
    assert!(
        source
            .join("A.Movie.2026.WEB-DL.ai.srt.subtrans.json")
            .exists()
    );
    assert!(
        source
            .join("B.Movie.2026.WEB-DL.ai.srt.subtrans.json")
            .exists()
    );
    let first = fs::read_to_string(source.join("A.Movie.2026.WEB-DL.ai.srt")).unwrap();
    let second = fs::read_to_string(source.join("B.Movie.2026.WEB-DL.ai.srt")).unwrap();
    assert!(first.contains("你好\nHello"));
    assert!(second.contains("你好\nHello"));
    let first_manifest = fs::read(source.join("A.Movie.2026.WEB-DL.ai.srt.subtrans.json")).unwrap();
    let first_manifest: subtrans::artifact::SubtitleArtifact =
        serde_json::from_slice(&first_manifest).unwrap();
    assert_eq!(first_manifest.translation_quality_log.len(), 1);
    assert!(
        first_manifest.translation_quality_log[0]
            .reasons
            .iter()
            .any(|reason| reason == "primary_translation_failed")
    );
}

#[test]
fn untranslated_english_candidate_is_replaced_by_review_and_logged() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "English.Echo.Movie.2026.WEB-DL";
    fs::write(source.join(format!("{stem}.mkv")), b"video").unwrap();
    let srt = "1\n00:00:01,000 --> 00:00:02,000\nThis stayed English.\n\n";
    fs::write(source.join(format!("{stem}.en.srt")), srt).unwrap();
    fs::write(source.join(format!("{stem}.emb.srt")), srt).unwrap();
    let (base_url, server) = ollama_server(vec![
        Reply::Translations(vec![(1, "This stayed English.")]),
        Reply::Corrections(vec![(1, "这仍然是英文。")]),
    ]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let output = fs::read_to_string(source.join(format!("{stem}.ai.srt"))).unwrap();
    assert!(output.contains("这仍然是英文。\nThis stayed English."));
    assert!(!output.contains("[?]"));
    let manifest = fs::read(source.join(format!("{stem}.ai.srt.subtrans.json"))).unwrap();
    let manifest: subtrans::artifact::SubtitleArtifact = serde_json::from_slice(&manifest).unwrap();
    let record = &manifest.translation_quality_log[0];
    assert_eq!(record.candidate_before_review, "This stayed English.");
    assert_eq!(record.reviewed_translation, "这仍然是英文。");
    assert!(
        record
            .reasons
            .iter()
            .any(|reason| reason == "source_text_repeated_unchanged")
    );
}

#[test]
fn incomplete_download_marker_blocks_subtitle_writes() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let video = "Downloading.Movie.2026.WEB-DL.mkv";
    fs::write(source.join(video), b"partial video").unwrap();
    fs::write(
        source.join("Downloading.Movie.2026.WEB-DL.en.srt"),
        "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n",
    )
    .unwrap();
    fs::write(source.join(format!("{video}.aria2")), b"active").unwrap();
    let cfg = support::config(root.path(), &source, &destination);

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();

    assert!(!source.join("Downloading.Movie.2026.WEB-DL.ai.srt").exists());
    assert!(source.join(format!("{video}.aria2")).exists());
}

#[test]
fn mismatched_external_srt_is_rejected_in_favor_of_embedded_english() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let video = "Cross.Checked.Movie.2026.WEB-DL.mkv";
    fs::write(source.join(video), b"video").unwrap();
    fs::write(
        source.join("Cross.Checked.Movie.2026.WEB-DL.en.srt"),
        "1\n00:10:01,000 --> 00:10:02,000\nWrong title\n\n2\n00:10:03,000 --> 00:10:04,000\nWrong dialogue\n\n",
    )
    .unwrap();
    fs::write(
        source.join("Cross.Checked.Movie.2026.WEB-DL.emb.srt"),
        "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n2\n00:00:03,000 --> 00:00:04,000\nGoodbye\n\n",
    )
    .unwrap();
    let (base_url, server) =
        ollama_server(vec![Reply::Translations(vec![(1, "你好"), (2, "再见")])]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let storage = LocalStorage::new(&source).unwrap();
    let entry = storage.metadata(video).unwrap().unwrap();
    let manifest = read_ready_artifact(&storage, &entry).unwrap().unwrap();
    assert_eq!(manifest.source_kind, "embedded_cached");
    assert_eq!(
        manifest.source_path.as_deref(),
        Some("Cross.Checked.Movie.2026.WEB-DL.emb.srt")
    );
    let evidence = manifest.source_evidence.unwrap();
    assert_eq!(evidence.decision, "embedded_selected_external_mismatch");
    assert_eq!(
        evidence.external_path,
        "Cross.Checked.Movie.2026.WEB-DL.en.srt"
    );
    assert_eq!(evidence.timing_match_ratio, 0.0);
    assert_eq!(evidence.text_similarity, 0.0);
}

#[cfg(unix)]
#[test]
fn external_english_is_trusted_when_video_has_no_embedded_english() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "External.Only.Movie.2026.WEB-DL";
    let video = format!("{stem}.mkv");
    fs::write(source.join(&video), b"video").unwrap();
    fs::write(
        source.join(format!("{stem}.en.srt")),
        "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n",
    )
    .unwrap();
    let ffprobe = root.path().join("fake-ffprobe");
    executable_script(&ffprobe, "#!/bin/sh\nprintf '{\"streams\":[]}'\n");
    let (base_url, server) = ollama_server(vec![Reply::Translations(vec![(1, "你好")])]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.subtitles.ffprobe = ffprobe.to_string_lossy().into_owned();
    cfg.translation.base_url = base_url;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let storage = LocalStorage::new(&source).unwrap();
    let entry = storage.metadata(&video).unwrap().unwrap();
    let manifest = read_ready_artifact(&storage, &entry).unwrap().unwrap();
    assert_eq!(manifest.source_kind, "external_english");
    let evidence = manifest.source_evidence.unwrap();
    assert_eq!(evidence.decision, "external_selected_no_embedded_english");
    assert_eq!(evidence.embedded_kind, "none");
}

#[cfg(unix)]
#[test]
fn asr_is_used_when_external_and_embedded_english_are_both_absent() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "Asr.Only.Movie.2026.WEB-DL";
    let video = format!("{stem}.mkv");
    fs::write(source.join(&video), b"video").unwrap();
    let ffprobe = root.path().join("fake-ffprobe");
    executable_script(&ffprobe, "#!/bin/sh\nprintf '{\"streams\":[]}'\n");
    let asr = root.path().join("fake-asr");
    executable_script(
        &asr,
        "#!/bin/sh\noutput=''\nwhile [ \"$#\" -gt 0 ]; do\n  if [ \"$1\" = '--output' ]; then output=$2; shift 2; else shift; fi\ndone\nprintf '1\\n00:00:01,000 --> 00:00:02,000\\nRecognized speech\\n\\n' > \"$output\"\n",
    );
    let (base_url, server) = ollama_server(vec![Reply::Translations(vec![(1, "识别出的语音")])]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.subtitles.ffprobe = ffprobe.to_string_lossy().into_owned();
    cfg.subtitles.asr = Some(subtrans::config::ExternalWorkerConfig {
        command: asr.to_string_lossy().into_owned(),
        args: vec![
            "--input".into(),
            "{input}".into(),
            "--output".into(),
            "{output}".into(),
            "--language".into(),
            "{language}".into(),
        ],
        version_args: vec!["--version".into()],
        enabled: true,
        version: "fake-asr-1".into(),
    });
    cfg.translation.base_url = base_url;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let storage = LocalStorage::new(&source).unwrap();
    let entry = storage.metadata(&video).unwrap().unwrap();
    let manifest = read_ready_artifact(&storage, &entry).unwrap().unwrap();
    assert_eq!(manifest.source_kind, "asr");
    assert!(source.join(format!("{stem}.asr.srt")).is_file());
}

#[cfg(unix)]
#[test]
fn missing_asr_configuration_reports_exact_recovery_steps() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    fs::write(source.join("No.Subtitles.Movie.2026.mkv"), b"video").unwrap();
    let ffprobe = root.path().join("fake-ffprobe");
    executable_script(&ffprobe, "#!/bin/sh\nprintf '{\"streams\":[]}'\n");
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.subtitles.ffprobe = ffprobe.to_string_lossy().into_owned();

    let error = subtrans::subtitles::run(&cfg, false, false, None).unwrap_err();
    let message = format!("{error:#}");
    assert!(message.contains("ASR is required"));
    assert!(message.contains("[subtitles.asr]"));
    assert!(message.contains("whisper.cpp"));
    assert!(message.contains("subtrans doctor"));
}

#[test]
fn failed_large_translation_batch_is_split_and_retried_sequentially() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "Adaptive.Batch.Movie.2026.WEB-DL";
    fs::write(source.join(format!("{stem}.mkv")), b"video").unwrap();
    let srt = "1\n00:00:01,000 --> 00:00:02,000\nOne\n\n2\n00:00:03,000 --> 00:00:04,000\nTwo\n\n3\n00:00:05,000 --> 00:00:06,000\nThree\n\n4\n00:00:07,000 --> 00:00:08,000\nFour\n\n";
    fs::write(source.join(format!("{stem}.en.srt")), srt).unwrap();
    fs::write(source.join(format!("{stem}.emb.srt")), srt).unwrap();
    let (base_url, server) = ollama_server(vec![
        Reply::Error(500),
        Reply::Translations(vec![(1, "一"), (2, "二")]),
        Reply::Translations(vec![(3, "三"), (4, "四")]),
    ]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;
    cfg.translation.batch_size = 4;
    cfg.translation.min_batch_size = 2;
    cfg.translation.context_cues = 1;
    cfg.translation.max_retries = 0;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let output = fs::read_to_string(source.join(format!("{stem}.ai.srt"))).unwrap();
    for text in ["一", "二", "三", "四"] {
        assert!(output.contains(text));
    }
}

#[test]
fn malformed_model_json_is_split_immediately_instead_of_retried_unchanged() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "Malformed.Json.Movie.2026.WEB-DL";
    fs::write(source.join(format!("{stem}.mkv")), b"video").unwrap();
    let srt = "1\n00:00:01,000 --> 00:00:02,000\nOne\n\n2\n00:00:03,000 --> 00:00:04,000\nTwo\n\n3\n00:00:05,000 --> 00:00:06,000\nThree\n\n4\n00:00:07,000 --> 00:00:08,000\nFour\n\n";
    fs::write(source.join(format!("{stem}.en.srt")), srt).unwrap();
    fs::write(source.join(format!("{stem}.emb.srt")), srt).unwrap();
    let (base_url, server) = ollama_server(vec![
        Reply::Malformed(r#"{"translations":[{"index":1,"translation":"坏结构"}]}"#),
        Reply::Translations(vec![(1, "一"), (2, "二")]),
        Reply::Translations(vec![(3, "三"), (4, "四")]),
    ]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;
    cfg.translation.batch_size = 4;
    cfg.translation.min_batch_size = 1;
    cfg.translation.max_retries = 2;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let output = fs::read_to_string(source.join(format!("{stem}.ai.srt"))).unwrap();
    for text in ["一", "二", "三", "四"] {
        assert!(output.contains(text));
    }
}

#[test]
fn repeatedly_malformed_single_cue_is_repaired_once_by_review_model() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "Malformed.Single.Cue.Movie.2026.WEB-DL";
    fs::write(source.join(format!("{stem}.mkv")), b"video").unwrap();
    let srt = "1\n00:00:01,000 --> 00:00:02,000\nKeep me safe\n\n2\n00:00:03,000 --> 00:00:04,000\nTranslate me\n\n";
    fs::write(source.join(format!("{stem}.en.srt")), srt).unwrap();
    fs::write(source.join(format!("{stem}.emb.srt")), srt).unwrap();
    let (base_url, server) = ollama_server(vec![
        // The malformed two-cue response is split immediately. Cue 1 then
        // fails all three strict singleton attempts and enters final review.
        Reply::Malformed("not-json"),
        Reply::Malformed("still-not-json"),
        Reply::Malformed("truncated"),
        Reply::Malformed("duplicate-index"),
        Reply::Translations(vec![(2, "翻译我")]),
        Reply::Corrections(vec![(1, "请小心")]),
    ]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;
    cfg.translation.batch_size = 2;
    cfg.translation.min_batch_size = 1;
    cfg.translation.max_retries = 2;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let output = fs::read_to_string(source.join(format!("{stem}.ai.srt"))).unwrap();
    let cues = subtrans::subtitles::parse_srt(&output).unwrap();
    assert_eq!(cues[0].text, "请小心\nKeep me safe");
    assert_eq!(cues[1].text, "翻译我\nTranslate me");
    assert!(
        source
            .join(format!("{stem}.ai.srt.subtrans.json"))
            .is_file()
    );
    let manifest = fs::read(source.join(format!("{stem}.ai.srt.subtrans.json"))).unwrap();
    let manifest: subtrans::artifact::SubtitleArtifact = serde_json::from_slice(&manifest).unwrap();
    assert_eq!(manifest.translation_quality_log.len(), 1);
    assert_eq!(manifest.translation_quality_log[0].cue_index, 1);
}

#[test]
fn omitted_repeated_cue_is_repaired_without_retranslating_valid_items() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "Repeated.Dialogue.Movie.2026.WEB-DL";
    fs::write(source.join(format!("{stem}.mkv")), b"video").unwrap();
    let srt = "1\n00:00:01,000 --> 00:00:02,000\nJace.\n\n2\n00:00:03,000 --> 00:00:04,000\nJace.\n\n3\n00:00:05,000 --> 00:00:06,000\nWhat have you done?\n\n4\n00:00:07,000 --> 00:00:08,000\nWhat have you done?\n\n5\n00:00:09,000 --> 00:00:10,000\nAnswer me.\n\n";
    fs::write(source.join(format!("{stem}.en.srt")), srt).unwrap();
    fs::write(source.join(format!("{stem}.emb.srt")), srt).unwrap();
    let (base_url, server) = ollama_server(vec![
        Reply::Translations(vec![
            (1, "杰斯。"),
            (3, "你做了什么？"),
            (4, "你做了什么？"),
        ]),
        Reply::Translations(vec![(2, "杰斯。")]),
        Reply::Translations(vec![(5, "回答我。")]),
    ]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;
    cfg.translation.batch_size = 4;
    cfg.translation.min_batch_size = 2;
    cfg.translation.context_cues = 1;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let output = fs::read_to_string(source.join(format!("{stem}.ai.srt"))).unwrap();
    assert_eq!(output.matches("杰斯。").count(), 2);
    assert_eq!(output.matches("你做了什么？").count(), 2);
    assert_eq!(output.matches("回答我。").count(), 1);
}

#[test]
fn complete_subtitle_consistency_review_applies_only_returned_corrections() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "Consistency.Movie.2026.WEB-DL";
    fs::write(source.join(format!("{stem}.mkv")), b"video").unwrap();
    let srt = "1\n00:00:01,000 --> 00:00:02,000\nHello John\n\n2\n00:00:03,000 --> 00:00:04,000\nGoodbye John\n\n";
    fs::write(source.join(format!("{stem}.en.srt")), srt).unwrap();
    fs::write(source.join(format!("{stem}.emb.srt")), srt).unwrap();
    let (base_url, server) = ollama_server(vec![
        Reply::Translations(vec![(1, "你好，约翰"), (2, "再见，强")]),
        Reply::Malformed(r#"{"corrections":[{"index":2,"text":"再见，约翰"," ":"invalid"}]}"#),
        Reply::Corrections(vec![(2, "再见，约翰")]),
    ]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;
    cfg.translation.consistency_check = true;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let output = fs::read_to_string(source.join(format!("{stem}.ai.srt"))).unwrap();
    assert!(output.contains("你好，约翰"));
    assert!(output.contains("再见，约翰"));
    assert!(!output.contains("再见，强"));
}

#[test]
fn cue_alignment_review_repairs_neighbor_shift_without_changing_source_timing() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "Alignment.Movie.2026.WEB-DL";
    fs::write(source.join(format!("{stem}.mkv")), b"video").unwrap();
    let srt = "1\n00:00:01,000 --> 00:00:02,000\nSmash it to pieces.\n\n2\n00:00:03,000 --> 00:00:04,000\nLeave now.\n\n3\n00:00:05,000 --> 00:00:06,000\nAnswer me.\n\n";
    fs::write(source.join(format!("{stem}.en.srt")), srt).unwrap();
    fs::write(source.join(format!("{stem}.emb.srt")), srt).unwrap();
    let (base_url, server) = ollama_server(vec![
        Reply::Translations(vec![(1, "现在离开。"), (2, "回答我。"), (3, "把它砸碎。")]),
        Reply::Corrections(vec![(1, "把它砸碎。"), (2, "现在离开。"), (3, "回答我。")]),
    ]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;
    cfg.translation.alignment_check = true;
    cfg.translation.alignment_batch_size = 3;
    cfg.translation.alignment_context_cues = 1;
    cfg.translation.alignment_max_corrections = 3;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let output = fs::read_to_string(source.join(format!("{stem}.ai.srt"))).unwrap();
    let cues = subtrans::subtitles::parse_srt(&output).unwrap();
    assert_eq!(cues.len(), 3);
    assert_eq!(cues[0].start_ms, 1_000);
    assert_eq!(cues[0].text, "把它砸碎。\nSmash it to pieces.");
    assert_eq!(cues[1].text, "现在离开。\nLeave now.");
    assert_eq!(cues[2].text, "回答我。\nAnswer me.");
}

#[test]
fn malformed_alignment_batch_is_split_until_exact_indices_are_auditable() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "Adaptive.Alignment.Movie.2026.WEB-DL";
    fs::write(source.join(format!("{stem}.mkv")), b"video").unwrap();
    let srt = "1\n00:00:01,000 --> 00:00:02,000\nFirst.\n\n2\n00:00:03,000 --> 00:00:04,000\nSecond.\n\n3\n00:00:05,000 --> 00:00:06,000\nThird.\n\n4\n00:00:07,000 --> 00:00:08,000\nFourth.\n\n";
    fs::write(source.join(format!("{stem}.en.srt")), srt).unwrap();
    fs::write(source.join(format!("{stem}.emb.srt")), srt).unwrap();
    let (base_url, server) = ollama_server(vec![
        Reply::Translations(vec![
            (1, "第二。"),
            (2, "第三。"),
            (3, "第四。"),
            (4, "第一。"),
        ]),
        Reply::Malformed("not-json"),
        Reply::Malformed("still-not-json"),
        Reply::Corrections(vec![(1, "第一。"), (2, "第二。")]),
        Reply::Corrections(vec![(3, "第三。"), (4, "第四。")]),
    ]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;
    cfg.translation.alignment_check = true;
    cfg.translation.alignment_batch_size = 4;
    cfg.translation.alignment_context_cues = 1;
    cfg.translation.alignment_max_corrections = 4;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let output = fs::read_to_string(source.join(format!("{stem}.ai.srt"))).unwrap();
    assert!(output.contains("第一。\nFirst."));
    assert!(output.contains("第二。\nSecond."));
    assert!(output.contains("第三。\nThird."));
    assert!(output.contains("第四。\nFourth."));
}

#[test]
fn review_model_correction_is_final_without_iteration_and_is_logged() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "Ambiguous.Context.Movie.2026.WEB-DL";
    fs::write(source.join(format!("{stem}.mkv")), b"video").unwrap();
    let srt =
        "1\n00:00:01,000 --> 00:00:02,000\nDuck!\n\n2\n00:00:03,000 --> 00:00:04,000\nRun now.\n\n";
    fs::write(source.join(format!("{stem}.en.srt")), srt).unwrap();
    fs::write(source.join(format!("{stem}.emb.srt")), srt).unwrap();
    let (base_url, server) = ollama_server(vec![
        Reply::Translations(vec![(1, "鸭子！"), (2, "快跑。")]),
        Reply::Corrections(vec![(1, "低头！")]),
    ]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;
    cfg.translation.alignment_check = true;
    cfg.translation.alignment_batch_size = 2;
    cfg.translation.alignment_context_cues = 1;
    cfg.translation.alignment_max_corrections = 2;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let output = fs::read_to_string(source.join(format!("{stem}.ai.srt"))).unwrap();
    let cues = subtrans::subtitles::parse_srt(&output).unwrap();
    assert_eq!(cues[0].text, "低头！\nDuck!");
    assert_eq!(cues[1].text, "快跑。\nRun now.");
    assert!(!output.contains("[?]"));
    assert!(
        source
            .join(format!("{stem}.ai.srt.subtrans.json"))
            .is_file()
    );
    let manifest = fs::read(source.join(format!("{stem}.ai.srt.subtrans.json"))).unwrap();
    let manifest: subtrans::artifact::SubtitleArtifact = serde_json::from_slice(&manifest).unwrap();
    assert_eq!(manifest.translation_quality_log.len(), 1);
    assert_eq!(
        manifest.translation_quality_log[0].reasons,
        vec!["review_model_quality_correction"]
    );
}

#[test]
fn undecidable_single_cue_audit_error_does_not_block_publication() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "Uncertain.Audit.Movie.2026.WEB-DL";
    fs::write(source.join(format!("{stem}.mkv")), b"video").unwrap();
    let srt = "1\n00:00:01,000 --> 00:00:02,000\nFine.\n\n";
    fs::write(source.join(format!("{stem}.en.srt")), srt).unwrap();
    fs::write(source.join(format!("{stem}.emb.srt")), srt).unwrap();
    let (base_url, server) = ollama_server(vec![
        Reply::Translations(vec![(1, "好吧。")]),
        Reply::Malformed("uncertain"),
        Reply::Malformed("still-uncertain"),
    ]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;
    cfg.translation.alignment_check = true;
    cfg.translation.alignment_batch_size = 1;
    cfg.translation.alignment_context_cues = 0;
    cfg.translation.alignment_max_corrections = 1;

    subtrans::subtitles::run(&cfg, false, false, None).unwrap();
    server.join().unwrap();

    let output = fs::read_to_string(source.join(format!("{stem}.ai.srt"))).unwrap();
    assert!(output.contains("好吧。\nFine."));
}

enum Reply<'a> {
    Translations(Vec<(u32, &'a str)>),
    Corrections(Vec<(u32, &'a str)>),
    Malformed(&'a str),
    Error(u16),
}

fn ollama_server(replies: Vec<Reply<'static>>) -> (String, thread::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let handle = thread::spawn(move || {
        for reply in replies {
            let (mut stream, _) = listener.accept().unwrap();
            read_request(&mut stream);
            match reply {
                Reply::Translations(lines) => {
                    let generated = serde_json::json!({
                        "translations": lines
                            .into_iter()
                            .map(|(index, text)| serde_json::json!({"index": index, "text": text}))
                            .collect::<Vec<_>>()
                    });
                    let body = serde_json::json!({"response": generated.to_string()}).to_string();
                    write_response(&mut stream, 200, &body);
                }
                Reply::Corrections(lines) => {
                    let generated = serde_json::json!({
                        "corrections": lines
                            .into_iter()
                            .map(|(index, text)| serde_json::json!({"index": index, "text": text}))
                            .collect::<Vec<_>>()
                    });
                    let body = serde_json::json!({"response": generated.to_string()}).to_string();
                    write_response(&mut stream, 200, &body);
                }
                Reply::Malformed(generated) => {
                    let body = serde_json::json!({"response": generated}).to_string();
                    write_response(&mut stream, 200, &body);
                }
                Reply::Error(status) => {
                    write_response(&mut stream, status, "{\"error\":\"injected\"}")
                }
            }
        }
    });
    (format!("http://{address}"), handle)
}

fn read_request(stream: &mut TcpStream) {
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    let mut bytes = Vec::new();
    let mut buffer = [0_u8; 4096];
    loop {
        let count = stream.read(&mut buffer).unwrap_or(0);
        if count == 0 {
            break;
        }
        bytes.extend_from_slice(&buffer[..count]);
        if let Some(header_end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
            let headers = String::from_utf8_lossy(&bytes[..header_end]);
            let content_length = headers
                .lines()
                .find_map(|line| {
                    line.strip_prefix("content-length: ")
                        .or_else(|| line.strip_prefix("Content-Length: "))
                })
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(0);
            if bytes.len() >= header_end + 4 + content_length {
                break;
            }
        }
    }
}

fn write_response(stream: &mut TcpStream, status: u16, body: &str) {
    let reason = if status == 200 { "OK" } else { "Error" };
    write!(
        stream,
        "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )
    .unwrap();
    stream.flush().unwrap();
}
