#![allow(dead_code)]

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use sha2::{Digest, Sha256};
use subtrans::artifact::{ARTIFACT_SCHEMA, SubtitleArtifact, artifact_paths, video_identity};
use subtrans::config::{
    AlphabetGroup, Config, ExternalSrtValidationConfig, LlmProvider, MetadataConfig,
    MigrationConfig, MigrationLayout, MigrationLayouts, StateConfig, StorageConfig, SubtitleConfig,
    TranslationConfig,
};
use subtrans::storage::{LocalStorage, Storage};

pub fn config(root: &Path, source: &Path, destination: &Path) -> Config {
    Config {
        version: 3,
        scan: Default::default(),
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
        metadata: MetadataConfig::default(),
        subtitles: SubtitleConfig {
            video_extensions: vec!["mkv".into(), "mp4".into()],
            min_video_bytes: 0,
            ffmpeg: "ffmpeg".into(),
            ffprobe: "ffprobe".into(),
            external_process_timeout_seconds: 120,
            external_srt_validation: ExternalSrtValidationConfig::default(),
            asr: None,
            pgs_ocr: None,
        },
        translation: TranslationConfig {
            provider: LlmProvider::Ollama,
            base_url: "http://127.0.0.1:11434".into(),
            model: "test".into(),
            consistency_model: None,
            alignment_model: None,
            api_key_env: None,
            source_language: "English".into(),
            source_language_code: "en".into(),
            target_language: "Simplified Chinese".into(),
            target_language_code: "zh-CN".into(),
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
        migration: migration_config(true),
    }
}

pub fn migration_config(require_translated_subtitle: bool) -> MigrationConfig {
    MigrationConfig {
        layouts: MigrationLayouts {
            movie_4k: MigrationLayout {
                root: "Movies4K".into(),
                directory_template: "{year_bucket}/{release_dir}".into(),
                filename_template: "{source_file}".into(),
                recent_year_from: Some(1900),
                alphabet_groups: Vec::new(),
            },
            movie_other: MigrationLayout {
                root: "Movies".into(),
                directory_template: "{year_bucket}/{release_dir}".into(),
                filename_template: "{source_file}".into(),
                recent_year_from: Some(2024),
                alphabet_groups: Vec::new(),
            },
            tv_4k: MigrationLayout {
                root: "TV4K".into(),
                directory_template: "{alpha_group}/{title_dot}/S{season_padded}".into(),
                filename_template: "{source_file}".into(),
                recent_year_from: None,
                alphabet_groups: vec![AlphabetGroup {
                    letters: "ABCDEFGHIJKLMNOPQRSTUVWXYZ".into(),
                    directory: "[A-Z]".into(),
                }],
            },
            tv_other: MigrationLayout {
                root: "TV".into(),
                directory_template: "{title_dot}/S{season_padded}".into(),
                filename_template: "{source_file}".into(),
                recent_year_from: None,
                alphabet_groups: Vec::new(),
            },
        },
        auto_apply_confidence: 0.95,
        sidecar_extensions: vec!["srt".into(), "nfo".into(), "json".into()],
        incomplete_marker_extensions: vec!["aria2".into(), "part".into()],
        require_translated_subtitle,
        generic_source_directories: vec!["incoming".into()],
        title_routes: BTreeMap::new(),
        overrides: BTreeMap::new(),
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
        source_evidence: None,
        translation_quality_log: Vec::new(),
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

use std::collections::VecDeque;
use std::sync::Mutex;

use anyhow::{Result, bail};
use subtrans::remote::{LlmClient, LlmCompletion, LlmProbe, MetadataSource};

pub enum LlmReply {
    Text(String),
    Failure,
}

pub struct ScriptedLlm {
    replies: Mutex<VecDeque<LlmReply>>,
}

impl ScriptedLlm {
    pub fn new(replies: Vec<LlmReply>) -> Self {
        Self {
            replies: Mutex::new(VecDeque::from(replies)),
        }
    }
}

pub fn translations(lines: &[(u32, &str)]) -> LlmReply {
    LlmReply::Text(model_lines("translations", lines))
}

pub fn corrections(lines: &[(u32, &str)]) -> LlmReply {
    LlmReply::Text(model_lines("corrections", lines))
}

pub fn malformed(body: &str) -> LlmReply {
    LlmReply::Text(body.to_owned())
}

pub fn failure() -> LlmReply {
    LlmReply::Failure
}

fn model_lines(field: &str, lines: &[(u32, &str)]) -> String {
    let items: Vec<_> = lines
        .iter()
        .map(|(index, text)| serde_json::json!({"index": index, "text": text}))
        .collect();
    serde_json::json!({field: items}).to_string()
}

impl LlmClient for ScriptedLlm {
    fn complete(&self, _request: &LlmCompletion<'_>) -> Result<String> {
        match self.replies.lock().expect("scripted LLM lock").pop_front() {
            Some(LlmReply::Text(text)) => Ok(text),
            Some(LlmReply::Failure) => {
                bail!("translation service rejected the scripted model call")
            }
            None => bail!("scripted LLM has no remaining replies"),
        }
    }

    fn probe(&self, _request: &LlmProbe<'_>) -> Result<String> {
        Ok(r#"{"models":[]}"#.to_owned())
    }
}

pub enum FixtureKind {
    Movie,
    AmbiguousSearch,
    Tv,
}

pub struct FixtureMetadata {
    kind: FixtureKind,
    image: Vec<u8>,
}

impl FixtureMetadata {
    pub fn movie(image: Vec<u8>) -> Self {
        Self {
            kind: FixtureKind::Movie,
            image,
        }
    }

    pub fn ambiguous_search() -> Self {
        Self {
            kind: FixtureKind::AmbiguousSearch,
            image: Vec::new(),
        }
    }

    pub fn tv(image: Vec<u8>) -> Self {
        Self {
            kind: FixtureKind::Tv,
            image,
        }
    }
}

impl MetadataSource for FixtureMetadata {
    fn get_json(&self, endpoint: &str, _parameters: &[(&str, &str)]) -> Result<Vec<u8>> {
        let body = match self.kind {
            FixtureKind::Movie => {
                r#"{"id":42,"title":"超级少女","original_title":"Supergirl","overview":"A hero.","tagline":"Hope","release_date":"2026-06-01","runtime":120,"vote_average":8.1,"genres":[{"name":"Action"}],"production_companies":[{"name":"Studio"}],"production_countries":[{"name":"USA"}],"credits":{"crew":[{"name":"Director","job":"Director"}],"cast":[{"name":"Actor","character":"Hero"}]},"imdb_id":"tt1234567","poster_path":"/poster.jpg","backdrop_path":"/backdrop.jpg"}"#
            }
            FixtureKind::AmbiguousSearch => {
                r#"{"results":[{"id":1,"title":"Ambiguous Movie","release_date":"2026-01-01"},{"id":2,"title":"Ambiguous Movie","release_date":"2026-02-02"}]}"#
            }
            FixtureKind::Tv if endpoint.contains("/season/") => {
                r#"{"id":990102,"name":"第二集","overview":"分集简介","air_date":"2026-01-02","runtime":50,"vote_average":8.2,"still_path":"/still.jpg"}"#
            }
            FixtureKind::Tv => {
                r#"{"id":99,"name":"示例剧","original_name":"Example Show","overview":"剧集简介","first_air_date":"2026-01-01","genres":[{"name":"Drama"}],"production_companies":[{"name":"Studio"}],"poster_path":"/show-poster.jpg","backdrop_path":"/show-backdrop.jpg"}"#
            }
        };
        Ok(body.as_bytes().to_vec())
    }

    fn get_image(&self, _path: &str) -> Result<Vec<u8>> {
        Ok(self.image.clone())
    }
}
