mod support;

use std::fs;

use subtrans::config::{
    AlphabetGroup, Config, ExternalSrtValidationConfig, LlmProvider, MigrationTitleRoute,
    StateConfig, StorageConfig, SubtitleConfig, TranslationConfig,
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
    assert!(item.source_fingerprint.content_sha256.is_some());
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
fn infuse_artwork_sidecars_follow_dot_normalized_video_name() {
    let fixture = TempDir::new().unwrap();
    let source = fixture.path().join("source");
    let destination = fixture.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let stem = "Movie Name 2026 WEB-DL";
    fs::write(source.join(format!("{stem}.mkv")), b"video").unwrap();
    fs::write(source.join(format!("{stem}.jpg")), b"poster").unwrap();
    fs::write(source.join(format!("{stem}-fanart.jpg")), b"fanart").unwrap();
    fs::write(source.join(format!("{stem}.nfo")), b"nfo").unwrap();

    let mut cfg = config_for(fixture.path(), &source, &destination);
    cfg.migration.layouts.movie_other.filename_template = "{source_file_dot}".into();
    cfg.migration.sidecar_extensions.push("jpg".into());
    let plan = build_plan(&cfg, None).unwrap();
    let destinations: Vec<_> = plan.items[0]
        .sidecar_actions
        .iter()
        .map(|action| action.destination.as_str())
        .collect();
    assert!(
        destinations
            .iter()
            .any(|path| path.ends_with("/Movie.Name.2026.WEB-DL.jpg"))
    );
    assert!(
        destinations
            .iter()
            .any(|path| path.ends_with("/Movie.Name.2026.WEB-DL-fanart.jpg"))
    );
    assert!(
        destinations
            .iter()
            .any(|path| path.ends_with("/Movie.Name.2026.WEB-DL.nfo"))
    );
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
    assert!(plan.items[0].source_fingerprint.content_sha256.is_none());
}

#[test]
fn db90_layouts_route_all_four_media_classes_from_configuration() {
    let fixture = TempDir::new().unwrap();
    let source = fixture.path().join("source");
    let destination = fixture.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let inputs = [
        (
            "Supergirl.2026.2160p.WEB-DL/Supergirl.2026.2160p.WEB-DL.HEVC.mkv",
            "MOVIE/2026/Supergirl.2026.2160p.WEB-DL/Supergirl.2026.2160p.WEB-DL.HEVC.mkv",
        ),
        (
            "House.S03.2160p/House of the Dragon S03E01 2160p WEB-DL.mkv",
            "TV/[G.H.I.J.K]/House.of.the.Dragon/S03/House.of.the.Dragon.S03E01.2160p.WEB-DL.mkv",
        ),
        (
            "low_imdb/the.hudsucker.proxy.1994.1080p.bluray.mkv",
            "X-Movie/1990s/the.hudsucker.proxy.1994.1080p.bluray/the.hudsucker.proxy.1994.1080p.bluray.mkv",
        ),
        (
            "download/Desperate.Housewives.S01E02.1080p.WEB-DL.mkv",
            "X-TV/Desperate.Housewives/S01/Desperate.Housewives.S01E02.1080p.WEB-DL.mkv",
        ),
    ];
    for (input, _) in inputs {
        let path = source.join(input);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, input.as_bytes()).unwrap();
    }

    let mut cfg = config_for(fixture.path(), &source, &destination);
    configure_db90_layouts(&mut cfg);
    let plan = build_plan(&cfg, None).unwrap();
    assert_eq!(plan.pending_count(), 0);
    for (input, expected) in inputs {
        let item = plan.items.iter().find(|item| item.source == input).unwrap();
        assert_eq!(item.destination.as_deref(), Some(expected));
    }
}

#[test]
fn title_routes_change_library_name_and_group_without_changing_media_kind() {
    let fixture = TempDir::new().unwrap();
    let source = fixture.path().join("source");
    let destination = fixture.path().join("destination");
    fs::create_dir_all(source.join("Lucky.Release")).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let input = "Lucky.Release/Lucky.2026.S01E02.2160p.WEB-DL.mkv";
    fs::write(source.join(input), b"episode").unwrap();
    let mut cfg = config_for(fixture.path(), &source, &destination);
    configure_db90_layouts(&mut cfg);
    cfg.migration.title_routes.insert(
        "Lucky 2026".into(),
        MigrationTitleRoute {
            title: Some("Lucky".into()),
            group: Some("[L.M.N]".into()),
        },
    );

    let plan = build_plan(&cfg, None).unwrap();
    assert_eq!(plan.items[0].classification.kind, MediaKind::Tv);
    assert_eq!(
        plan.items[0].destination.as_deref(),
        Some("TV/[L.M.N]/Lucky/S01/Lucky.2026.S01E02.2160p.WEB-DL.mkv")
    );
}

