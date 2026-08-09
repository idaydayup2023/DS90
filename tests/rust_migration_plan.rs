use std::fs;

use subtrans::config::{
    Config, LlmProvider, MigrationConfig, StateConfig, StorageConfig, SubtitleConfig,
    TranslationConfig,
};
use subtrans::migration::{MediaKind, PlanDocument, PlanStatus, build_plan, classify_path};
use tempfile::TempDir;

#[test]
fn classifies_explicit_4k_episodes_without_using_quality_as_kind() {
    let sxx = classify_path("Foundation.4K/Season 02/Foundation.S02E03.2160p.UHD.HEVC.mkv");
    assert_eq!(sxx.kind, MediaKind::Tv);
    assert_eq!((sxx.season, sxx.episode), (Some(2), Some(3)));
    assert!(sxx.is_4k);

    let one_x = classify_path("Foundation/02x03/Foundation.2x03.HDR.DV.mkv");
    assert_eq!(one_x.kind, MediaKind::Tv);
    assert_eq!((one_x.season, one_x.episode), (Some(2), Some(3)));
    assert!(!one_x.is_4k, "HDR/DV alone do not prove 4K resolution");

    let season_episode = classify_path("Slow Horses/Season 04/Episode 05.2160p.HEVC.mkv");
    assert_eq!(season_episode.kind, MediaKind::Tv);
    assert_eq!(
        (season_episode.season, season_episode.episode),
        (Some(4), Some(5))
    );

    let chinese = classify_path("庆余年/第2季/庆余年.第12集.4K.HEVC.mkv");
    assert_eq!(chinese.kind, MediaKind::Tv);
    assert_eq!((chinese.season, chinese.episode), (Some(2), Some(12)));
}

#[test]
fn classifies_4k_movies_and_never_treats_franchise_numbers_as_episodes() {
    let movie = classify_path("Movies.4K/Dune.Part.Two.2024.2160p.UHD.WEB-DL.HEVC.mkv");
    assert_eq!(movie.kind, MediaKind::Movie);
    assert_eq!(movie.year, Some(2024));
    assert_eq!(movie.episode, None);

    let franchise = classify_path("Movies.4K/Mission.Impossible.7.2023.2160p.UHD.BluRay.HEVC.mkv");
    assert_eq!(franchise.kind, MediaKind::Movie);
    assert_eq!(franchise.episode, None);
}

#[test]
fn supergirl_is_a_movie_and_never_receives_s01e01() {
    let source = concat!(
        "Supergirl.2026.2160p.iT.WEB-DL.DV.HDR10+.MULTi.",
        "DDP5.1.Atmos.H265.MP4-BTM.mkv"
    );
    let decision = classify_path(source);
    assert_eq!(decision.kind, MediaKind::Movie);
    assert_eq!(decision.season, None);
    assert_eq!(decision.episode, None);
    assert!(
        decision
            .evidence
            .iter()
            .any(|item| item.code == "movie_release_signature")
    );
}

#[test]
fn incomplete_or_quality_only_evidence_is_pending() {
    let incomplete = classify_path("Show.Name.4K/Season 01/Show.Name.2160p.HEVC.mkv");
    assert_eq!(incomplete.kind, MediaKind::Unknown);
    assert!(incomplete.is_pending());

    let quality_only = classify_path("Ambiguous.Title.2024.4K.UHD.2160p.HEVC.HDR.DV.mkv");
    assert_eq!(quality_only.kind, MediaKind::Unknown);
    assert!(quality_only.is_pending());
}

#[test]
fn classification_golden_edges_remain_auditable() {
    let special = classify_path("Doctor.Who/Season 00/Doctor.Who.S00E01.2160p.WEB-DL.mkv");
    assert_eq!(special.kind, MediaKind::Tv);
    assert_eq!((special.season, special.episode), (Some(0), Some(1)));

    let multi = classify_path("Show.Name.S02E03-E04.2160p.WEB-DL.mkv");
    assert_eq!(multi.kind, MediaKind::Unknown);
    assert!(multi.is_pending());

    let dated_show = classify_path("Daily.Show.2026.08.09.2160p.WEB-DL.mkv");
    assert_eq!(dated_show.kind, MediaKind::Unknown);
    assert!(dated_show.is_pending());

    let numeric_title = classify_path("2001.A.Space.Odyssey.1968.2160p.BluRay.mkv");
    assert_eq!(numeric_title.kind, MediaKind::Movie);
    assert_eq!(numeric_title.year, Some(1968));
    assert_eq!(numeric_title.title.as_deref(), Some("2001 A Space Odyssey"));

    let anime = classify_path("Anime.Title.[01].1080p.HEVC.mkv");
    assert_eq!(anime.kind, MediaKind::Unknown);
    assert!(
        anime.is_pending(),
        "anime numbering needs an explicit override"
    );
}

