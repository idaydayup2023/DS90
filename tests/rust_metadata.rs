mod support;

use std::collections::BTreeMap;
use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::thread;

use subtrans::config::{MetadataConfig, MetadataOverride, OverrideKind};
use subtrans::metadata::{FetchMode, MetadataManifest};
use subtrans::migration::build_plan;
use tempfile::tempdir;

const JPEG: &[u8] = &[0xff, 0xd8, 0xff, 0xd9];

#[test]
fn tmdb_movie_artifacts_are_infuse_named_validated_and_cached() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    fs::create_dir_all(source.join("nested")).unwrap();
    let video = "nested/Supergirl.2026.2160p.WEB-DL.mkv";
    fs::write(source.join(video), b"video").unwrap();

    let (base_url, server) = tmdb_server(4);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.metadata = metadata_config(&base_url, video, "SUBTRANS_TEST_TMDB_TOKEN_MOVIE");
    unsafe { std::env::set_var("SUBTRANS_TEST_TMDB_TOKEN_MOVIE", "secret-token") };

    let summary = subtrans::metadata::run(&cfg, FetchMode::Default, false, None).unwrap();
    assert_eq!(summary.fetched, 1);
    server.join().unwrap();
    let stem = "nested/Supergirl.2026.2160p.WEB-DL";
    assert_eq!(fs::read(source.join(format!("{stem}.jpg"))).unwrap(), JPEG);
    assert_eq!(
        fs::read(source.join(format!("{stem}-fanart.jpg"))).unwrap(),
        JPEG
    );
    let nfo = fs::read_to_string(source.join(format!("{stem}.nfo"))).unwrap();
    assert!(nfo.contains("<movie>"));
    assert!(nfo.contains("<uniqueid type=\"tmdb\" default=\"true\">42</uniqueid>"));
    assert!(nfo.contains("<director>Director</director>"));
    assert!(nfo.contains("<name>Actor</name>"));
    assert!(nfo.contains("<role>Hero</role>"));
    let manifest: MetadataManifest = serde_json::from_slice(
        &fs::read(source.join(format!("{stem}.subtrans.metadata.json"))).unwrap(),
    )
    .unwrap();
    assert_eq!(manifest.tmdb_id, 42);
    assert_eq!(manifest.artifacts.len(), 3);

    // The mock server is gone. A complete, hash-valid manifest must avoid all network calls.
    unsafe { std::env::remove_var("SUBTRANS_TEST_TMDB_TOKEN_MOVIE") };
    let cached = subtrans::metadata::run(&cfg, FetchMode::Default, false, None).unwrap();
    assert_eq!(cached.cached, 1);
    cfg.migration.require_translated_subtitle = false;
    cfg.migration.sidecar_extensions.push("jpg".into());
    let plan = build_plan(&cfg, None).unwrap();
    assert_eq!(plan.pending_count(), 0);
    let sidecars: Vec<_> = plan.items[0]
        .sidecar_actions
        .iter()
        .map(|action| action.source.as_str())
        .collect();
    assert!(sidecars.iter().any(|path| path.ends_with(".nfo")));
    assert!(sidecars.iter().any(|path| path.ends_with(".jpg")));
    assert!(
        sidecars
            .iter()
            .any(|path| path.ends_with(".subtrans.metadata.json"))
    );
}

#[test]
fn ambiguous_tmdb_match_blocks_translation_before_the_llm_is_called() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "Ambiguous.Movie.2026.WEB-DL";
    fs::write(source.join(format!("{stem}.mkv")), b"video").unwrap();
    fs::write(
        source.join(format!("{stem}.en.srt")),
        "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n",
    )
    .unwrap();
    let (base_url, server) = ambiguous_search_server();
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.metadata = metadata_config(
        &base_url,
        "unused.mkv",
        "SUBTRANS_TEST_TMDB_TOKEN_AMBIGUOUS",
    );
    cfg.metadata.overrides.clear();
    cfg.translation.base_url = "http://127.0.0.1:1".into();
    unsafe { std::env::set_var("SUBTRANS_TEST_TMDB_TOKEN_AMBIGUOUS", "secret-token") };

    let error = subtrans::subtitles::run(&cfg, false, false, None).unwrap_err();
    server.join().unwrap();
    let message = format!("{error:#}");
    assert!(message.contains("ambiguous"));
    assert!(message.contains("metadata prerequisite"));
    assert!(!source.join(format!("{stem}.ai.srt")).exists());
    unsafe { std::env::remove_var("SUBTRANS_TEST_TMDB_TOKEN_AMBIGUOUS") };
}

