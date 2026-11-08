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
pub struct TranslationQualityRecord {
    pub cue_index: u32,
    pub source: String,
    pub candidate_before_review: String,
    pub reviewed_translation: String,
    pub reasons: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub primary_error: Option<String>,
    pub translation_model: String,
    pub review_model: String,
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
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub translation_quality_log: Vec<TranslationQualityRecord>,
    pub created_unix_seconds: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactPaths {
    pub output: String,
    pub manifest: String,
}

/// Extension of the `.ai.<ext>` subtitle output the engine publishes unless
/// `subtitles.artifact_output_extension` says otherwise.
pub const DEFAULT_ARTIFACT_OUTPUT_EXTENSION: &str = "srt";

/// Output extensions the read side recognizes. `.ai.ass` outputs are produced
/// by the roster tooling under `tools/`, so the engine must see them as ready
/// artifacts (and must never treat them as blind-overwrite candidates).
pub const KNOWN_ARTIFACT_OUTPUT_EXTENSIONS: [&str; 2] = ["srt", "ass"];

/// Validate a `.ai.<ext>` output extension: 1-8 lowercase ASCII letters or
/// digits, no leading dot, no separators. Keeps a configured value from
/// ever steering the writer outside the `<stem>.ai.<ext>` naming shape.
fn validate_artifact_output_extension(extension: &str) -> Result<()> {
    let ok = !extension.is_empty()
        && extension.len() <= 8
        && extension
            .chars()
            .all(|character| character.is_ascii_lowercase() || character.is_ascii_digit());
    if !ok {
        bail!(
            "subtitle artifact output extension {extension:?} must be 1-8 lowercase ASCII letters or digits without a dot"
        );
    }
    Ok(())
}

pub fn artifact_paths(video_path: &str) -> Result<ArtifactPaths> {
    artifact_paths_with_extension(video_path, DEFAULT_ARTIFACT_OUTPUT_EXTENSION)
}

/// Artifact paths for one concrete output extension (no dot, e.g. `srt` or
/// `ass`). The manifest name always tracks the output it vouches for.
pub fn artifact_paths_with_extension(
    video_path: &str,
    output_extension: &str,
) -> Result<ArtifactPaths> {
    validate_artifact_output_extension(output_extension)?;
    let path = Path::new(video_path);
    let stem = path
        .file_stem()
        .and_then(|value| value.to_str())
        .context("video file name is not valid UTF-8")?;
    let parent = path.parent().and_then(Path::to_str).unwrap_or("");
    let output_name = format!("{stem}.ai.{output_extension}");
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

/// Read the ready artifact for a video, recognizing every known output
/// form. Candidates are probed in `KNOWN_ARTIFACT_OUTPUT_EXTENSIONS` order
/// and the first candidate with any trace (output or manifest) owns the
/// verdict. That keeps the historical single-form behavior exactly for
/// libraries that only ever held `.ai.srt` pairs, while roster-produced
/// `.ai.ass` pairs are honored whenever no `.ai.srt` trace exists.
pub fn read_ready_artifact(
    storage: &dyn Storage,
    video: &FileEntry,
) -> Result<Option<SubtitleArtifact>> {
    for extension in KNOWN_ARTIFACT_OUTPUT_EXTENSIONS {
        let paths = artifact_paths_with_extension(&video.path, extension)?;
        if storage.exists(&paths.output)? || storage.exists(&paths.manifest)? {
            return validate_ready_manifest(storage, video, &paths);
        }
    }
    eprintln!(
        "subtitle artifact not_ready video={} reason=missing output_exists=false manifest_exists=false",
        video.path
    );
    Ok(None)
}

fn validate_ready_manifest(
    storage: &dyn Storage,
    video: &FileEntry,
    paths: &ArtifactPaths,
) -> Result<Option<SubtitleArtifact>> {
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::{LocalStorage, Storage};
    use std::io::Cursor;

    fn sha(bytes: &[u8]) -> String {
        let mut digest = Sha256::new();
        digest.update(bytes);
        hex::encode(digest.finalize())
    }

    fn entry(path: &str, bytes: &[u8]) -> FileEntry {
        FileEntry {
            path: path.to_owned(),
            size: bytes.len() as u64,
            is_dir: false,
            modified: None,
        }
    }

    fn ready_manifest(video: &FileEntry, output_sha256: &str) -> SubtitleArtifact {
        SubtitleArtifact {
            schema: ARTIFACT_SCHEMA,
            status: "ready".into(),
            video_path: video.path.clone(),
            video_identity_sha256: video_identity(video),
            source_sha256: "a".repeat(64),
            output_sha256: output_sha256.into(),
            cache_key: "cache-key".into(),
            acquisition_key: "acquisition-key".into(),
            source_kind: "embedded".into(),
            source_path: None,
            source_evidence: None,
            translation_quality_log: vec![],
            created_unix_seconds: 1,
        }
    }

    #[test]
    fn default_paths_keep_the_historical_ai_srt_naming() {
        let paths = artifact_paths("TV/Show/movie.mkv").unwrap();
        assert_eq!(paths.output, "TV/Show/movie.ai.srt");
        assert!(paths.manifest.starts_with("TV/Show/movie.ai.srt."));
        assert!(paths.manifest.ends_with(".json"));
    }

    #[test]
    fn ass_extension_produces_the_ass_form() {
        let paths = artifact_paths_with_extension("movie.mkv", "ass").unwrap();
        assert_eq!(paths.output, "movie.ai.ass");
        assert!(paths.manifest.starts_with("movie.ai.ass."));
        assert!(paths.manifest.ends_with(".json"));
    }

    #[test]
    fn unsafe_output_extensions_are_rejected() {
        for bad in ["", "SRT", "s rt", "sr.t", "srt/", ".srt", "abcdefghij"] {
            assert!(
                artifact_paths_with_extension("movie.mkv", bad).is_err(),
                "extension {bad:?} must be rejected"
            );
        }
    }

    fn seeded_storage() -> (tempfile::TempDir, LocalStorage) {
        let scratch = tempfile::tempdir().unwrap();
        let storage = LocalStorage::new(scratch.path()).unwrap();
        storage.create_dir_all("TV/Show").unwrap();
        (scratch, storage)
    }

    fn upload(storage: &dyn Storage, path: &str, bytes: &[u8]) {
        storage
            .upload_atomic(path, &mut Cursor::new(bytes.to_vec()))
            .unwrap();
    }

    #[test]
    fn ready_ass_pair_is_recognized_when_no_srt_trace_exists() {
        let (_scratch, storage) = seeded_storage();
        let video_path = "TV/Show/movie.mkv";
        let output_bytes = b"1\n00:00:01,000 --> 00:00:02,000\nhello\n".to_vec();
        let video = entry(video_path, b"video-bytes");
        let paths = artifact_paths_with_extension(video_path, "ass").unwrap();
        upload(&storage, &paths.output, &output_bytes);
        let manifest = ready_manifest(&video, &sha(&output_bytes));
        upload(
            &storage,
            &paths.manifest,
            &serde_json::to_vec(&manifest).unwrap(),
        );
        // Nothing exists for the srt candidate, so the ass pair must count.
        let ready = read_ready_artifact(&storage, &video).unwrap();
        assert!(ready.is_some(), "ass pair must be recognized as ready");
        assert_eq!(ready.unwrap().cache_key, "cache-key");
    }

    #[test]
    fn missing_pair_yields_not_ready() {
        let (_scratch, storage) = seeded_storage();
        let video = entry("TV/Show/movie.mkv", b"video-bytes");
        assert!(read_ready_artifact(&storage, &video).unwrap().is_none());
    }

    #[test]
    fn partial_srt_trace_owns_the_verdict_over_a_valid_ass_pair() {
        let (_scratch, storage) = seeded_storage();
        let video_path = "TV/Show/movie.mkv";
        let video = entry(video_path, b"video-bytes");
        // A half-published srt (output without its manifest) keeps the
        // historical partial_publish verdict; it is not rescued by another form.
        let srt = artifact_paths(video_path).unwrap();
        upload(&storage, &srt.output, b"partial");
        let ass_bytes = b"1\n00:00:01,000 --> 00:00:02,000\nhello\n".to_vec();
        let ass = artifact_paths_with_extension(video_path, "ass").unwrap();
        upload(&storage, &ass.output, &ass_bytes);
        let manifest = ready_manifest(&video, &sha(&ass_bytes));
        upload(
            &storage,
            &ass.manifest,
            &serde_json::to_vec(&manifest).unwrap(),
        );
        assert!(read_ready_artifact(&storage, &video).unwrap().is_none());
    }
}
