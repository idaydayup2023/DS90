use std::path::Path;
use std::time::UNIX_EPOCH;

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::storage::{FileEntry, Storage};

pub const ARTIFACT_SCHEMA: u32 = 2;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SubtitleArtifact {
    pub schema: u32,
    pub status: String,
    pub video_path: String,
    pub video_identity_sha256: String,
    pub source_sha256: String,
    pub output_sha256: String,
    pub cache_key: String,
    pub acquisition_key: String,
    pub source_kind: String,
    pub source_path: Option<String>,
    pub created_unix_seconds: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactPaths {
    pub output: String,
    pub manifest: String,
}

pub fn artifact_paths(video_path: &str) -> Result<ArtifactPaths> {
    let path = Path::new(video_path);
    let stem = path
        .file_stem()
        .and_then(|value| value.to_str())
        .context("video file name is not valid UTF-8")?;
    let parent = path.parent().and_then(Path::to_str).unwrap_or("");
    let output_name = format!("{stem}.ai.srt");
    let output = if parent.is_empty() {
        output_name
    } else {
        format!("{parent}/{output_name}")
    };
    Ok(ArtifactPaths {
        manifest: format!("{output}.subtrans.json"),
        output,
    })
}

pub fn video_identity(entry: &FileEntry) -> String {
    let modified = entry
        .modified
        .and_then(|value| value.duration_since(UNIX_EPOCH).ok())
        .map(|value| value.as_secs());
    identity(&entry.path, entry.size, modified)
}

pub fn identity(path: &str, size: u64, modified: Option<u64>) -> String {
    let mut digest = Sha256::new();
    digest.update(b"subtrans-source-fingerprint-v1\0");
    digest.update(path.as_bytes());
    digest.update(b"\0");
    digest.update(size.to_le_bytes());
    digest.update(modified.unwrap_or(u64::MAX).to_le_bytes());
    hex::encode(digest.finalize())
}

pub fn read_ready_artifact(
    storage: &dyn Storage,
    video: &FileEntry,
) -> Result<Option<SubtitleArtifact>> {
    let paths = artifact_paths(&video.path)?;
    if !storage.exists(&paths.output)? || !storage.exists(&paths.manifest)? {
        return Ok(None);
    }
    let raw = storage
        .read(&paths.manifest)
        .with_context(|| format!("failed to read subtitle manifest {}", paths.manifest))?;
    let manifest: SubtitleArtifact = match serde_json::from_slice(&raw) {
        Ok(value) => value,
        Err(_) => return Ok(None),
    };
    if manifest.schema != ARTIFACT_SCHEMA
        || manifest.status != "ready"
        || manifest.video_path != video.path
        || manifest.video_identity_sha256 != video_identity(video)
    {
        return Ok(None);
    }
    if storage.sha256(&paths.output)? != manifest.output_sha256 {
        return Ok(None);
    }
    if let Some(source_path) = manifest.source_path.as_deref()
        && (!storage.exists(source_path)? || storage.sha256(source_path)? != manifest.source_sha256)
    {
        return Ok(None);
    }
    Ok(Some(manifest))
}

pub fn require_ready_artifact(
    storage: &dyn Storage,
    video: &FileEntry,
) -> Result<SubtitleArtifact> {
    read_ready_artifact(storage, video)?.with_context(|| {
        format!(
            "video {} has no valid ready subtitle artifact or its hashes no longer match",
            video.path
        )
    })
}

pub fn validate_manifest_for_publish(manifest: &SubtitleArtifact) -> Result<()> {
    if manifest.schema != ARTIFACT_SCHEMA || manifest.status != "ready" {
        bail!("subtitle manifest must be schema {ARTIFACT_SCHEMA} and status ready");
    }
    if manifest.video_path.is_empty()
        || manifest.video_identity_sha256.is_empty()
        || manifest.source_sha256.is_empty()
        || manifest.output_sha256.is_empty()
        || manifest.cache_key.is_empty()
        || manifest.acquisition_key.is_empty()
    {
        bail!("subtitle manifest is missing required identity fields");
    }
    Ok(())
}
