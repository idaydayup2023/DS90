use std::path::Path;
use std::time::UNIX_EPOCH;

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::storage::{FileEntry, Storage};

pub const ARTIFACT_SCHEMA: u32 = 3;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SubtitleSourceEvidence {
    pub decision: String,
    pub external_path: String,
    pub embedded_kind: String,
    pub timing_match_ratio: f32,
    pub text_similarity: f32,
    pub external_quality: f32,
    pub embedded_quality: f32,
}

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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_evidence: Option<SubtitleSourceEvidence>,
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
    let output_exists = storage.exists(&paths.output)?;
    let manifest_exists = storage.exists(&paths.manifest)?;
    if !output_exists || !manifest_exists {
        eprintln!(
            "subtitle artifact not_ready video={} reason={} output_exists={} manifest_exists={}",
            video.path,
            if output_exists || manifest_exists {
                "partial_publish"
            } else {
                "missing"
            },
            output_exists,
            manifest_exists
        );
        return Ok(None);
    }
    let raw = storage
        .read(&paths.manifest)
        .with_context(|| format!("failed to read subtitle manifest {}", paths.manifest))?;
    let manifest: SubtitleArtifact = match serde_json::from_slice(&raw) {
        Ok(value) => value,
        Err(error) => {
            eprintln!(
                "subtitle artifact not_ready video={} reason=invalid_manifest_json error={error}",
                video.path
            );
            return Ok(None);
        }
    };
    if manifest.schema != ARTIFACT_SCHEMA {
        eprintln!(
            "subtitle artifact not_ready video={} reason=schema expected={} actual={}",
            video.path, ARTIFACT_SCHEMA, manifest.schema
        );
        return Ok(None);
    }
    if manifest.status != "ready" {
        eprintln!(
            "subtitle artifact not_ready video={} reason=status actual={}",
            video.path, manifest.status
        );
        return Ok(None);
    }
    if manifest.video_path != video.path {
        eprintln!(
            "subtitle artifact not_ready video={} reason=video_path manifest_video={}",
            video.path, manifest.video_path
        );
        return Ok(None);
    }
    let expected_video_identity = video_identity(video);
    if manifest.video_identity_sha256 != expected_video_identity {
        eprintln!(
            "subtitle artifact not_ready video={} reason=video_identity expected={} actual={}",
            video.path, expected_video_identity, manifest.video_identity_sha256
        );
        return Ok(None);
    }
    let output_sha256 = storage.sha256(&paths.output)?;
    if output_sha256 != manifest.output_sha256 {
        eprintln!(
            "subtitle artifact not_ready video={} reason=output_sha256 expected={} actual={}",
            video.path, manifest.output_sha256, output_sha256
        );
        return Ok(None);
    }
    if let Some(source_path) = manifest.source_path.as_deref() {
        if !storage.exists(source_path)? {
            eprintln!(
                "subtitle artifact not_ready video={} reason=source_missing source={source_path}",
                video.path
            );
            return Ok(None);
        }
        let source_sha256 = storage.sha256(source_path)?;
        if source_sha256 != manifest.source_sha256 {
            eprintln!(
                "subtitle artifact not_ready video={} reason=source_sha256 source={} expected={} actual={}",
                video.path, source_path, manifest.source_sha256, source_sha256
            );
            return Ok(None);
        }
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
