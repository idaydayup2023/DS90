use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub version: u32,
    pub state: StateConfig,
    pub source: StorageConfig,
    pub destination: StorageConfig,
    pub subtitles: SubtitleConfig,
    pub translation: TranslationConfig,
    pub migration: MigrationConfig,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct StateConfig {
    pub database: PathBuf,
    #[serde(default = "default_lease_seconds")]
    pub lease_seconds: u64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "lowercase", deny_unknown_fields)]
pub enum StorageConfig {
    Local {
        root: PathBuf,
    },
    Ftp {
        host: String,
        #[serde(default = "default_ftp_port")]
        port: u16,
        username: String,
        password_env: String,
        #[serde(default = "default_storage_root")]
        root: String,
        #[serde(default = "default_ftp_timeout")]
        timeout_seconds: u64,
        #[serde(default)]
        allow_plaintext: bool,
    },
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SubtitleConfig {
    #[serde(default = "default_video_extensions")]
    pub video_extensions: Vec<String>,
    #[serde(default)]
    pub min_video_bytes: u64,
    #[serde(default = "default_ffmpeg")]
    pub ffmpeg: String,
    #[serde(default = "default_ffprobe")]
    pub ffprobe: String,
    #[serde(default = "default_external_process_timeout")]
    pub external_process_timeout_seconds: u64,
    #[serde(default)]
    pub asr: Option<ExternalWorkerConfig>,
    #[serde(default)]
    pub pgs_ocr: Option<ExternalWorkerConfig>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExternalWorkerConfig {
    pub command: String,
    #[serde(default)]
    pub args: Vec<String>,
    #[serde(default = "default_worker_version_args")]
    pub version_args: Vec<String>,
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub version: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TranslationConfig {
    pub provider: LlmProvider,
    pub base_url: String,
    pub model: String,
    #[serde(default)]
    pub api_key_env: Option<String>,
    #[serde(default = "default_source_language")]
    pub source_language: String,
    #[serde(default = "default_target_language")]
    pub target_language: String,
    #[serde(default = "default_true")]
    pub bilingual: bool,
    #[serde(default = "default_batch_size")]
    pub batch_size: usize,
    #[serde(default = "default_timeout")]
    pub timeout_seconds: u64,
    #[serde(default = "default_retries")]
    pub max_retries: u32,
    #[serde(default = "default_max_batch_chars")]
    pub max_batch_chars: usize,
    #[serde(default = "default_max_response_bytes")]
    pub max_response_bytes: usize,
    #[serde(default = "default_min_target_script_ratio")]
    pub min_target_script_ratio: f32,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LlmProvider {
    Ollama,
    OpenaiCompatible,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MigrationConfig {
    pub movie_1080_root: String,
    pub movie_4k_root: String,
    pub tv_1080_root: String,
    pub tv_4k_root: String,
    #[serde(default = "default_year_split")]
    pub year_split: u16,
    #[serde(default = "default_auto_apply_confidence")]
    pub auto_apply_confidence: f32,
    #[serde(default = "default_sidecar_extensions")]
    pub sidecar_extensions: Vec<String>,
    #[serde(default = "default_true")]
    pub require_translated_subtitle: bool,
    #[serde(default = "default_true")]
    pub normalize_names: bool,
    #[serde(default)]
    pub overrides: BTreeMap<String, MigrationOverride>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MigrationOverride {
    pub kind: OverrideKind,
    pub title: String,
    pub year: Option<u16>,
    pub season: Option<u16>,
    pub episode: Option<u16>,
    pub is_4k: Option<bool>,
    #[serde(default)]
    pub allow_untranslated: bool,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OverrideKind {
    Movie,
    Tv,
}

impl Config {
    pub fn load(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        let text = fs::read_to_string(path)
            .with_context(|| format!("failed to read config {}", path.display()))?;
        let cfg: Self =
            toml::from_str(&text).with_context(|| format!("invalid config {}", path.display()))?;
        cfg.validate()?;
        Ok(cfg)
    }

    pub fn validate(&self) -> Result<()> {
        if self.version != 3 {
            bail!("unsupported config version {}; expected 3", self.version);
        }
        if self.translation.batch_size == 0 {
            bail!("translation.batch_size must be greater than zero");
        }
        if self.translation.timeout_seconds == 0
            || self.subtitles.external_process_timeout_seconds == 0
        {
            bail!("translation and external process timeouts must be greater than zero");
        }
        if self.translation.max_batch_chars == 0 || self.translation.max_response_bytes < 1024 {
            bail!("translation size limits must be positive and max_response_bytes >= 1024");
        }
        if !(0.0..=1.0).contains(&self.translation.min_target_script_ratio) {
            bail!("translation.min_target_script_ratio must be between 0 and 1");
        }
        if self.state.lease_seconds < 30 {
            bail!("state.lease_seconds must be at least 30");
        }
        if !(0.0..=1.0).contains(&self.migration.auto_apply_confidence) {
            bail!("migration.auto_apply_confidence must be between 0 and 1");
        }
        let translation_url = reqwest::Url::parse(&self.translation.base_url)
            .context("translation.base_url must be a valid absolute URL")?;
        if !matches!(translation_url.scheme(), "http" | "https") {
            bail!("translation.base_url must use http or https");
        }
        validate_storage(&self.source, "source")?;
        validate_storage(&self.destination, "destination")?;
        validate_worker(self.subtitles.asr.as_ref(), "subtitles.asr")?;
        validate_worker(self.subtitles.pgs_ocr.as_ref(), "subtitles.pgs_ocr")?;
        for (name, value) in [
            ("movie_1080_root", &self.migration.movie_1080_root),
            ("movie_4k_root", &self.migration.movie_4k_root),
            ("tv_1080_root", &self.migration.tv_1080_root),
            ("tv_4k_root", &self.migration.tv_4k_root),
        ] {
            crate::storage::validate_relative_path(value)
                .with_context(|| format!("migration.{name} must be a safe relative path"))?;
            if value.is_empty() {
                bail!("migration.{name} must not be empty");
            }
        }
        for (path, decision) in &self.migration.overrides {
            crate::storage::validate_relative_path(path)
                .with_context(|| format!("unsafe migration override path {path:?}"))?;
            if decision.title.trim().is_empty() {
                bail!("migration override title must not be empty for {path}");
            }
            match decision.kind {
                OverrideKind::Movie if decision.year.is_none() => {
                    bail!("movie override requires year for {path}")
                }
                OverrideKind::Tv if decision.season.is_none() || decision.episode.is_none() => {
                    bail!("TV override requires season and episode for {path}")
                }
                _ => {}
            }
        }
        Ok(())
    }
}

fn validate_worker(worker: Option<&ExternalWorkerConfig>, name: &str) -> Result<()> {
    let Some(worker) = worker.filter(|worker| worker.enabled) else {
        return Ok(());
    };
    if worker.command.trim().is_empty() || worker.version.trim().is_empty() {
        bail!("{name} requires non-empty command and version when enabled");
    }
    if worker.version_args.is_empty() || worker.version_args.iter().any(|arg| arg.trim().is_empty())
    {
        bail!("{name}.version_args must contain a non-empty version probe command");
    }
    let joined = worker.args.join("\0");
    if !joined.contains("{input}") || !joined.contains("{output}") {
        bail!("{name}.args must contain both {{input}} and {{output}} placeholders");
    }
    for argument in &worker.args {
        let mut remainder = argument.as_str();
        while let Some(start) = remainder.find('{') {
            let tail = &remainder[start..];
            let Some(end) = tail.find('}') else {
                bail!("{name}.args contains an unclosed placeholder");
            };
            let placeholder = &tail[..=end];
            if !matches!(
                placeholder,
                "{input}" | "{output}" | "{language}" | "{stream}"
            ) {
                bail!("{name}.args contains unsupported placeholder {placeholder}");
            }
            remainder = &tail[end + 1..];
        }
    }
    Ok(())
}

impl StorageConfig {
    pub fn ftp_password(&self) -> Result<Option<String>> {
        match self {
            Self::Ftp { password_env, .. } => {
                let value = env::var(password_env).with_context(|| {
                    format!("missing FTP password environment variable {password_env}")
                })?;
                Ok(Some(value))
            }
            Self::Local { .. } => Ok(None),
        }
    }
}

impl TranslationConfig {
    pub fn api_key(&self) -> Result<Option<String>> {
        self.api_key_env
            .as_ref()
            .map(|name| {
                env::var(name)
                    .with_context(|| format!("missing API key environment variable {name}"))
            })
            .transpose()
    }
}

fn validate_storage(storage: &StorageConfig, name: &str) -> Result<()> {
    match storage {
        StorageConfig::Local { root } if root.as_os_str().is_empty() => {
            bail!("{name}.root must not be empty")
        }
        StorageConfig::Ftp {
            host,
            username,
            password_env,
            ..
        } if host.trim().is_empty()
            || username.trim().is_empty()
            || password_env.trim().is_empty() =>
        {
            bail!("{name} FTP host, username, and password_env are required")
        }
        StorageConfig::Ftp {
            timeout_seconds, ..
        } if *timeout_seconds == 0 => bail!("{name} FTP timeout_seconds must be positive"),
        StorageConfig::Ftp {
            allow_plaintext: false,
            ..
        } => bail!(
            "{name} uses FTP but plaintext access was not explicitly allowed; prefer a locally mounted NAS path or set allow_plaintext=true only on a trusted network"
        ),
        _ => Ok(()),
    }
}

fn default_ftp_port() -> u16 {
    21
}
fn default_ftp_timeout() -> u64 {
    120
}
fn default_lease_seconds() -> u64 {
    7_200
}
fn default_storage_root() -> String {
    "/".to_owned()
}
fn default_ffmpeg() -> String {
    "ffmpeg".to_owned()
}
fn default_ffprobe() -> String {
    "ffprobe".to_owned()
}
fn default_external_process_timeout() -> u64 {
    7_200
}
fn default_worker_version_args() -> Vec<String> {
    vec!["--version".to_owned()]
}
fn default_source_language() -> String {
    "English".to_owned()
}
fn default_target_language() -> String {
    "Simplified Chinese".to_owned()
}
fn default_true() -> bool {
    true
}
fn default_batch_size() -> usize {
    20
}
fn default_timeout() -> u64 {
    300
}
fn default_retries() -> u32 {
    2
}
fn default_max_batch_chars() -> usize {
    8_000
}
fn default_max_response_bytes() -> usize {
    4 * 1024 * 1024
}
fn default_min_target_script_ratio() -> f32 {
    0.15
}
fn default_year_split() -> u16 {
    2024
}
fn default_auto_apply_confidence() -> f32 {
    0.95
}

fn default_video_extensions() -> Vec<String> {
    ["mkv", "mp4", "avi", "mov", "m4v", "ts"]
        .into_iter()
        .map(str::to_owned)
        .collect()
}

fn default_sidecar_extensions() -> Vec<String> {
    ["srt", "ass", "ssa", "vtt", "nfo", "json"]
        .into_iter()
        .map(str::to_owned)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn distributed_example_is_valid_and_reproducible() {
        let cfg: Config = toml::from_str(include_str!("../config.example.toml")).unwrap();
        cfg.validate().unwrap();
        assert_eq!(cfg.state.lease_seconds, 7_200);
        assert!(cfg.migration.require_translated_subtitle);
    }

    #[test]
    fn rejects_wrong_version() {
        let raw = r#"
version = 2
[state]
database = "state.sqlite3"
[source]
kind = "local"
root = "in"
[destination]
kind = "local"
root = "out"
[subtitles]
[translation]
provider = "ollama"
base_url = "http://127.0.0.1:11434"
model = "m"
[migration]
movie_1080_root = "Movies"
movie_4k_root = "Movies4K"
tv_1080_root = "TV"
tv_4k_root = "TV4K"
"#;
        let cfg: Config = toml::from_str(raw).unwrap();
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn rejects_string_boolean() {
        let raw = r#"
version = 3
[state]
database = "state.sqlite3"
[source]
kind = "local"
root = "in"
[destination]
kind = "local"
root = "out"
[subtitles]
[translation]
provider = "ollama"
base_url = "http://127.0.0.1:11434"
model = "m"
bilingual = "false"
[migration]
movie_1080_root = "Movies"
movie_4k_root = "Movies4K"
tv_1080_root = "TV"
tv_4k_root = "TV4K"
"#;
        assert!(toml::from_str::<Config>(raw).is_err());
    }
}
