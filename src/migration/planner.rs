use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::artifact::{read_ready_artifact, video_identity};
use crate::config::{Config, MigrationOverride, OverrideKind, StorageConfig};
use crate::storage::{FileEntry, Storage, open_storage, validate_relative_path};

use super::classifier::{Classification, Evidence, MediaKind, RULE_VERSION, classify_path};

const PLAN_SCHEMA_VERSION: u32 = 2;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceFingerprint {
    pub size_bytes: u64,
    pub modified_unix_seconds: Option<u64>,
    pub identity_sha256: String,
    pub content_sha256: String,
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
        let source_fingerprint = fingerprint(storage.as_ref(), video)?;
        let destination = destination_for(config, &video.path, &classification)?;
        let subtitle_ready = read_ready_artifact(storage.as_ref(), video)?;
        let allow_untranslated = decision.is_some_and(|decision| decision.allow_untranslated);

        let status = if config.migration.require_translated_subtitle
            && subtitle_ready.is_none()
            && !allow_untranslated
        {
            PlanStatus::Pending {
                reason: "valid translated subtitle artifact is required before migration".into(),
            }
        } else if classification.is_pending() {
            PlanStatus::Pending {
                reason: classification
                    .pending_reason
                    .clone()
                    .unwrap_or_else(|| "classification requires confirmation".into()),
            }
        } else if classification.confidence < config.migration.auto_apply_confidence {
            PlanStatus::Pending {
                reason: format!(
                    "classification confidence {:.2} is below configured threshold {:.2}",
                    classification.confidence, config.migration.auto_apply_confidence
                ),
            }
        } else if destination.is_none() {
            PlanStatus::Pending {
                reason: "classification lacks destination naming fields".into(),
            }
        } else {
            PlanStatus::Ready
        };

        let destination = matches!(status, PlanStatus::Ready)
            .then_some(destination)
            .flatten();
        let sidecar_actions = if let Some(target) = destination.as_deref() {
            sidecars_for(
                storage.as_ref(),
                &entries,
                &video.path,
                target,
                &sidecar_extensions,
            )?
        } else {
            Vec::new()
        };
        items.push(PlanItem {
            source: video.path.clone(),
            source_fingerprint,
            classification,
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

fn destination_for(
    config: &Config,
    source: &str,
    classification: &Classification,
) -> Result<Option<String>> {
    let extension = Path::new(source)
        .extension()
        .and_then(|value| value.to_str())
        .context("video extension is not valid UTF-8")?;
    let Some(title) = classification.title.as_deref().map(safe_component) else {
        return Ok(None);
    };
    let (root, directory_parts, normalized_stem) = match classification.kind {
        MediaKind::Movie => {
            let Some(year) = classification.year else {
                return Ok(None);
            };
            let root = if classification.is_4k {
                &config.migration.movie_4k_root
            } else {
                &config.migration.movie_1080_root
            };
            let year_bucket = if year >= config.migration.year_split {
                year.to_string()
            } else {
                format!("{}0s", year / 10)
            };
            let folder = format!("{title} ({year})");
            let stem = if config.migration.normalize_names {
                format!("{}.{}", dotify(&title), year)
            } else {
                Path::new(source)
                    .file_stem()
                    .and_then(|value| value.to_str())
                    .unwrap_or(&title)
                    .to_owned()
            };
            (root.as_str(), vec![year_bucket, folder], stem)
        }
        MediaKind::Tv => {
            let (Some(season), Some(episode)) = (classification.season, classification.episode)
            else {
                return Ok(None);
            };
            let root = if classification.is_4k {
                &config.migration.tv_4k_root
            } else {
                &config.migration.tv_1080_root
            };
            let stem = if config.migration.normalize_names {
                format!("{}.S{season:02}E{episode:02}", dotify(&title))
            } else {
                Path::new(source)
                    .file_stem()
                    .and_then(|value| value.to_str())
                    .unwrap_or(&title)
                    .to_owned()
            };
            (root.as_str(), vec![title, format!("S{season:02}")], stem)
        }
        MediaKind::Unknown => return Ok(None),
    };
    let mut parts = vec![root.to_owned()];
    parts.extend(directory_parts);
    parts.push(format!("{normalized_stem}.{extension}"));
    let destination = join_storage_path(&parts.iter().map(String::as_str).collect::<Vec<_>>());
    validate_relative_path(&destination)?;
    Ok(Some(destination))
}

fn sidecars_for(
    storage: &dyn Storage,
    entries: &[FileEntry],
    source: &str,
    target: &str,
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
        let suffix = if stem == video_stem {
            String::new()
        } else if let Some(suffix) = stem.strip_prefix(&format!("{video_stem}.")) {
            format!(".{suffix}")
        } else {
            continue;
        };
        let destination_name = format!("{target_stem}{suffix}.{extension}");
        let destination =
            join_storage_path(&[target_parent.to_str().unwrap_or(""), &destination_name]);
        actions.push(FileAction {
            source: entry.path.clone(),
            destination,
            source_fingerprint: fingerprint(storage, entry)?,
        });
    }
    Ok(actions)
}

fn fingerprint(storage: &dyn Storage, entry: &FileEntry) -> Result<SourceFingerprint> {
    let modified_unix_seconds = entry
        .modified
        .and_then(|value| value.duration_since(UNIX_EPOCH).ok())
        .map(|duration| duration.as_secs());
    Ok(SourceFingerprint {
        size_bytes: entry.size,
        modified_unix_seconds,
        identity_sha256: video_identity(entry),
        content_sha256: storage
            .sha256(&entry.path)
            .with_context(|| format!("failed to hash planned source {}", entry.path))?,
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
        video_extensions: &'a [String],
        min_video_bytes: u64,
    }
    let value = Relevant {
        source: storage_binding(&config.source)?,
        destination: storage_binding(&config.destination)?,
        migration: &config.migration,
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
            username,
            root,
            ..
        } => StorageBinding {
            kind: "ftp".into(),
            endpoint: format!("{}@{}:{}", username, host.to_ascii_lowercase(), port),
            root: format!("/{}", root.trim_matches('/')),
        },
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