#[test]
fn plan_contains_fingerprint_evidence_sidecars_and_stable_hash() {
    let fixture = TempDir::new().unwrap();
    let source = fixture.path().join("source");
    let destination = fixture.path().join("destination");
    fs::create_dir_all(source.join("incoming")).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let video_name = "Supergirl.2026.2160p.WEB-DL.HEVC.mkv";
    fs::write(source.join("incoming").join(video_name), b"video bytes").unwrap();
    fs::write(
        source.join("incoming/Supergirl.2026.2160p.WEB-DL.HEVC.ai.srt"),
        b"subtitle bytes",
    )
    .unwrap();

    let config = config_for(fixture.path(), &source, &destination);
    let plan = build_plan(&config, None).unwrap();
    assert_eq!(plan.items.len(), 1);
    assert_eq!(plan.pending_count(), 0);
    let item = &plan.items[0];
    assert!(matches!(item.status, PlanStatus::Ready));
    assert!(!item.source_fingerprint.identity_sha256.is_empty());
    assert!(!item.classification.evidence.is_empty());
    assert_eq!(item.sidecar_actions.len(), 1);
    assert!(
        item.destination
            .as_deref()
            .unwrap()
            .starts_with("Movies4K/2026/")
    );
    assert!(!item.destination.as_deref().unwrap().contains("S01E01"));

    let plan_again = build_plan(&config, None).unwrap();
    assert_eq!(plan.plan_hash, plan_again.plan_hash);
    plan.verify_hash().unwrap();

    let plan_path = fixture.path().join("plan.json");
    plan.write(&plan_path).unwrap();
    let mut loaded = PlanDocument::read(&plan_path).unwrap();
    assert_eq!(loaded, plan);
    loaded.items[0].destination = Some("tampered/path.mkv".to_owned());
    assert!(loaded.verify_hash().is_err());
}

#[test]
fn pending_plan_has_no_destination_or_sidecar_actions() {
    let fixture = TempDir::new().unwrap();
    let source = fixture.path().join("source");
    let destination = fixture.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    fs::write(source.join("Ambiguous.2024.2160p.UHD.HEVC.mkv"), b"video").unwrap();

    let plan = build_plan(&config_for(fixture.path(), &source, &destination), None).unwrap();
    assert_eq!(plan.pending_count(), 1);
    assert!(plan.items[0].destination.is_none());
    assert!(plan.items[0].sidecar_actions.is_empty());
}

fn config_for(
    root: &std::path::Path,
    source: &std::path::Path,
    destination: &std::path::Path,
) -> Config {
    Config {
        version: 3,
        state: StateConfig {
            database: root.join("state.sqlite3"),
            lease_seconds: 120,
        },
        source: StorageConfig::Local {
            root: source.to_path_buf(),
        },
        destination: StorageConfig::Local {
            root: destination.to_path_buf(),
        },
        subtitles: SubtitleConfig {
            video_extensions: vec!["mkv".to_owned()],
            min_video_bytes: 0,
            ffmpeg: "ffmpeg".to_owned(),
            ffprobe: "ffprobe".to_owned(),
            external_process_timeout_seconds: 120,
            asr: None,
            pgs_ocr: None,
        },
        translation: TranslationConfig {
            provider: LlmProvider::Ollama,
            base_url: "http://127.0.0.1:11434".to_owned(),
            model: "test".to_owned(),
            api_key_env: None,
            source_language: "English".to_owned(),
            target_language: "Simplified Chinese".to_owned(),
            bilingual: true,
            batch_size: 20,
            timeout_seconds: 30,
            max_retries: 0,
            max_batch_chars: 8_000,
            max_response_bytes: 1024 * 1024,
            min_target_script_ratio: 0.15,
        },
        migration: MigrationConfig {
            movie_1080_root: "Movies".to_owned(),
            movie_4k_root: "Movies4K".to_owned(),
            tv_1080_root: "TV".to_owned(),
            tv_4k_root: "TV4K".to_owned(),
            year_split: 2024,
            auto_apply_confidence: 0.95,
            sidecar_extensions: vec!["srt".to_owned(), "nfo".to_owned(), "json".to_owned()],
            require_translated_subtitle: false,
            normalize_names: true,
            overrides: Default::default(),
        },
    }
}
