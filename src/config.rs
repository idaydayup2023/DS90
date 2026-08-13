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
    pub metadata: MetadataConfig,
    pub subtitles: SubtitleConfig,
    pub translation: TranslationConfig,
    pub migration: MigrationConfig,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MetadataConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_metadata_base_url")]
    pub base_url: String,
    #[serde(default = "default_metadata_image_base_url")]
    pub image_base_url: String,
    #[serde(default = "default_metadata_api_token_env")]
    pub api_token_env: String,
    #[serde(default = "default_metadata_language")]
    pub language: String,
    #[serde(default = "default_metadata_fallback_language")]
    pub fallback_language: String,
    #[serde(default = "default_metadata_timeout")]
    pub timeout_seconds: u64,
    #[serde(default = "default_metadata_retries")]
    pub max_retries: u32,
    #[serde(default = "default_metadata_max_response_bytes")]
    pub max_response_bytes: usize,
    #[serde(default = "default_metadata_max_image_bytes")]
    pub max_image_bytes: usize,
    #[serde(default = "default_metadata_match_threshold")]
    pub match_threshold: f32,
    #[serde(default = "default_metadata_ambiguity_gap")]
    pub ambiguity_gap: f32,
    #[serde(default = "default_metadata_refresh_after_days")]
    pub refresh_after_days: u16,
    #[serde(default)]
    pub overrides: BTreeMap<String, MetadataOverride>,
}

