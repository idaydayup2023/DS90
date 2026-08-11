mod support;

use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::thread;
use std::time::Duration;

use subtrans::artifact::read_ready_artifact;
use subtrans::migration::build_plan;
use subtrans::storage::{LocalStorage, Storage};
use tempfile::tempdir;

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
fn one_llm_failure_does_not_prevent_later_videos_from_publishing() {
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
        Reply::Translations(vec![(1, "你好")]),
    ]);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.translation.base_url = base_url;
    cfg.translation.max_retries = 0;
    assert!(subtrans::subtitles::run(&cfg, false, false, None).is_err());
    server.join().unwrap();
    assert!(
        !source
            .join("A.Movie.2026.WEB-DL.ai.srt.subtrans.json")
            .exists()
    );
    assert!(
        source
            .join("B.Movie.2026.WEB-DL.ai.srt.subtrans.json")
            .exists()
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
            (5, "回答我。"),
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
