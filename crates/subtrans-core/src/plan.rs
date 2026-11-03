use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::classify::{Classification, RULE_VERSION};

pub trait PlanBinding {
    fn plan_config_sha256(&self) -> Result<String>;
    fn plan_source_binding(&self) -> Result<StorageBinding>;
    fn plan_destination_binding(&self) -> Result<StorageBinding>;
}

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
    pub fn new(config: &impl PlanBinding, mut items: Vec<PlanItem>) -> Result<Self> {
        items.sort_by(|left, right| left.source.cmp(&right.source));
        for item in &mut items {
            item.sidecar_actions
                .sort_by(|left, right| left.source.cmp(&right.source));
        }
        mark_destination_collisions(&mut items);
        let mut document = Self {
            schema_version: PLAN_SCHEMA_VERSION,
            rule_version: RULE_VERSION.to_owned(),
            config_sha256: config.plan_config_sha256()?,
            source_binding: config.plan_source_binding()?,
            destination_binding: config.plan_destination_binding()?,
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

    pub fn verify_config(&self, config: &impl PlanBinding) -> Result<()> {
        if self.config_sha256 != config.plan_config_sha256()?
            || self.source_binding != config.plan_source_binding()?
            || self.destination_binding != config.plan_destination_binding()?
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

fn temporary_plan_path(path: &Path) -> PathBuf {
    use std::sync::atomic::{AtomicU64, Ordering};
    static NONCE: AtomicU64 = AtomicU64::new(0);
    let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or(0);
    let mut file_name = path
        .file_name()
        .map(|value| value.to_os_string())
        .unwrap_or_else(|| "migration-plan.json".into());
    file_name.push(format!(".tmp-{nanos}-{nonce}"));
    path.with_file_name(file_name)
}
