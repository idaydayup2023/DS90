#![allow(dead_code)]

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use sha2::{Digest, Sha256};
use subtrans::artifact::{ARTIFACT_SCHEMA, SubtitleArtifact, artifact_paths, video_identity};
use subtrans::config::{
    Config, LlmProvider, MigrationConfig, StateConfig, StorageConfig, SubtitleConfig,
    TranslationConfig,
};
use subtrans::storage::{LocalStorage, Storage};

pub fn config(root: &Path, source: &Path, destination: &Path) -> Config {
    Config {
        version: 3,
        state: StateConfig {
            database: root.join("state/subtrans.sqlite3"),
            lease_seconds: 120,
        },
        source: StorageConfig::Local {
            root: source.to_path_buf(),
        },
        destination: StorageConfig::Local {
            root: destination.to_path_buf(),
        },
        subtitles: SubtitleConfig {
            video_extensions: vec!["mkv".into(), "mp4".into()],
            min_video_bytes: 0,
            ffmpeg: "ffmpeg".into(),
            ffprobe: "ffprobe".into(),
            external_process_timeout_seconds: 120,
            asr: None,
            pgs_ocr: None,
        },
        translation: TranslationConfig {
            provider: LlmProvider::Ollama,
            base_url: "http://127.0.0.1:11434".into(),
            model: "test".into(),
            api_key_env: None,
            source_language: "English".into(),
            target_language: "Simplified Chinese".into(),
            bilingual: true,
            batch_size: 20,
            timeout_seconds: 30,
            max_retries: 0,
            max_batch_chars: 8_000,
            max_response_bytes: 1024 * 1024,
            min_target_script_ratio: 0.15,
        },
        migration: MigrationConfig {
            movie_1080_root: "Movies".into(),
            movie_4k_root: "Movies4K".into(),
            tv_1080_root: "TV".into(),
            tv_4k_root: "TV4K".into(),
            year_split: 2024,
            auto_apply_confidence: 0.95,
            sidecar_extensions: vec!["srt".into(), "nfo".into(), "json".into()],
            require_translated_subtitle: true,
            normalize_names: true,
            overrides: BTreeMap::new(),
        },
    }
}

pub fn write_ready_artifact(source_root: &Path, video_path: &str) {
    let storage = LocalStorage::new(source_root).unwrap();
    let video = storage.metadata(video_path).unwrap().unwrap();
    let paths = artifact_paths(video_path).unwrap();
    let stem = Path::new(video_path).file_stem().unwrap().to_string_lossy();
    let parent = Path::new(video_path)
        .parent()
        .and_then(Path::to_str)
        .unwrap_or("");
    let source_path = if parent.is_empty() {
        format!("{stem}.en.srt")
    } else {
        format!("{parent}/{stem}.en.srt")
    };
    let source_srt = b"1\n00:00:01,000 --> 00:00:02,000\nHello world\n\n";
    let output_srt = b"1\n00:00:01,000 --> 00:00:02,000\n\xE4\xBD\xA0\xE5\xA5\xBD\nHello world\n\n";
    if let Some(parent) = Path::new(&source_path).parent() {
        fs::create_dir_all(source_root.join(parent)).unwrap();
    }
    fs::write(source_root.join(&source_path), source_srt).unwrap();
    fs::write(source_root.join(&paths.output), output_srt).unwrap();
    let manifest = SubtitleArtifact {
        schema: ARTIFACT_SCHEMA,
        status: "ready".into(),
        video_path: video.path.clone(),
        video_identity_sha256: video_identity(&video),
        source_sha256: hash(source_srt),
        output_sha256: hash(output_srt),
        cache_key: "test-cache".into(),
        acquisition_key: "test-acquisition".into(),
        source_kind: "external_english".into(),
        source_path: Some(source_path),
        created_unix_seconds: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs(),
    };
    fs::write(
        source_root.join(paths.manifest),
        serde_json::to_vec_pretty(&manifest).unwrap(),
    )
    .unwrap();
}

fn hash(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}
