use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::artifact::{read_ready_artifact, video_identity};
use crate::config::{
    Config, MigrationLayout, MigrationOverride, MigrationTitleRoute, OverrideKind, StorageConfig,
};
use crate::metadata::read_ready_metadata;
use crate::storage::{FileEntry, Storage, open_storage, validate_relative_path};

use super::classifier::{Classification, Evidence, MediaKind, RULE_VERSION, classify_path};

const PLAN_SCHEMA_VERSION: u32 = 6;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceFingerprint {
    pub size_bytes: u64,
    pub modified_unix_seconds: Option<u64>,
    pub identity_sha256: String,
    /// Full content hash is present only on executable actions. Pending review
    /// items deliberately avoid reading multi-gigabyte media that cannot be
    /// applied; any resolution requires generating a fresh, fully hashed plan.
    pub content_sha256: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FileAction {
    pub source: String,
    pub destination: String,
    pub source_fingerprint: SourceFingerprint,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum PlanStatus {
    Ready,
    Pending { reason: String },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PlanItem {
    pub source: String,
    pub source_fingerprint: SourceFingerprint,
    pub classification: Classification,
    /// Auditable routing preview. This may be present on a pending item but is
    /// never returned by `actions()` and therefore can never be applied.
    pub proposed_destination: Option<String>,
    pub destination: Option<String>,
    pub sidecar_actions: Vec<FileAction>,
    pub status: PlanStatus,
}

impl PlanItem {
    pub fn is_pending(&self) -> bool {
        matches!(self.status, PlanStatus::Pending { .. })
    }

    pub fn actions(&self) -> Vec<FileAction> {
        let mut actions = self.sidecar_actions.clone();
        if let Some(destination) = &self.destination {
            actions.push(FileAction {
                source: self.source.clone(),
                destination: destination.clone(),
                source_fingerprint: self.source_fingerprint.clone(),
            });
        }
        actions
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StorageBinding {
    pub kind: String,
    pub endpoint: String,
    pub root: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PlanDocument {
    pub schema_version: u32,
    pub rule_version: String,
    pub config_sha256: String,
    pub source_binding: StorageBinding,
    pub destination_binding: StorageBinding,
    pub items: Vec<PlanItem>,
    pub plan_hash: String,
}

impl PlanDocument {
    pub fn new(config: &Config, mut items: Vec<PlanItem>) -> Result<Self> {
        items.sort_by(|left, right| left.source.cmp(&right.source));
        for item in &mut items {
            item.sidecar_actions
                .sort_by(|left, right| left.source.cmp(&right.source));
        }
        mark_destination_collisions(&mut items);
        let mut document = Self {
            schema_version: PLAN_SCHEMA_VERSION,
            rule_version: RULE_VERSION.to_owned(),
            config_sha256: relevant_config_hash(config)?,
            source_binding: storage_binding(&config.source)?,
            destination_binding: storage_binding(&config.destination)?,
            items,
            plan_hash: String::new(),
        };
        document.plan_hash = document.calculate_hash()?;
        Ok(document)
    }

    pub fn pending_count(&self) -> usize {
        self.items.iter().filter(|item| item.is_pending()).count()
    }

    pub fn calculate_hash(&self) -> Result<String> {
        #[derive(Serialize)]
        struct HashPayload<'a> {
            schema_version: u32,
            rule_version: &'a str,
            config_sha256: &'a str,
            source_binding: &'a StorageBinding,
            destination_binding: &'a StorageBinding,
            items: &'a [PlanItem],
        }
        let payload = HashPayload {
            schema_version: self.schema_version,
            rule_version: &self.rule_version,
            config_sha256: &self.config_sha256,
            source_binding: &self.source_binding,
            destination_binding: &self.destination_binding,
            items: &self.items,
        };
        Ok(hex::encode(Sha256::digest(serde_json::to_vec(&payload)?)))
    }

    pub fn verify_hash(&self) -> Result<()> {
        let calculated = self.calculate_hash()?;
        if calculated != self.plan_hash {
            bail!(
                "migration plan hash mismatch: expected {}, calculated {}",
                self.plan_hash,
                calculated
            );
        }
        Ok(())
    }

    pub fn verify_config(&self, config: &Config) -> Result<()> {
        if self.config_sha256 != relevant_config_hash(config)?
            || self.source_binding != storage_binding(&config.source)?
            || self.destination_binding != storage_binding(&config.destination)?
        {
            bail!("migration plan was approved for a different configuration or storage endpoint");
        }
        Ok(())
    }

    pub fn write(&self, path: impl AsRef<Path>) -> Result<()> {
        self.verify_hash()?;
        let path = path.as_ref();
        if let Some(parent) = path
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
        {
            std::fs::create_dir_all(parent)?;
        }
        let bytes = serde_json::to_vec_pretty(self)?;
        let temporary = temporary_plan_path(path);
        std::fs::write(&temporary, bytes)?;
        std::fs::rename(&temporary, path)
            .with_context(|| format!("failed to publish migration plan {}", path.display()))?;
        Ok(())
    }

    pub fn read(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        let document: Self = serde_json::from_slice(
            &std::fs::read(path)
                .with_context(|| format!("failed to read migration plan {}", path.display()))?,
        )?;
        if document.schema_version != PLAN_SCHEMA_VERSION || document.rule_version != RULE_VERSION {
            bail!("migration plan schema or rule version is not supported by this executable");
        }
        document.verify_hash()?;
        Ok(document)
    }
}

pub fn build_plan(config: &Config, limit: Option<usize>) -> Result<PlanDocument> {
    crate::metadata::ensure_before(config, false, limit)
        .context("metadata prerequisite failed before migration planning")?;
    let storage = open_storage(&config.source).context("failed to open source storage")?;
    let mut entries = storage.list_recursive("")?;
    entries.sort_by(|left, right| left.path.cmp(&right.path));
    let video_extensions: HashSet<String> = config
        .subtitles
        .video_extensions
        .iter()
        .map(|value| value.trim_start_matches('.').to_ascii_lowercase())
        .collect();
    let sidecar_extensions: HashSet<String> = config
        .migration
        .sidecar_extensions
        .iter()
        .map(|value| value.trim_start_matches('.').to_ascii_lowercase())
        .collect();
    let incomplete_marker_extensions: Vec<String> = config
        .migration
        .incomplete_marker_extensions
        .iter()
        .map(|value| value.trim_start_matches('.').to_ascii_lowercase())
        .collect();
    let videos: Vec<&FileEntry> = entries
        .iter()
        .filter(|entry| {
            !entry.is_dir
                && entry.size >= config.subtitles.min_video_bytes
                && extension(&entry.path).is_some_and(|value| video_extensions.contains(&value))
        })
        .take(limit.unwrap_or(usize::MAX))
        .collect();

    let mut items = Vec::with_capacity(videos.len());
    for video in videos {
        let decision = config.migration.overrides.get(&video.path);
        let classification = decision
            .map(|decision| classification_from_override(video, decision))
            .unwrap_or_else(|| classify_path(&video.path));
        let destination_resolution = destination_for(config, &video.path, &classification)?;
        let subtitle_ready = read_ready_artifact(storage.as_ref(), video)?;
        let metadata_ready = read_ready_metadata(storage.as_ref(), video, config)?;
        let allow_untranslated = decision.is_some_and(|decision| decision.allow_untranslated);
        let incomplete_marker = entries.iter().find(|entry| {
            !entry.is_dir
                && incomplete_marker_extensions.iter().any(|extension| {
                    entry
                        .path
                        .eq_ignore_ascii_case(&format!("{}.{}", video.path, extension))
                })
        });

        let mut blockers = Vec::new();
        if let Some(marker) = incomplete_marker {
            blockers.push(format!(
                "incomplete download marker is present: {}",
                marker.path
            ));
        }
        if classification.is_pending() {
            blockers.push(
                classification
                    .pending_reason
                    .clone()
                    .unwrap_or_else(|| "classification requires confirmation".into()),
            );
        } else if classification.confidence < config.migration.auto_apply_confidence {
            blockers.push(format!(
                "classification confidence {:.2} is below configured threshold {:.2}",
                classification.confidence, config.migration.auto_apply_confidence
            ));
        } else if destination_resolution.destination.is_none() {
            blockers.push(
                destination_resolution
                    .pending_reason
                    .clone()
                    .unwrap_or_else(|| "classification lacks destination naming fields".into()),
            );
        }
        if config.migration.require_translated_subtitle
            && subtitle_ready.is_none()
            && !allow_untranslated
        {
            blockers.push("valid translated subtitle artifact is required before migration".into());
        }
        if config.metadata.enabled && metadata_ready.is_none() {
            blockers.push(
                "valid TMDB metadata manifest, NFO, and poster are required before migration"
                    .into(),
            );
        }
        let status = if blockers.is_empty() {
            PlanStatus::Ready
        } else {
            PlanStatus::Pending {
                reason: blockers.join("; "),
            }
        };

        let proposed_destination = destination_resolution.destination;
        let destination = matches!(status, PlanStatus::Ready)
            .then_some(proposed_destination.clone())
            .flatten();
        let source_fingerprint =
            fingerprint(storage.as_ref(), video, matches!(status, PlanStatus::Ready))?;
        let sidecar_actions = if let Some(target) = destination.as_deref() {
            sidecars_for(
                storage.as_ref(),
                &entries,
                &video.path,
                target,
                &classification,
                &sidecar_extensions,
            )?
        } else {
            Vec::new()
        };
        items.push(PlanItem {
            source: video.path.clone(),
            source_fingerprint,
            classification,
            proposed_destination,
            destination,
            sidecar_actions,
            status,
        });
    }
    PlanDocument::new(config, items)
}

fn classification_from_override(video: &FileEntry, decision: &MigrationOverride) -> Classification {
    let kind = match decision.kind {
        OverrideKind::Movie => MediaKind::Movie,
        OverrideKind::Tv => MediaKind::Tv,
    };
    Classification {
        kind,
        title: Some(decision.title.trim().to_owned()),
        year: decision.year,
        season: decision.season,
        episode: decision.episode,
        is_4k: decision
            .is_4k
            .unwrap_or_else(|| classify_path(&video.path).is_4k),
        confidence: 1.0,
        evidence: vec![Evidence {
            code: "user_override".into(),
            detail: format!(
                "explicit versioned configuration override for {}",
                video.path
            ),
            confidence: 1.0,
        }],
        pending_reason: None,
    }
}

struct DestinationResolution {
    destination: Option<String>,
    pending_reason: Option<String>,
}

impl DestinationResolution {
    fn pending(reason: impl Into<String>) -> Self {
        Self {
            destination: None,
            pending_reason: Some(reason.into()),
        }
    }

    fn ready(destination: String) -> Self {
        Self {
            destination: Some(destination),
            pending_reason: None,
        }
    }
}

fn destination_for(
    config: &Config,
    source: &str,
    classification: &Classification,
) -> Result<DestinationResolution> {
    let source_path = Path::new(source);
    let extension = source_path
        .extension()
        .and_then(|value| value.to_str())
        .context("video extension is not valid UTF-8")?;
    let source_file = source_path
        .file_name()
        .and_then(|value| value.to_str())
        .context("video file name is not valid UTF-8")?;
    let source_stem = source_path
        .file_stem()
        .and_then(|value| value.to_str())
        .context("video stem is not valid UTF-8")?;
    let Some(classified_title) = classification.title.as_deref() else {
        return Ok(DestinationResolution::pending(
            "classification has no title for destination rendering",
        ));
    };
    let route = title_route(config, classified_title);
    let title = route
        .and_then(|value| value.title.as_deref())
        .unwrap_or(classified_title);
    let title = safe_component(title);
    if title.is_empty() {
        return Ok(DestinationResolution::pending(
            "configured destination title is empty after path sanitization",
        ));
    }
    let layout = match classification.kind {
        MediaKind::Movie if classification.is_4k => &config.migration.layouts.movie_4k,
        MediaKind::Movie => &config.migration.layouts.movie_other,
        MediaKind::Tv if classification.is_4k => &config.migration.layouts.tv_4k,
        MediaKind::Tv => &config.migration.layouts.tv_other,
        MediaKind::Unknown => {
            return Ok(DestinationResolution::pending(
                "unknown media type has no destination layout",
            ));
        }
    };
    let mut values = HashMap::from([
        ("title", title.clone()),
        ("title_dot", dotify(&title)),
        ("source_file", safe_component(source_file)),
        ("source_file_dot", dotify(source_file)),
        ("source_stem", safe_component(source_stem)),
        ("source_stem_dot", dotify(source_stem)),
        ("extension", extension.to_owned()),
        (
            "release_dir",
            release_directory(config, source_path, source_stem),
        ),
    ]);

    match classification.kind {
        MediaKind::Movie => {
            let Some(year) = classification.year else {
                return Ok(DestinationResolution::pending(
                    "movie classification has no release year",
                ));
            };
            let decade = format!("{}0s", year / 10);
            let year_bucket = if layout
                .recent_year_from
                .is_none_or(|recent_year_from| year >= recent_year_from)
            {
                year.to_string()
            } else {
                decade.clone()
            };
            values.insert("year", year.to_string());
            values.insert("decade", decade);
            values.insert("year_bucket", year_bucket);
        }
        MediaKind::Tv => {
            let (Some(season), Some(episode)) = (classification.season, classification.episode)
            else {
                return Ok(DestinationResolution::pending(
                    "TV classification requires both season and episode",
                ));
            };
            values.insert("season", season.to_string());
            values.insert("season_padded", format!("{season:02}"));
            values.insert("episode", episode.to_string());
            values.insert("episode_padded", format!("{episode:02}"));
            if layout.directory_template.contains("{alpha_group}") {
                let group = route
                    .and_then(|value| value.group.as_deref())
                    .map(safe_component)
                    .or_else(|| alphabet_group(layout, &title));
                let Some(group) = group else {
                    return Ok(DestinationResolution::pending(format!(
                        "TV title {title:?} has no configured alphabet group or title route"
                    )));
                };
                values.insert("alpha_group", group);
            }
        }
        MediaKind::Unknown => unreachable!("unknown media was handled before rendering"),
    }

    let directory = render_template(&layout.directory_template, &values)?;
    let filename = render_template(&layout.filename_template, &values)?;
    let destination = join_storage_path(&[&layout.root, &directory, &filename]);
    validate_relative_path(&destination)?;
    Ok(DestinationResolution::ready(destination))
}

fn title_route<'a>(config: &'a Config, title: &str) -> Option<&'a MigrationTitleRoute> {
    config
        .migration
        .title_routes
        .iter()
        .find(|(candidate, _)| candidate.eq_ignore_ascii_case(title))
        .map(|(_, route)| route)
}

fn release_directory(config: &Config, source: &Path, source_stem: &str) -> String {
    let parent = source
        .parent()
        .and_then(Path::file_name)
        .and_then(|value| value.to_str());
    let parent_is_generic = parent.is_none_or(|parent| {
        config
            .migration
            .generic_source_directories
            .iter()
            .any(|candidate| candidate.eq_ignore_ascii_case(parent))
    });
    safe_component(if parent_is_generic {
        source_stem
    } else {
        parent.unwrap_or(source_stem)
    })
}

fn alphabet_group(layout: &MigrationLayout, title: &str) -> Option<String> {
    let initial = title
        .chars()
        .find(|value| value.is_ascii_alphabetic())?
        .to_ascii_uppercase();
    layout
        .alphabet_groups
        .iter()
        .find(|group| {
            group
                .letters
                .chars()
                .any(|letter| letter.to_ascii_uppercase() == initial)
        })
        .map(|group| safe_component(&group.directory))
}

fn render_template(template: &str, values: &HashMap<&str, String>) -> Result<String> {
    let mut rendered = String::new();
    let mut remainder = template;
    while let Some(start) = remainder.find('{') {
        rendered.push_str(&remainder[..start]);
        let tail = &remainder[start + 1..];
        let end = tail
            .find('}')
            .context("validated migration template has an unclosed placeholder")?;
        let placeholder = &tail[..end];
        let value = values.get(placeholder).with_context(|| {
            format!("migration template field {{{placeholder}}} is unavailable")
        })?;
        rendered.push_str(value);
        remainder = &tail[end + 1..];
    }
    rendered.push_str(remainder);
    Ok(rendered)
}

fn sidecars_for(
    storage: &dyn Storage,
    entries: &[FileEntry],
    source: &str,
    target: &str,
    classification: &Classification,
    extensions: &HashSet<String>,
) -> Result<Vec<FileAction>> {
    let source_path = Path::new(source);
    let source_parent = source_path.parent().unwrap_or_else(|| Path::new(""));
    let video_stem = source_path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("");
    let target_path = Path::new(target);
    let target_parent = target_path.parent().unwrap_or_else(|| Path::new(""));
    let target_stem = target_path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or(video_stem);
    let mut actions = Vec::new();
    for entry in entries.iter().filter(|entry| !entry.is_dir) {
        let path = Path::new(&entry.path);
        if path.parent().unwrap_or_else(|| Path::new("")) != source_parent {
            continue;
        }
        let Some(extension) = extension(&entry.path) else {
            continue;
        };
        if !extensions.contains(&extension) {
            continue;
        }
        let Some(stem) = path.file_stem().and_then(|value| value.to_str()) else {
            continue;
        };
        let destination_name = if stem == video_stem {
            format!("{target_stem}.{extension}")
        } else if let Some(suffix) = stem.strip_prefix(&format!("{video_stem}.")) {
            format!("{target_stem}.{suffix}.{extension}")
        } else if let Some(suffix) = stem.strip_prefix(&format!("{video_stem}-")) {
            format!("{target_stem}-{suffix}.{extension}")
        } else if is_same_episode_sidecar(classification, &entry.path) {
            path.file_name()
                .and_then(|value| value.to_str())
                .context("sidecar file name is not valid UTF-8")?
                .to_owned()
        } else {
            continue;
        };
        let destination_name = dotify(&destination_name);
        let destination =
            join_storage_path(&[target_parent.to_str().unwrap_or(""), &destination_name]);
        actions.push(FileAction {
            source: entry.path.clone(),
            destination,
            source_fingerprint: fingerprint(storage, entry, true)?,
        });
    }
    Ok(actions)
}

fn is_same_episode_sidecar(video: &Classification, sidecar_path: &str) -> bool {
    if video.kind != MediaKind::Tv {
        return false;
    }
    let sidecar = classify_path(sidecar_path);
    sidecar.kind == MediaKind::Tv
        && sidecar.season == video.season
        && sidecar.episode == video.episode
}

fn fingerprint(
    storage: &dyn Storage,
    entry: &FileEntry,
    include_content: bool,
) -> Result<SourceFingerprint> {
    let modified_unix_seconds = entry
        .modified
        .and_then(|value| value.duration_since(UNIX_EPOCH).ok())
        .map(|duration| duration.as_secs());
    Ok(SourceFingerprint {
        size_bytes: entry.size,
        modified_unix_seconds,
        identity_sha256: video_identity(entry),
        content_sha256: include_content
            .then(|| {
                storage
                    .sha256(&entry.path)
                    .with_context(|| format!("failed to hash planned source {}", entry.path))
            })
            .transpose()?,
    })
}

fn mark_destination_collisions(items: &mut [PlanItem]) {
    let mut owners: HashMap<String, Vec<usize>> = HashMap::new();
    for (index, item) in items.iter().enumerate() {
        for action in item.actions() {
            owners
                .entry(action.destination.to_lowercase())
                .or_default()
                .push(index);
        }
    }
    let colliding: HashSet<usize> = owners
        .values()
        .filter(|indices| indices.len() > 1)
        .flatten()
        .copied()
        .collect();
    for index in colliding {
        items[index].status = PlanStatus::Pending {
            reason: "one or more destination paths collide case-insensitively".into(),
        };
        items[index].destination = None;
        items[index].sidecar_actions.clear();
    }
}

pub fn relevant_config_hash(config: &Config) -> Result<String> {
    #[derive(Serialize)]
    struct Relevant<'a> {
        source: StorageBinding,
        destination: StorageBinding,
        migration: &'a crate::config::MigrationConfig,
        metadata: &'a crate::config::MetadataConfig,
        video_extensions: &'a [String],
        min_video_bytes: u64,
    }
    let value = Relevant {
        source: storage_binding(&config.source)?,
        destination: storage_binding(&config.destination)?,
        migration: &config.migration,
        metadata: &config.metadata,
        video_extensions: &config.subtitles.video_extensions,
        min_video_bytes: config.subtitles.min_video_bytes,
    };
    Ok(hex::encode(Sha256::digest(serde_json::to_vec(&value)?)))
}

pub fn storage_binding(config: &StorageConfig) -> Result<StorageBinding> {
    Ok(match config {
        StorageConfig::Local { root } => StorageBinding {
            kind: "local".into(),
            endpoint: "localhost".into(),
            root: root
                .canonicalize()
                .unwrap_or_else(|_| root.to_path_buf())
                .to_string_lossy()
                .into_owned(),
        },
        StorageConfig::Ftp {
            host,
            port,
            username_env,
            root,
            ..
        } => {
            let username = crate::storage::resolve_ftp_username(username_env)?;
            let account_hash = hex::encode(Sha256::digest(username.as_bytes()));
            StorageBinding {
                kind: "ftp".into(),
                endpoint: format!(
                    "{}:{}#account_sha256={account_hash}",
                    host.to_ascii_lowercase(),
                    port
                ),
                root: format!("/{}", root.trim_matches('/')),
            }
        }
    })
}

fn extension(path: &str) -> Option<String> {
    Path::new(path)
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_ascii_lowercase)
}

fn safe_component(value: &str) -> String {
    value
        .replace(['/', '\\', ':', '*', '?', '"', '<', '>', '|'], " ")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn dotify(value: &str) -> String {
    safe_component(value)
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(".")
}

fn join_storage_path(parts: &[&str]) -> String {
    parts
        .iter()
        .flat_map(|part| part.split('/'))
        .filter(|part| !part.is_empty() && *part != ".")
        .collect::<Vec<_>>()
        .join("/")
}

fn temporary_plan_path(path: &Path) -> PathBuf {
    let mut file_name = path
        .file_name()
        .map(|value| value.to_os_string())
        .unwrap_or_else(|| "migration-plan.json".into());
    file_name.push(format!(".tmp-{}", std::process::id()));
    path.with_file_name(file_name)
}