#[test]
fn supplement_preserves_existing_poster_while_force_replaces_it() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let video = "Manual.Poster.2026.WEB-DL.mkv";
    let stem = "Manual.Poster.2026.WEB-DL";
    fs::write(source.join(video), b"video").unwrap();
    fs::write(source.join(format!("{stem}.jpg")), b"manual-poster").unwrap();
    let (base_url, server) = tmdb_server(4);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.metadata = metadata_config(&base_url, video, "SUBTRANS_TEST_TMDB_TOKEN_SUPPLEMENT");
    unsafe { std::env::set_var("SUBTRANS_TEST_TMDB_TOKEN_SUPPLEMENT", "secret-token") };

    subtrans::metadata::run(&cfg, FetchMode::Supplement, false, None).unwrap();
    server.join().unwrap();
    assert_eq!(
        fs::read(source.join(format!("{stem}.jpg"))).unwrap(),
        b"manual-poster"
    );
    assert!(source.join(format!("{stem}.nfo")).exists());

    // Invalidating a managed file triggers a normal refresh, but the poster that
    // supplement mode marked as user-managed must still not be overwritten.
    fs::write(source.join(format!("{stem}.nfo")), b"damaged").unwrap();
    let (base_url, server) = tmdb_server(4);
    cfg.metadata.base_url = base_url.clone();
    cfg.metadata.image_base_url = format!("{base_url}/images");
    subtrans::metadata::run(&cfg, FetchMode::Default, false, None).unwrap();
    server.join().unwrap();
    assert_eq!(
        fs::read(source.join(format!("{stem}.jpg"))).unwrap(),
        b"manual-poster"
    );

    let (base_url, server) = tmdb_server(4);
    cfg.metadata.base_url = base_url.clone();
    cfg.metadata.image_base_url = format!("{base_url}/images");
    subtrans::metadata::run(&cfg, FetchMode::Force, false, None).unwrap();
    server.join().unwrap();
    assert_eq!(fs::read(source.join(format!("{stem}.jpg"))).unwrap(), JPEG);
    unsafe { std::env::remove_var("SUBTRANS_TEST_TMDB_TOKEN_SUPPLEMENT") };
}

#[test]
fn tmdb_tv_episode_writes_infuse_episode_artwork_and_nfo() {
    let root = tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let video = "Show.Name.S01E02.2160p.WEB-DL.mkv";
    let stem = "Show.Name.S01E02.2160p.WEB-DL";
    fs::write(source.join(video), b"episode").unwrap();
    let (base_url, server) = tv_server(6);
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.metadata = metadata_config(&base_url, video, "SUBTRANS_TEST_TMDB_TOKEN_TV");
    cfg.metadata.overrides.insert(
        video.into(),
        MetadataOverride {
            kind: OverrideKind::Tv,
            tmdb_id: 99,
            season: Some(1),
            episode: Some(2),
        },
    );
    unsafe { std::env::set_var("SUBTRANS_TEST_TMDB_TOKEN_TV", "secret-token") };

    subtrans::metadata::run(&cfg, FetchMode::Default, false, None).unwrap();
    server.join().unwrap();
    assert_eq!(fs::read(source.join(format!("{stem}.jpg"))).unwrap(), JPEG);
    let nfo = fs::read_to_string(source.join(format!("{stem}.nfo"))).unwrap();
    assert!(nfo.contains("<episodedetails>"));
    assert!(nfo.contains("<title>第二集</title>"));
    assert!(nfo.contains("<showtitle>示例剧</showtitle>"));
    assert!(nfo.contains("<season>1</season>"));
    assert!(nfo.contains("<episode>2</episode>"));
    assert!(nfo.contains("<uniqueid type=\"tmdb\" default=\"true\">990102</uniqueid>"));
    let manifest: MetadataManifest = serde_json::from_slice(
        &fs::read(source.join(format!("{stem}.subtrans.metadata.json"))).unwrap(),
    )
    .unwrap();
    assert_eq!(manifest.tmdb_id, 99);
    assert_eq!(manifest.episode_tmdb_id, Some(990102));
    unsafe { std::env::remove_var("SUBTRANS_TEST_TMDB_TOKEN_TV") };
}

