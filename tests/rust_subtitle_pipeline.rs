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
    let (base_url, server) = ollama_server(vec![Ok(vec![(1, "你好"), (2, "再见")])]);
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
    }
    let (base_url, server) = ollama_server(vec![Err(500), Ok(vec![(1, "你好")])]);
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

type Reply<'a> = Result<Vec<(u32, &'a str)>, u16>;

fn ollama_server(replies: Vec<Reply<'static>>) -> (String, thread::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let handle = thread::spawn(move || {
        for reply in replies {
            let (mut stream, _) = listener.accept().unwrap();
            read_request(&mut stream);
            match reply {
                Ok(lines) => {
                    let translation = serde_json::json!({
                        "translations": lines
                            .into_iter()
                            .map(|(index, text)| serde_json::json!({"index": index, "text": text}))
                            .collect::<Vec<_>>()
                    });
                    let body = serde_json::json!({"response": translation.to_string()}).to_string();
                    write_response(&mut stream, 200, &body);
                }
                Err(status) => write_response(&mut stream, status, "{\"error\":\"injected\"}"),
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