impl Default for MetadataConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            base_url: default_metadata_base_url(),
            image_base_url: default_metadata_image_base_url(),
            api_token_env: default_metadata_api_token_env(),
            language: default_metadata_language(),
            fallback_language: default_metadata_fallback_language(),
            timeout_seconds: default_metadata_timeout(),
            max_retries: default_metadata_retries(),
            max_response_bytes: default_metadata_max_response_bytes(),
            max_image_bytes: default_metadata_max_image_bytes(),
            match_threshold: default_metadata_match_threshold(),
            ambiguity_gap: default_metadata_ambiguity_gap(),
            refresh_after_days: default_metadata_refresh_after_days(),
            overrides: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MetadataOverride {
    pub kind: OverrideKind,
    pub tmdb_id: u64,
    #[serde(default)]
    pub season: Option<u16>,
    #[serde(default)]
    pub episode: Option<u16>,
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
        username_env: String,
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
    pub external_srt_validation: ExternalSrtValidationConfig,
    #[serde(default)]
    pub asr: Option<ExternalWorkerConfig>,
    #[serde(default)]
    pub pgs_ocr: Option<ExternalWorkerConfig>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExternalSrtValidationConfig {
    #[serde(default = "default_external_srt_min_timing_match_ratio")]
    pub min_timing_match_ratio: f32,
    #[serde(default = "default_external_srt_min_text_similarity")]
    pub min_text_similarity: f32,
    #[serde(default = "default_external_srt_quality_margin")]
    pub external_quality_margin: f32,
}

impl Default for ExternalSrtValidationConfig {
    fn default() -> Self {
        Self {
            min_timing_match_ratio: default_external_srt_min_timing_match_ratio(),
            min_text_similarity: default_external_srt_min_text_similarity(),
            external_quality_margin: default_external_srt_quality_margin(),
        }
    }
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
    pub consistency_model: Option<String>,
    #[serde(default)]
    pub alignment_model: Option<String>,
    #[serde(default)]
    pub api_key_env: Option<String>,
    #[serde(default = "default_source_language")]
    pub source_language: String,
    #[serde(default = "default_source_language_code")]
    pub source_language_code: String,
    #[serde(default = "default_target_language")]
    pub target_language: String,
    #[serde(default = "default_target_language_code")]
    pub target_language_code: String,
    #[serde(default = "default_true")]
    pub bilingual: bool,
    #[serde(default = "default_batch_size")]
    pub batch_size: usize,
    #[serde(default = "default_min_batch_size")]
    pub min_batch_size: usize,
    #[serde(default = "default_context_cues")]
    pub context_cues: usize,
    #[serde(default = "default_timeout")]
    pub timeout_seconds: u64,
    #[serde(default = "default_retries")]
    pub max_retries: u32,
    #[serde(default = "default_max_batch_chars")]
    pub max_batch_chars: usize,
    #[serde(default = "default_max_response_bytes")]
    pub max_response_bytes: usize,
    #[serde(default = "default_max_output_tokens")]
    pub max_output_tokens: u32,
    #[serde(default = "default_min_target_script_ratio")]
    pub min_target_script_ratio: f32,
    #[serde(default = "default_true")]
    pub consistency_check: bool,
    #[serde(default = "default_consistency_max_chars")]
    pub consistency_max_chars: usize,
    #[serde(default = "default_consistency_max_corrections")]
    pub consistency_max_corrections: usize,
    #[serde(default = "default_consistency_max_output_tokens")]
    pub consistency_max_output_tokens: u32,
    #[serde(default = "default_true")]
    pub alignment_check: bool,
    #[serde(default = "default_alignment_batch_size")]
    pub alignment_batch_size: usize,
    #[serde(default = "default_alignment_context_cues")]
    pub alignment_context_cues: usize,
    #[serde(default = "default_alignment_max_corrections")]
    pub alignment_max_corrections: usize,
    #[serde(default = "default_alignment_max_attempts")]
    pub alignment_max_attempts: u32,
    #[serde(default = "default_alignment_max_output_tokens")]
    pub alignment_max_output_tokens: u32,
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
    pub layouts: MigrationLayouts,
    #[serde(default = "default_auto_apply_confidence")]
    pub auto_apply_confidence: f32,
    #[serde(default = "default_sidecar_extensions")]
    pub sidecar_extensions: Vec<String>,
    #[serde(default = "default_incomplete_marker_extensions")]
    pub incomplete_marker_extensions: Vec<String>,
    #[serde(default = "default_true")]
    pub require_translated_subtitle: bool,
    #[serde(default)]
    pub generic_source_directories: Vec<String>,
    #[serde(default)]
    pub title_routes: BTreeMap<String, MigrationTitleRoute>,
    #[serde(default)]
    pub overrides: BTreeMap<String, MigrationOverride>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MigrationLayouts {
    pub movie_4k: MigrationLayout,
    pub movie_other: MigrationLayout,
    pub tv_4k: MigrationLayout,
    pub tv_other: MigrationLayout,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MigrationLayout {
    pub root: String,
    pub directory_template: String,
    pub filename_template: String,
    #[serde(default)]
    pub recent_year_from: Option<u16>,
    #[serde(default)]
    pub alphabet_groups: Vec<AlphabetGroup>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AlphabetGroup {
    pub letters: String,
    pub directory: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MigrationTitleRoute {
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub group: Option<String>,
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
        if self.translation.batch_size == 0
            || self.translation.min_batch_size == 0
            || self.translation.min_batch_size > self.translation.batch_size
        {
            bail!(
                "translation batch_size and min_batch_size must be positive, with min_batch_size <= batch_size"
            );
        }
        if self.translation.context_cues > self.translation.batch_size {
            bail!("translation.context_cues must not exceed batch_size");
        }
        if self.translation.timeout_seconds == 0
            || self.subtitles.external_process_timeout_seconds == 0
        {
            bail!("translation and external process timeouts must be greater than zero");
        }
        if self.translation.max_batch_chars == 0
            || self.translation.max_response_bytes < 1024
            || self.translation.max_output_tokens == 0
        {
            bail!("translation size limits must be positive and max_response_bytes >= 1024");
        }
        if self.translation.consistency_check
            && self.translation.consistency_max_chars < self.translation.max_batch_chars
        {
            bail!(
                "translation.consistency_max_chars must be at least max_batch_chars when consistency_check is enabled"
            );
        }
        if self.translation.consistency_check
            && (self.translation.consistency_max_corrections == 0
                || self.translation.consistency_max_output_tokens == 0)
        {
            bail!("translation consistency output limits must be positive when enabled");
        }
        if self.translation.alignment_check
            && (self.translation.alignment_batch_size == 0
                || self.translation.alignment_max_corrections == 0
                || self.translation.alignment_max_corrections
                    > self.translation.alignment_batch_size
                || self.translation.alignment_max_attempts == 0
                || self.translation.alignment_max_output_tokens == 0)
        {
            bail!(
                "translation alignment limits must be positive and max_corrections must not exceed batch_size when enabled"
            );
        }
        if self.translation.alignment_check
            && self.translation.alignment_context_cues > self.translation.alignment_batch_size
        {
            bail!("translation.alignment_context_cues must not exceed alignment_batch_size");
        }
        for (name, value) in [
            ("source_language", &self.translation.source_language),
            ("target_language", &self.translation.target_language),
            (
                "source_language_code",
                &self.translation.source_language_code,
            ),
            (
                "target_language_code",
                &self.translation.target_language_code,
            ),
        ] {
            if value.trim().is_empty() {
                bail!("translation.{name} must not be empty");
            }
        }
        if self.translation.consistency_check
            && self
                .translation
                .consistency_model
                .as_deref()
                .is_some_and(|model| model.trim().is_empty())
        {
            bail!("translation.consistency_model must not be empty when configured");
        }
        if self.translation.alignment_check
            && self
                .translation
                .alignment_model
                .as_deref()
                .is_some_and(|model| model.trim().is_empty())
        {
            bail!("translation.alignment_model must not be empty when configured");
        }
        if !(0.0..=1.0).contains(&self.translation.min_target_script_ratio) {
            bail!("translation.min_target_script_ratio must be between 0 and 1");
        }
        if !(0.0..=1.0).contains(
            &self
                .subtitles
                .external_srt_validation
                .min_timing_match_ratio,
        ) || !(0.0..=1.0).contains(&self.subtitles.external_srt_validation.min_text_similarity)
        {
            bail!("external SRT validation ratios must be between 0 and 1");
        }
        if !(0.0..=100.0).contains(
            &self
                .subtitles
                .external_srt_validation
                .external_quality_margin,
        ) {
            bail!("external SRT quality margin must be between 0 and 100");
        }
        if self.state.lease_seconds < 30 {
            bail!("state.lease_seconds must be at least 30");
        }
        if !(0.0..=1.0).contains(&self.migration.auto_apply_confidence) {
            bail!("migration.auto_apply_confidence must be between 0 and 1");
        }
        validate_metadata(&self.metadata)?;
        let translation_url = reqwest::Url::parse(&self.translation.base_url)
            .context("translation.base_url must be a valid absolute URL")?;
        if !matches!(translation_url.scheme(), "http" | "https") {
            bail!("translation.base_url must use http or https");
        }
        validate_storage(&self.source, "source")?;
        validate_storage(&self.destination, "destination")?;
        validate_worker(self.subtitles.asr.as_ref(), "subtitles.asr")?;
        validate_worker(self.subtitles.pgs_ocr.as_ref(), "subtitles.pgs_ocr")?;
        for (name, layout, is_tv) in [
            ("movie_4k", &self.migration.layouts.movie_4k, false),
            ("movie_other", &self.migration.layouts.movie_other, false),
            ("tv_4k", &self.migration.layouts.tv_4k, true),
            ("tv_other", &self.migration.layouts.tv_other, true),
        ] {
            validate_migration_layout(name, layout, is_tv)?;
        }
        for directory in &self.migration.generic_source_directories {
            validate_single_component(directory).with_context(|| {
                format!("migration.generic_source_directories contains {directory:?}")
            })?;
        }
        for (name, extensions) in [
            ("sidecar_extensions", &self.migration.sidecar_extensions),
            (
                "incomplete_marker_extensions",
                &self.migration.incomplete_marker_extensions,
            ),
        ] {
            for extension in extensions {
                validate_extension(extension)
                    .with_context(|| format!("unsafe migration {name} entry {extension:?}"))?;
            }
        }
        for (source_title, route) in &self.migration.title_routes {
            if source_title.trim().is_empty() {
                bail!("migration.title_routes keys must not be empty");
            }
            if route.title.is_none() && route.group.is_none() {
                bail!("migration title route {source_title:?} changes neither title nor group");
            }
            if let Some(title) = route.title.as_deref() {
                validate_single_component(title).with_context(|| {
                    format!("unsafe title in migration title route {source_title:?}")
                })?;
            }
            if let Some(group) = route.group.as_deref() {
                validate_single_component(group).with_context(|| {
                    format!("unsafe group in migration title route {source_title:?}")
                })?;
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

const MOVIE_TEMPLATE_FIELDS: &[&str] = &[
    "year",
    "decade",
    "year_bucket",
    "title",
    "title_dot",
    "source_stem",
    "source_stem_dot",
    "source_file",
    "source_file_dot",
    "release_dir",
    "extension",
];
const TV_TEMPLATE_FIELDS: &[&str] = &[
    "title",
    "title_dot",
    "season",
    "season_padded",
    "episode",
    "episode_padded",
    "alpha_group",
    "source_stem",
    "source_stem_dot",
    "source_file",
    "source_file_dot",
    "release_dir",
    "extension",
];

fn validate_migration_layout(name: &str, layout: &MigrationLayout, is_tv: bool) -> Result<()> {
    crate::storage::validate_relative_path(&layout.root)
        .with_context(|| format!("migration.layouts.{name}.root must be a safe relative path"))?;
    if layout.root.is_empty() {
        bail!("migration.layouts.{name}.root must not be empty");
    }
    if layout.directory_template.trim().is_empty() {
        bail!("migration.layouts.{name}.directory_template must not be empty");
    }
    if layout.filename_template.trim().is_empty() || layout.filename_template.contains(['/', '\\'])
    {
        bail!("migration.layouts.{name}.filename_template must be one safe file name");
    }
    let allowed = if is_tv {
        TV_TEMPLATE_FIELDS
    } else {
        MOVIE_TEMPLATE_FIELDS
    };
    validate_template(
        name,
        "directory_template",
        &layout.directory_template,
        allowed,
    )?;
    validate_template(
        name,
        "filename_template",
        &layout.filename_template,
        allowed,
    )?;
    if !layout.filename_template.contains("{extension}")
        && !layout.filename_template.contains("{source_file}")
        && !layout.filename_template.contains("{source_file_dot}")
    {
        bail!(
            "migration.layouts.{name}.filename_template must include {{extension}}, {{source_file}}, or {{source_file_dot}}"
        );
    }

    let mut covered = std::collections::BTreeSet::new();
    for group in &layout.alphabet_groups {
        validate_single_component(&group.directory).with_context(|| {
            format!("unsafe alphabet group directory in migration.layouts.{name}")
        })?;
        if group.letters.trim().is_empty()
            || !group
                .letters
                .chars()
                .all(|value| value.is_ascii_alphabetic())
        {
            bail!(
                "migration.layouts.{name}.alphabet_groups letters must contain only A-Z characters"
            );
        }
        for letter in group
            .letters
            .chars()
            .map(|value| value.to_ascii_uppercase())
        {
            if !covered.insert(letter) {
                bail!(
                    "migration.layouts.{name}.alphabet_groups contains duplicate letter {letter}"
                );
            }
        }
    }
    if layout.directory_template.contains("{alpha_group}") && covered != ('A'..='Z').collect() {
        bail!(
            "migration.layouts.{name} uses {{alpha_group}} and must map every letter A-Z exactly once"
        );
    }
    Ok(())
}

fn validate_template(name: &str, field: &str, template: &str, allowed: &[&str]) -> Result<()> {
    if template.starts_with('/') || template.contains('\\') {
        bail!("migration.layouts.{name}.{field} must be a relative POSIX template");
    }
    let mut rendered = String::new();
    let mut remainder = template;
    while let Some(start) = remainder.find('{') {
        rendered.push_str(&remainder[..start]);
        let tail = &remainder[start + 1..];
        let Some(end) = tail.find('}') else {
            bail!("migration.layouts.{name}.{field} contains an unclosed placeholder");
        };
        let placeholder = &tail[..end];
        if !allowed.contains(&placeholder) {
            bail!(
                "migration.layouts.{name}.{field} contains unsupported placeholder {{{placeholder}}}"
            );
        }
        rendered.push('X');
        remainder = &tail[end + 1..];
    }
    if remainder.contains('}') {
        bail!("migration.layouts.{name}.{field} contains an unmatched closing brace");
    }
    rendered.push_str(remainder);
    crate::storage::validate_relative_path(&rendered)
        .with_context(|| format!("migration.layouts.{name}.{field} can render an unsafe path"))?;
    Ok(())
}

fn validate_single_component(value: &str) -> Result<()> {
    let value = value.trim();
    if value.is_empty() || value.contains(['/', '\\']) {
        bail!("path component must be non-empty and contain no separators");
    }
    let normalized = crate::storage::validate_relative_path(value)?;
    if normalized != value {
        bail!("path component must not require normalization");
    }
    Ok(())
}

fn validate_extension(value: &str) -> Result<()> {
    let value = value.trim_start_matches('.');
    if value.is_empty()
        || !value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '-' | '_'))
    {
        bail!("extension must contain only ASCII letters, numbers, dash, or underscore");
    }
    Ok(())
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

impl MetadataConfig {
    pub fn api_token(&self) -> Result<String> {
        match env::var(&self.api_token_env) {
            Ok(token) if !token.trim().is_empty() => return Ok(token),
            Ok(_) => bail!(
                "TMDB API read token environment variable {} is empty. {}",
                self.api_token_env,
                tmdb_token_setup_guidance(&self.api_token_env)
            ),
            Err(env::VarError::NotUnicode(_)) => bail!(
                "TMDB API read token environment variable {} is not valid Unicode. {}",
                self.api_token_env,
                tmdb_token_setup_guidance(&self.api_token_env)
            ),
            Err(env::VarError::NotPresent) => {}
        }

        #[cfg(target_os = "macos")]
        {
            let output = std::process::Command::new("/bin/launchctl")
                .args(["getenv", &self.api_token_env])
                .output()
                .context("failed to query the current macOS launchd environment for the TMDB API read token")?;
            if output.status.success() {
                let token = String::from_utf8(output.stdout).context(
                    "TMDB API read token from the macOS launchd environment is not valid Unicode",
                )?;
                let token = token.trim_end_matches(['\r', '\n']).to_owned();
                if !token.trim().is_empty() {
                    return Ok(token);
                }
            }

            let output = std::process::Command::new("/usr/bin/security")
                .args([
                    "find-generic-password",
                    "-s",
                    "subtrans.tmdb.read-token",
                    "-w",
                ])
                .output()
                .context("failed to query macOS Keychain for the TMDB API read token")?;
            if output.status.success() {
                let token = String::from_utf8(output.stdout)
                    .context("TMDB API read token from macOS Keychain is not valid Unicode")?;
                let token = token.trim_end_matches(['\r', '\n']).to_owned();
                if !token.trim().is_empty() {
                    return Ok(token);
                }
            }
        }

        bail!(
            "missing TMDB API read token. {}",
            tmdb_token_setup_guidance(&self.api_token_env)
        )
    }
}

fn tmdb_token_setup_guidance(environment_name: &str) -> String {
    let mut guidance = format!(
        "Get an API Read Access Token at https://www.themoviedb.org/settings/api, then set it for this shell with `read -s \"{environment_name}?TMDB read token: \"; export {environment_name}; echo`"
    );
    if cfg!(target_os = "macos") {
        guidance.push_str(
            &format!(
                "; to make it available to current-user launchd jobs without exposing it in shell history, run `read -s \"{environment_name}?TMDB read token: \"; launchctl setenv {environment_name} \"${environment_name}\"; export {environment_name}; echo`; for restart-safe fallback reuse that environment value with `security add-generic-password -U -a \"$USER\" -s \"subtrans.tmdb.read-token\" -w \"${environment_name}\"`"
            ),
        );
    }
    guidance.push_str("; verify with `subtrans doctor --config subtrans.toml`");
    guidance
}

fn validate_metadata(metadata: &MetadataConfig) -> Result<()> {
    for (name, value) in [
        ("base_url", metadata.base_url.as_str()),
        ("image_base_url", metadata.image_base_url.as_str()),
    ] {
        let url = reqwest::Url::parse(value)
            .with_context(|| format!("metadata.{name} must be a valid absolute URL"))?;
        if !matches!(url.scheme(), "http" | "https") {
            bail!("metadata.{name} must use http or https");
        }
    }
    validate_environment_name(&metadata.api_token_env)
        .context("metadata.api_token_env is invalid")?;
    if metadata.language.trim().is_empty() || metadata.fallback_language.trim().is_empty() {
        bail!("metadata language values must not be empty");
    }
    if metadata.timeout_seconds == 0
        || metadata.max_response_bytes < 1024
        || metadata.max_image_bytes < 1024
    {
        bail!("metadata timeout and size limits must be positive and size limits >= 1024");
    }
    if !(0.0..=1.0).contains(&metadata.match_threshold)
        || !(0.0..=1.0).contains(&metadata.ambiguity_gap)
    {
        bail!("metadata matching thresholds must be between 0 and 1");
    }
    if metadata.refresh_after_days == 0 || metadata.refresh_after_days > 180 {
        bail!("metadata.refresh_after_days must be between 1 and 180");
    }
    for (path, decision) in &metadata.overrides {
        crate::storage::validate_relative_path(path)
            .with_context(|| format!("unsafe metadata override path {path:?}"))?;
        if decision.tmdb_id == 0 {
            bail!("metadata override tmdb_id must be positive for {path}");
        }
        match decision.kind {
            OverrideKind::Movie if decision.season.is_some() || decision.episode.is_some() => {
                bail!("movie metadata override must not include season/episode for {path}")
            }
            OverrideKind::Tv if decision.season.is_none() || decision.episode.is_none() => {
                bail!("TV metadata override requires season and episode for {path}")
            }
            _ => {}
        }
    }
    Ok(())
}

fn validate_storage(storage: &StorageConfig, name: &str) -> Result<()> {
    match storage {
        StorageConfig::Local { root } if root.as_os_str().is_empty() => {
            bail!("{name}.root must not be empty")
        }
        StorageConfig::Ftp {
            host,
            username_env,
            password_env,
            timeout_seconds,
            allow_plaintext,
            ..
        } => {
            if host.trim().is_empty()
                || username_env.trim().is_empty()
                || password_env.trim().is_empty()
            {
                bail!("{name} FTP host, username_env, and password_env are required");
            }
            validate_environment_name(username_env)
                .with_context(|| format!("{name}.username_env is invalid"))?;
            validate_environment_name(password_env)
                .with_context(|| format!("{name}.password_env is invalid"))?;
            if *timeout_seconds == 0 {
                bail!("{name} FTP timeout_seconds must be positive");
            }
            if !allow_plaintext {
                bail!(
                    "{name} uses FTP but plaintext access was not explicitly allowed; set allow_plaintext=true only for a trusted isolated network"
                );
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

fn validate_environment_name(value: &str) -> Result<()> {
    let mut characters = value.chars();
    let Some(first) = characters.next() else {
        bail!("environment variable name must not be empty");
    };
    if !(first == '_' || first.is_ascii_alphabetic())
        || !characters.all(|character| character == '_' || character.is_ascii_alphanumeric())
    {
        bail!("environment variable name must contain only ASCII letters, numbers, and underscore");
    }
    Ok(())
}

fn default_ftp_port() -> u16 {
    21
}
fn default_metadata_base_url() -> String {
    "https://api.themoviedb.org/3".to_owned()
}
fn default_metadata_image_base_url() -> String {
    "https://image.tmdb.org/t/p/original".to_owned()
}
fn default_metadata_api_token_env() -> String {
    "SUBTRANS_TMDB_READ_TOKEN".to_owned()
}
fn default_metadata_language() -> String {
    "zh-CN".to_owned()
}
fn default_metadata_fallback_language() -> String {
    "en-US".to_owned()
}
fn default_metadata_timeout() -> u64 {
    30
}
fn default_metadata_retries() -> u32 {
    2
}
fn default_metadata_max_response_bytes() -> usize {
    4 * 1024 * 1024
}
fn default_metadata_max_image_bytes() -> usize {
    32 * 1024 * 1024
}
fn default_metadata_match_threshold() -> f32 {
    0.85
}
fn default_metadata_ambiguity_gap() -> f32 {
    0.08
}
fn default_metadata_refresh_after_days() -> u16 {
    180
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

fn default_external_srt_min_timing_match_ratio() -> f32 {
    0.70
}

fn default_external_srt_min_text_similarity() -> f32 {
    0.45
}

fn default_external_srt_quality_margin() -> f32 {
    5.0
}
fn default_worker_version_args() -> Vec<String> {
    vec!["--version".to_owned()]
}
fn default_source_language() -> String {
    "English".to_owned()
}
fn default_source_language_code() -> String {
    "en".to_owned()
}
fn default_target_language() -> String {
    "Simplified Chinese".to_owned()
}
fn default_target_language_code() -> String {
    "zh-CN".to_owned()
}
fn default_true() -> bool {
    true
}
fn default_batch_size() -> usize {
    32
}
fn default_min_batch_size() -> usize {
    1
}
fn default_context_cues() -> usize {
    6
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
fn default_max_output_tokens() -> u32 {
    4_096
}
fn default_min_target_script_ratio() -> f32 {
    0.15
}
fn default_consistency_max_chars() -> usize {
    120_000
}
fn default_consistency_max_corrections() -> usize {
    64
}
fn default_consistency_max_output_tokens() -> u32 {
    4_096
}
fn default_alignment_batch_size() -> usize {
    8
}
fn default_alignment_context_cues() -> usize {
    6
}
fn default_alignment_max_corrections() -> usize {
    8
}
fn default_alignment_max_attempts() -> u32 {
    3
}
fn default_alignment_max_output_tokens() -> u32 {
    4_096
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
    ["srt", "ass", "ssa", "vtt", "nfo", "json", "jpg", "png"]
        .into_iter()
        .map(str::to_owned)
        .collect()
}

fn default_incomplete_marker_extensions() -> Vec<String> {
    ["aria2", "part", "crdownload"]
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
        assert!(cfg.metadata.enabled);
        assert!(matches!(cfg.source, StorageConfig::Ftp { .. }));
        assert!(matches!(cfg.destination, StorageConfig::Ftp { .. }));
    }

    #[test]
    fn distributed_example_contains_no_deployment_identifiers_or_inline_password() {
        let example = include_str!("../config.example.toml");
        assert!(!example.contains("password ="));
        assert!(!example.contains("username ="));

        let cfg: Config = toml::from_str(example).unwrap();
        assert!(matches!(
            &cfg.source,
            StorageConfig::Ftp { host, username_env, .. }
                if host == "nas.example.internal" && username_env == "SUBTRANS_FTP_USERNAME"
        ));

        let mut cfg = cfg;
        if let StorageConfig::Ftp { password_env, .. } = &mut cfg.source {
            password_env.clear();
        }
        assert!(cfg.validate().is_err());

        let mut cfg: Config = toml::from_str(example).unwrap();
        if let StorageConfig::Ftp { username_env, .. } = &mut cfg.source {
            *username_env = "invalid-name".into();
        }
        assert!(cfg.validate().is_err());
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
[metadata]
enabled = false
[subtitles]
[translation]
provider = "ollama"
base_url = "http://127.0.0.1:11434"
model = "m"
[migration]
[migration.layouts.movie_4k]
root = "Movies4K"
directory_template = "{year}/{release_dir}"
filename_template = "{source_file}"
[migration.layouts.movie_other]
root = "Movies"
directory_template = "{year_bucket}/{release_dir}"
filename_template = "{source_file}"
[migration.layouts.tv_4k]
root = "TV4K"
directory_template = "{title_dot}/S{season_padded}"
filename_template = "{source_file}"
[migration.layouts.tv_other]
root = "TV"
directory_template = "{title_dot}/S{season_padded}"
filename_template = "{source_file}"
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
[metadata]
enabled = false
[subtitles]
[translation]
provider = "ollama"
base_url = "http://127.0.0.1:11434"
model = "m"
bilingual = "false"
[migration]
[migration.layouts.movie_4k]
root = "Movies4K"
directory_template = "{year}/{release_dir}"
filename_template = "{source_file}"
[migration.layouts.movie_other]
root = "Movies"
directory_template = "{year_bucket}/{release_dir}"
filename_template = "{source_file}"
[migration.layouts.tv_4k]
root = "TV4K"
directory_template = "{title_dot}/S{season_padded}"
filename_template = "{source_file}"
[migration.layouts.tv_other]
root = "TV"
directory_template = "{title_dot}/S{season_padded}"
filename_template = "{source_file}"
"#;
        assert!(toml::from_str::<Config>(raw).is_err());
    }

    #[test]
    fn missing_tmdb_token_guidance_is_actionable_and_secret_free() {
        let guidance = tmdb_token_setup_guidance("SUBTRANS_TMDB_READ_TOKEN");
        assert!(guidance.contains("https://www.themoviedb.org/settings/api"));
        assert!(guidance.contains("SUBTRANS_TMDB_READ_TOKEN"));
        assert!(guidance.contains("subtrans doctor"));
        if cfg!(target_os = "macos") {
            assert!(guidance.contains("subtrans.tmdb.read-token"));
        }
    }
}