fn metadata_config(base_url: &str, video: &str, token_env: &str) -> MetadataConfig {
    MetadataConfig {
        enabled: true,
        base_url: base_url.into(),
        image_base_url: format!("{base_url}/images"),
        api_token_env: token_env.into(),
        language: "zh-CN".into(),
        fallback_language: "en-US".into(),
        timeout_seconds: 2,
        max_retries: 0,
        max_response_bytes: 1024 * 1024,
        max_image_bytes: 1024 * 1024,
        match_threshold: 0.85,
        ambiguity_gap: 0.08,
        refresh_after_days: 180,
        overrides: BTreeMap::from([(
            video.into(),
            MetadataOverride {
                kind: OverrideKind::Movie,
                tmdb_id: 42,
                season: None,
                episode: None,
            },
        )]),
    }
}

fn tmdb_server(request_count: usize) -> (String, thread::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let handle = thread::spawn(move || {
        for stream in listener.incoming().take(request_count) {
            respond(stream.unwrap());
        }
    });
    (format!("http://{address}"), handle)
}

fn ambiguous_search_server() -> (String, thread::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let handle = thread::spawn(move || {
        let stream = listener.incoming().next().unwrap().unwrap();
        respond_json(
            stream,
            r#"{"results":[{"id":1,"title":"Ambiguous Movie","release_date":"2026-01-01"},{"id":2,"title":"Ambiguous Movie","release_date":"2026-02-02"}]}"#,
        );
    });
    (format!("http://{address}"), handle)
}

fn tv_server(request_count: usize) -> (String, thread::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let handle = thread::spawn(move || {
        for stream in listener.incoming().take(request_count) {
            let mut stream = stream.unwrap();
            let mut request = [0u8; 4096];
            let read = stream.read(&mut request).unwrap();
            let request = String::from_utf8_lossy(&request[..read]);
            let target = request.split_whitespace().nth(1).unwrap_or("/");
            let (content_type, body): (&str, Vec<u8>) = if target.starts_with("/images/") {
                ("image/jpeg", JPEG.to_vec())
            } else if target.starts_with("/tv/99/season/1/episode/2") {
                (
                    "application/json",
                    r#"{"id":990102,"name":"第二集","overview":"分集简介","air_date":"2026-01-02","runtime":50,"vote_average":8.2,"still_path":"/still.jpg"}"#
                        .as_bytes()
                        .to_vec(),
                )
            } else {
                (
                    "application/json",
                    r#"{"id":99,"name":"示例剧","original_name":"Example Show","overview":"剧集简介","first_air_date":"2026-01-01","genres":[{"name":"Drama"}],"production_companies":[{"name":"Studio"}],"poster_path":"/show-poster.jpg","backdrop_path":"/show-backdrop.jpg"}"#
                        .as_bytes()
                        .to_vec(),
                )
            };
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            )
            .unwrap();
            stream.write_all(&body).unwrap();
        }
    });
    (format!("http://{address}"), handle)
}

fn respond(mut stream: TcpStream) {
    let mut request = [0u8; 4096];
    let read = stream.read(&mut request).unwrap();
    let request = String::from_utf8_lossy(&request[..read]);
    let target = request.split_whitespace().nth(1).unwrap_or("/");
    let (content_type, body): (&str, Vec<u8>) = if target.starts_with("/images/") {
        ("image/jpeg", JPEG.to_vec())
    } else {
        (
            "application/json",
            r#"{"id":42,"title":"超级少女","original_title":"Supergirl","overview":"A hero.","tagline":"Hope","release_date":"2026-06-01","runtime":120,"vote_average":8.1,"genres":[{"name":"Action"}],"production_companies":[{"name":"Studio"}],"production_countries":[{"name":"USA"}],"credits":{"crew":[{"name":"Director","job":"Director"}],"cast":[{"name":"Actor","character":"Hero"}]},"imdb_id":"tt1234567","poster_path":"/poster.jpg","backdrop_path":"/backdrop.jpg"}"#
                .as_bytes()
                .to_vec(),
        )
    };
    write!(
        stream,
        "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    )
    .unwrap();
    stream.write_all(&body).unwrap();
}

fn respond_json(mut stream: TcpStream, body: &str) {
    let mut request = [0u8; 4096];
    let _ = stream.read(&mut request).unwrap();
    write!(
        stream,
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.len(),
        body
    )
    .unwrap();
}
