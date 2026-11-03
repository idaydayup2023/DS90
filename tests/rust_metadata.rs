mod support;

use std::collections::BTreeMap;
use std::fs;

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

    let metadata = support::FixtureMetadata::movie(JPEG.to_vec());
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.metadata = metadata_config(
        "https://api.themoviedb.org/3",
        video,
        "SUBTRANS_TEST_TMDB_TOKEN_MOVIE",
    );
    unsafe { std::env::set_var("SUBTRANS_TEST_TMDB_TOKEN_MOVIE", "secret-token") };

    let summary =
        subtrans::metadata::run_with(&cfg, FetchMode::Default, false, None, Some(&metadata))
            .unwrap();
    assert_eq!(summary.fetched, 1);
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
    let metadata = support::FixtureMetadata::ambiguous_search();
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.metadata = metadata_config(
        "https://api.themoviedb.org/3",
        "unused.mkv",
        "SUBTRANS_TEST_TMDB_TOKEN_AMBIGUOUS",
    );
    cfg.metadata.overrides.clear();
    cfg.translation.base_url = "http://127.0.0.1:1".into();
    unsafe { std::env::set_var("SUBTRANS_TEST_TMDB_TOKEN_AMBIGUOUS", "secret-token") };

    let error =
        subtrans::subtitles::run_with(&cfg, false, false, None, None, Some(&metadata)).unwrap_err();
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
    let metadata = support::FixtureMetadata::movie(JPEG.to_vec());
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.metadata = metadata_config(
        "https://api.themoviedb.org/3",
        video,
        "SUBTRANS_TEST_TMDB_TOKEN_SUPPLEMENT",
    );
    unsafe { std::env::set_var("SUBTRANS_TEST_TMDB_TOKEN_SUPPLEMENT", "secret-token") };

    subtrans::metadata::run_with(&cfg, FetchMode::Supplement, false, None, Some(&metadata))
        .unwrap();
    assert_eq!(
        fs::read(source.join(format!("{stem}.jpg"))).unwrap(),
        b"manual-poster"
    );
    assert!(source.join(format!("{stem}.nfo")).exists());

    // Invalidating a managed file triggers a normal refresh, but the poster that
    // supplement mode marked as user-managed must still not be overwritten.
    fs::write(source.join(format!("{stem}.nfo")), b"damaged").unwrap();
    subtrans::metadata::run_with(&cfg, FetchMode::Default, false, None, Some(&metadata)).unwrap();
    assert_eq!(
        fs::read(source.join(format!("{stem}.jpg"))).unwrap(),
        b"manual-poster"
    );

    subtrans::metadata::run_with(&cfg, FetchMode::Force, false, None, Some(&metadata)).unwrap();
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
    let metadata = support::FixtureMetadata::tv(JPEG.to_vec());
    let mut cfg = support::config(root.path(), &source, &destination);
    cfg.metadata = metadata_config(
        "https://api.themoviedb.org/3",
        video,
        "SUBTRANS_TEST_TMDB_TOKEN_TV",
    );
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

    subtrans::metadata::run_with(&cfg, FetchMode::Default, false, None, Some(&metadata)).unwrap();
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