#[test]
fn episode_marked_sidecars_with_a_different_title_are_kept_with_the_episode() {
    let fixture = TempDir::new().unwrap();
    let source = fixture.path().join("source");
    let destination = fixture.path().join("destination");
    let release = source.join("Show.Release");
    fs::create_dir_all(&release).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let video = "Show.Release/House.of.the.Dragon.S03E02.2160p.WEB-DL.mkv";
    let subtitle = "Show.Release/龙之家族 第三季 House of the Dragon S03E02 简中.srt";
    fs::write(source.join(video), b"episode").unwrap();
    fs::write(source.join(subtitle), b"subtitle").unwrap();
    let mut cfg = config_for(fixture.path(), &source, &destination);
    configure_db90_layouts(&mut cfg);

    let plan = build_plan(&cfg, None).unwrap();
    let item = &plan.items[0];
    assert_eq!(item.sidecar_actions.len(), 1);
    assert_eq!(item.sidecar_actions[0].source, subtitle);
    assert_eq!(
        item.sidecar_actions[0].destination,
        "TV/[G.H.I.J.K]/House.of.the.Dragon/S03/龙之家族.第三季.House.of.the.Dragon.S03E02.简中.srt"
    );
}

#[test]
fn unsafe_or_incomplete_layout_templates_are_rejected() {
    let fixture = TempDir::new().unwrap();
    let source = fixture.path().join("source");
    let destination = fixture.path().join("destination");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&destination).unwrap();
    let mut cfg = config_for(fixture.path(), &source, &destination);
    cfg.migration.layouts.movie_4k.directory_template = "../{release_dir}".into();
    assert!(cfg.validate().is_err());

    let mut cfg = config_for(fixture.path(), &source, &destination);
    cfg.migration.layouts.tv_4k.alphabet_groups = vec![AlphabetGroup {
        letters: "ABC".into(),
        directory: "[A.B.C]".into(),
    }];
    assert!(cfg.validate().is_err());
}

fn configure_db90_layouts(cfg: &mut Config) {
    cfg.migration.layouts.movie_4k.root = "MOVIE".into();
    cfg.migration.layouts.movie_other.root = "X-Movie".into();
    cfg.migration.layouts.tv_4k.root = "TV".into();
    cfg.migration.layouts.tv_other.root = "X-TV".into();
    cfg.migration.layouts.movie_4k.filename_template = "{source_file_dot}".into();
    cfg.migration.layouts.movie_other.filename_template = "{source_file_dot}".into();
    cfg.migration.layouts.tv_4k.filename_template = "{source_file_dot}".into();
    cfg.migration.layouts.tv_other.filename_template = "{source_file_dot}".into();
    cfg.migration.generic_source_directories = vec!["low_imdb".into(), "download".into()];
    cfg.migration.layouts.tv_4k.alphabet_groups = vec![
        AlphabetGroup {
            letters: "ABC".into(),
            directory: "[A.B.C]".into(),
        },
        AlphabetGroup {
            letters: "DEF".into(),
            directory: "[D.E.F]".into(),
        },
        AlphabetGroup {
            letters: "GHIJK".into(),
            directory: "[G.H.I.J.K]".into(),
        },
        AlphabetGroup {
            letters: "LMN".into(),
            directory: "[L.M.N]".into(),
        },
        AlphabetGroup {
            letters: "OPQR".into(),
            directory: "[O.P.Q.R]".into(),
        },
        AlphabetGroup {
            letters: "S".into(),
            directory: "[S]".into(),
        },
        AlphabetGroup {
            letters: "T".into(),
            directory: "[T]".into(),
        },
        AlphabetGroup {
            letters: "UVWXYZ".into(),
            directory: "[U.V.W.Y.Z]".into(),
        },
    ];
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
        metadata: subtrans::config::MetadataConfig::default(),
        subtitles: SubtitleConfig {
            video_extensions: vec!["mkv".to_owned()],
            min_video_bytes: 0,
            ffmpeg: "ffmpeg".to_owned(),
            ffprobe: "ffprobe".to_owned(),
            external_process_timeout_seconds: 120,
            external_srt_validation: ExternalSrtValidationConfig::default(),
            asr: None,
            pgs_ocr: None,
        },
        translation: TranslationConfig {
            provider: LlmProvider::Ollama,
            base_url: "http://127.0.0.1:11434".to_owned(),
            model: "test".to_owned(),
            consistency_model: None,
            alignment_model: None,
            api_key_env: None,
            source_language: "English".to_owned(),
            source_language_code: "en".to_owned(),
            target_language: "Simplified Chinese".to_owned(),
            target_language_code: "zh-CN".to_owned(),
            bilingual: true,
            batch_size: 80,
            min_batch_size: 20,
            context_cues: 6,
            timeout_seconds: 30,
            max_retries: 0,
            max_batch_chars: 8_000,
            max_response_bytes: 1024 * 1024,
            max_output_tokens: 4_096,
            min_target_script_ratio: 0.15,
            consistency_check: false,
            consistency_max_chars: 120_000,
            consistency_max_corrections: 64,
            consistency_max_output_tokens: 4_096,
            alignment_check: false,
            alignment_batch_size: 32,
            alignment_context_cues: 6,
            alignment_max_corrections: 32,
            alignment_max_attempts: 3,
            alignment_max_output_tokens: 4_096,
        },
        migration: support::migration_config(false),
    }
}
