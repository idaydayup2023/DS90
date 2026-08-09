mod quality;
mod srt;
mod translation;

use std::collections::HashMap;
use std::fs;
use std::io::Cursor;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tempfile::TempDir;

use crate::artifact::{
    ARTIFACT_SCHEMA, SubtitleArtifact, artifact_paths, read_ready_artifact,
    validate_manifest_for_publish, video_identity,
};
use crate::config::{Config, ExternalWorkerConfig, LlmProvider, TranslationConfig};
use crate::state::{ClaimResult, StateStore, process_owner};
use crate::storage::{FileEntry, Storage, open_storage};

pub use quality::{score_source, validate_translation_quality};
pub use srt::{Cue, format as format_srt, parse as parse_srt};
pub use translation::{parse_aligned, render as render_translation, validate_output};

#[derive(Debug, Clone)]
struct SourceSubtitle {
    bytes: Vec<u8>,
    kind: String,
    path: Option<String>,
    acquisition_key: String,
}

#[derive(Serialize)]
struct CacheKey<'a> {
    schema: u32,
    prompt_version: &'a str,
    source_sha256: &'a str,
    translation: &'a TranslationConfig,
}

#[derive(Debug, Deserialize)]
struct ProbeResult {
    #[serde(default)]
    streams: Vec<SubtitleTrack>,
}

#[derive(Debug, Clone, Deserialize)]
struct SubtitleTrack {
    index: u32,
    #[serde(default)]
    codec_name: String,
    #[serde(default)]
    tags: TrackTags,
    #[serde(default)]
    disposition: TrackDisposition,
}

#[derive(Debug, Clone, Default, Deserialize)]
struct TrackTags {
    #[serde(default)]
    language: String,
    #[serde(default)]
    title: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
struct TrackDisposition {
    #[serde(default)]
    default: i32,
    #[serde(default)]
    forced: i32,
    #[serde(default)]
    hearing_impaired: i32,
}

pub fn run(cfg: &Config, dry_run: bool, force: bool, limit: Option<usize>) -> Result<()> {
    let storage = open_storage(&cfg.source)?;
    let entries = storage.list_recursive("")?;
    let videos = select_videos(&entries, cfg, limit);
    let by_directory = index_files(&entries);
    let mut state = StateStore::open(&cfg.state.database)?;
    let owner = process_owner();
    let scanned = videos.len();
    let mut translated = 0usize;
    let mut cached = 0usize;
    let mut pending = 0usize;
    let mut failures = Vec::new();

    for video in videos {
        match process_video(
            &mut state,
            storage.as_ref(),
            &video,
            &by_directory,
            cfg,
            &owner,
            dry_run,
            force,
        ) {
            Ok(VideoOutcome::Translated) => translated += 1,
            Ok(VideoOutcome::Cached) => cached += 1,
            Ok(VideoOutcome::Pending(reason)) => {
                pending += 1;
                println!("subtitles pending video={} reason={reason}", video.path);
            }
            Err(error) => {
                failures.push(format!("{}: {error:#}", video.path));
                eprintln!("subtitles failed video={} error={error:#}", video.path);
            }
        }
    }
    println!(
        "subtitles complete scanned={scanned} translated={translated} cached={cached} pending={pending} failed={}",
        failures.len()
    );
    if failures.is_empty() {
        Ok(())
    } else {
        bail!(
            "{} subtitle job(s) failed: {}",
            failures.len(),
            failures.join(" | ")
        )
    }
}

enum VideoOutcome {
    Translated,
    Cached,
    Pending(String),
}

#[allow(clippy::too_many_arguments)]
fn process_video(
    state: &mut StateStore,
    storage: &dyn Storage,
    video: &FileEntry,
    by_directory: &HashMap<String, Vec<FileEntry>>,
    cfg: &Config,
    owner: &str,
    dry_run: bool,
    force: bool,
) -> Result<VideoOutcome> {
    let acquisition_key = acquisition_key(video, cfg)?;
    if !force
        && let Some(manifest) = read_ready_artifact(storage, video)?
        && manifest.acquisition_key == acquisition_key
        && manifest.cache_key == cache_key(&manifest.source_sha256, &cfg.translation)?
    {
        println!(
            "subtitles cached video={} source={}",
            video.path, manifest.source_kind
        );
        return Ok(VideoOutcome::Cached);
    }
    if dry_run {
        let source = acquire_existing_source(storage, video, by_directory, cfg, &acquisition_key)?;
        return Ok(source.map_or_else(
            || VideoOutcome::Pending("no_existing_source".into()),
            |source| {
                let paths = artifact_paths(&video.path).expect("validated video path");
                println!(
                    "subtitles plan video={} source={} output={}",
                    video.path, source.kind, paths.output
                );
                VideoOutcome::Pending("dry_run".into())
            },
        ));
    }

    let job_id = subtitle_job_id(video, &acquisition_key);
    match state.claim(
        &job_id,
        "subtitle",
        owner,
        cfg.state.lease_seconds,
        "__artifact_is_verified_before_claim__",
        &serde_json::json!({"video": video.path}),
    )? {
        ClaimResult::Acquired => {}
        ClaimResult::AlreadyComplete => unreachable!(),
    }
    let result = (|| -> Result<VideoOutcome> {
        state.transition(
            &job_id,
            "subtitle",
            owner,
            "CLAIMED",
            "ACQUIRING",
            &serde_json::json!({"video": video.path}),
        )?;
        let source = acquire_source(storage, video, by_directory, cfg, &acquisition_key)?
            .context("no usable English subtitle source was found")?;
        state.renew(&job_id, owner, cfg.state.lease_seconds)?;
        state.transition(
            &job_id,
            "subtitle",
            owner,
            "ACQUIRING",
            "TRANSLATING",
            &serde_json::json!({"source_kind": source.kind, "source_path": source.path}),
        )?;

        let source_text =
            std::str::from_utf8(&source.bytes).context("source subtitle is not valid UTF-8")?;
        let source_cues = srt::parse(source_text)?;
        quality::validate_source(&source_cues)?;
        let output_cues = translation::translate(&source_cues, &cfg.translation)?;
        let output = srt::format(&output_cues)?;
        let reparsed = srt::parse(&output)?;
        translation::validate_output(&source_cues, &reparsed, cfg.translation.bilingual)?;
        quality::validate_translation_quality(
            &source_cues,
            &reparsed,
            &cfg.translation.target_language,
            cfg.translation.min_target_script_ratio,
        )?;
        state.renew(&job_id, owner, cfg.state.lease_seconds)?;
        state.transition(
            &job_id,
            "subtitle",
            owner,
            "TRANSLATING",
            "VERIFIED",
            &serde_json::json!({"cues": reparsed.len()}),
        )?;

        let paths = artifact_paths(&video.path)?;
        let output_bytes = output.into_bytes();
        let output_sha256 = sha256_bytes(&output_bytes);
        let source_sha256 = sha256_bytes(&source.bytes);
        let manifest = SubtitleArtifact {
            schema: ARTIFACT_SCHEMA,
            status: "ready".into(),
            video_path: video.path.clone(),
            video_identity_sha256: video_identity(video),
            source_sha256: source_sha256.clone(),
            output_sha256: output_sha256.clone(),
            cache_key: cache_key(&source_sha256, &cfg.translation)?,
            acquisition_key: source.acquisition_key,
            source_kind: source.kind,
            source_path: source.path,
            created_unix_seconds: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs(),
        };
        validate_manifest_for_publish(&manifest)?;
        // The manifest is the commit marker and is deliberately published last.
        storage.upload_atomic(&paths.output, &mut Cursor::new(&output_bytes))?;
        if storage.sha256(&paths.output)? != output_sha256 {
            bail!("published subtitle hash mismatch");
        }
        storage.upload_atomic(
            &paths.manifest,
            &mut Cursor::new(serde_json::to_vec_pretty(&manifest)?),
        )?;
        read_ready_artifact(storage, video)?
            .context("published subtitle artifact failed its final readiness check")?;
        state.transition(
            &job_id,
            "subtitle",
            owner,
            "VERIFIED",
            "READY",
            &serde_json::json!({"output": paths.output, "output_sha256": output_sha256}),
        )?;
        println!(
            "subtitles translated video={} output={}",
            video.path, paths.output
        );
        Ok(VideoOutcome::Translated)
    })();
    if let Err(error) = &result {
        let _ = state.fail(
            &job_id,
            "subtitle",
            owner,
            &serde_json::json!({"video": video.path, "error": format!("{error:#}")}),
        );
    }
    result
}

pub fn doctor(cfg: &Config) -> Result<()> {
    let scratch = tempfile::tempdir()?;
    run_capture(
        &cfg.subtitles.ffmpeg,
        &["-version".into()],
        Duration::from_secs(30),
        scratch.path(),
    )?;
    run_capture(
        &cfg.subtitles.ffprobe,
        &["-version".into()],
        Duration::from_secs(30),
        scratch.path(),
    )?;
    for (name, worker) in [
        ("ASR", cfg.subtitles.asr.as_ref()),
        ("PGS OCR", cfg.subtitles.pgs_ocr.as_ref()),
    ] {
        if let Some(worker) = worker.filter(|worker| worker.enabled) {
            ensure_executable(&worker.command)
                .with_context(|| format!("{name} worker is unavailable"))?;
            validate_worker_args(worker)?;
            if worker.version.trim().is_empty() {
                bail!("{name} worker must declare a stable version for cache identity");
            }
            let reported = run_capture(
                &worker.command,
                &worker.version_args,
                Duration::from_secs(30),
                scratch.path(),
            )?;
            if !String::from_utf8_lossy(&reported).contains(&worker.version) {
                bail!(
                    "{name} worker version probe did not contain configured version {:?}",
                    worker.version
                );
            }
        }
    }
    let url = match cfg.translation.provider {
        LlmProvider::Ollama => endpoint(&cfg.translation.base_url, "api/tags"),
        LlmProvider::OpenaiCompatible => endpoint(&cfg.translation.base_url, "models"),
    };
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(cfg.translation.timeout_seconds.min(30)))
        .build()?;
    let mut request = client.get(url);
    if let Some(key) = cfg.translation.api_key()? {
        request = request.bearer_auth(key);
    }
    let body = request.send()?.error_for_status()?.text()?;
    if !body.contains(&cfg.translation.model) {
        bail!(
            "translation service is reachable but configured model {:?} was not advertised",
            cfg.translation.model
        );
    }
    Ok(())
}

pub fn cache_key(source_sha256: &str, cfg: &TranslationConfig) -> Result<String> {
    Ok(sha256_bytes(&serde_json::to_vec(&CacheKey {
        schema: ARTIFACT_SCHEMA,
        prompt_version: translation::prompt_version(),
        source_sha256,
        translation: cfg,
    })?))
}

pub fn should_translate(force: bool, output_exists: bool, manifest_matches: bool) -> bool {
    force || !output_exists || !manifest_matches
}

fn acquisition_key(video: &FileEntry, cfg: &Config) -> Result<String> {
    #[derive(Serialize)]
    struct Acquisition<'a> {
        schema: u32,
        video_identity: String,
        source_language: &'a str,
        ffmpeg: &'a str,
        ffprobe: &'a str,
        asr: &'a Option<ExternalWorkerConfig>,
        pgs_ocr: &'a Option<ExternalWorkerConfig>,
    }
    Ok(sha256_bytes(&serde_json::to_vec(&Acquisition {
        schema: ARTIFACT_SCHEMA,
        video_identity: video_identity(video),
        source_language: &cfg.translation.source_language,
        ffmpeg: &cfg.subtitles.ffmpeg,
        ffprobe: &cfg.subtitles.ffprobe,
        asr: &cfg.subtitles.asr,
        pgs_ocr: &cfg.subtitles.pgs_ocr,
    })?))
}

fn acquire_source(
    storage: &dyn Storage,
    video: &FileEntry,
    by_directory: &HashMap<String, Vec<FileEntry>>,
    cfg: &Config,
    acquisition_key: &str,
) -> Result<Option<SourceSubtitle>> {
    if let Some(existing) =
        acquire_existing_source(storage, video, by_directory, cfg, acquisition_key)?
    {
        return Ok(Some(existing));
    }
    acquire_generated_source(storage, video, cfg, acquisition_key)
}

fn acquire_existing_source(
    storage: &dyn Storage,
    video: &FileEntry,
    by_directory: &HashMap<String, Vec<FileEntry>>,
    cfg: &Config,
    acquisition_key: &str,
) -> Result<Option<SourceSubtitle>> {
    let stem = file_stem(&video.path)?;
    let directory = parent(&video.path);
    let mut candidates = Vec::new();
    for entry in by_directory.get(directory).into_iter().flatten() {
        let Some((name_rank, kind)) = source_rank(&entry.path, stem) else {
            continue;
        };
        let bytes = storage.read(&entry.path)?;
        let Ok(text) = std::str::from_utf8(&bytes) else {
            continue;
        };
        let Ok(cues) = srt::parse(text) else {
            continue;
        };
        let Ok(quality) = quality::score_source(&cues, &cfg.translation.source_language) else {
            continue;
        };
        candidates.push((quality, name_rank, entry.path.clone(), kind, bytes));
    }
    candidates.sort_by(|left, right| {
        right
            .0
            .total_cmp(&left.0)
            .then(right.1.cmp(&left.1))
            .then(left.2.cmp(&right.2))
    });
    Ok(candidates
        .into_iter()
        .next()
        .map(|(_, _, path, kind, bytes)| SourceSubtitle {
            bytes,
            kind: kind.into(),
            path: Some(path),
            acquisition_key: acquisition_key.into(),
        }))
}

fn acquire_generated_source(
    storage: &dyn Storage,
    video: &FileEntry,
    cfg: &Config,
    acquisition_key: &str,
) -> Result<Option<SourceSubtitle>> {
    let scratch = tempfile::Builder::new().prefix("subtrans-").tempdir()?;
    let local_video = if let Some(path) = storage.local_path(&video.path)? {
        path
    } else {
        let required = video.size.saturating_add(128 * 1024 * 1024);
        let available = fs2::available_space(scratch.path())?;
        if available < required {
            bail!("insufficient scratch space for {}", video.path);
        }
        let path = scratch.path().join(format!(
            "input.{}",
            extension(&video.path).unwrap_or("media")
        ));
        storage.download(&video.path, &path)?;
        path
    };
    let tracks = probe_tracks(&local_video, cfg, &scratch)?;
    let mut english: Vec<SubtitleTrack> = tracks.into_iter().filter(is_english_track).collect();
    english.sort_by_key(track_rank);

    for track in english
        .iter()
        .filter(|track| is_text_codec(&track.codec_name))
    {
        let output = scratch.path().join(format!("embedded-{}.srt", track.index));
        let args = vec![
            "-v".into(),
            "error".into(),
            "-y".into(),
            "-i".into(),
            local_video.to_string_lossy().into_owned(),
            "-map".into(),
            format!("0:{}", track.index),
            "-f".into(),
            "srt".into(),
            output.to_string_lossy().into_owned(),
        ];
        if run_capture(
            &cfg.subtitles.ffmpeg,
            &args,
            Duration::from_secs(cfg.subtitles.external_process_timeout_seconds),
            scratch.path(),
        )
        .is_ok()
            && let Some(source) = read_generated(&output, "embedded", acquisition_key)?
        {
            return persist_generated(storage, video, source, "emb.srt");
        }
    }

    if let Some(worker) = cfg
        .subtitles
        .pgs_ocr
        .as_ref()
        .filter(|worker| worker.enabled)
        && let Some(track) = english
            .iter()
            .find(|track| is_bitmap_codec(&track.codec_name))
    {
        let output = scratch.path().join("pgs.srt");
        if run_worker(
            worker,
            &local_video,
            &output,
            &cfg.translation.source_language,
            Some(track.index),
            cfg.subtitles.external_process_timeout_seconds,
            scratch.path(),
        )? && let Some(source) = read_generated(&output, "pgs_ocr", acquisition_key)?
        {
            return persist_generated(storage, video, source, "pgs.srt");
        }
    }
    if let Some(worker) = cfg.subtitles.asr.as_ref().filter(|worker| worker.enabled) {
        let output = scratch.path().join("asr.srt");
        if run_worker(
            worker,
            &local_video,
            &output,
            &cfg.translation.source_language,
            None,
            cfg.subtitles.external_process_timeout_seconds,
            scratch.path(),
        )? && let Some(source) = read_generated(&output, "asr", acquisition_key)?
        {
            return persist_generated(storage, video, source, "asr.srt");
        }
    }
    Ok(None)
}

fn probe_tracks(video: &Path, cfg: &Config, scratch: &TempDir) -> Result<Vec<SubtitleTrack>> {
    let args = vec![
        "-v".into(),
        "error".into(),
        "-select_streams".into(),
        "s".into(),
        "-show_entries".into(),
        "stream=index,codec_name:stream_tags=language,title:stream_disposition=default,forced,hearing_impaired".into(),
        "-of".into(),
        "json".into(),
        video.to_string_lossy().into_owned(),
    ];
    let output = run_capture(
        &cfg.subtitles.ffprobe,
        &args,
        Duration::from_secs(60),
        scratch.path(),
    )?;
    Ok(serde_json::from_slice::<ProbeResult>(&output)
        .context("ffprobe returned invalid subtitle track JSON")?
        .streams)
}

fn persist_generated(
    storage: &dyn Storage,
    video: &FileEntry,
    mut source: SourceSubtitle,
    suffix: &str,
) -> Result<Option<SourceSubtitle>> {
    let stem = file_stem(&video.path)?;
    let path = if parent(&video.path).is_empty() {
        format!("{stem}.{suffix}")
    } else {
        format!("{}/{stem}.{suffix}", parent(&video.path))
    };
    storage.upload_atomic(&path, &mut Cursor::new(&source.bytes))?;
    if storage.sha256(&path)? != sha256_bytes(&source.bytes) {
        bail!("persisted generated subtitle hash mismatch");
    }
    source.path = Some(path);
    Ok(Some(source))
}

fn read_generated(
    path: &Path,
    kind: &str,
    acquisition_key: &str,
) -> Result<Option<SourceSubtitle>> {
    if !path.is_file() {
        return Ok(None);
    }
    let bytes = fs::read(path)?;
    let text = match std::str::from_utf8(&bytes) {
        Ok(text) => text,
        Err(_) => return Ok(None),
    };
    let cues = match srt::parse(text) {
        Ok(cues) => cues,
        Err(_) => return Ok(None),
    };
    quality::validate_source(&cues)?;
    Ok(Some(SourceSubtitle {
        bytes,
        kind: kind.into(),
        path: None,
        acquisition_key: acquisition_key.into(),
    }))
}

#[allow(clippy::too_many_arguments)]
fn run_worker(
    worker: &ExternalWorkerConfig,
    input: &Path,
    output: &Path,
    language: &str,
    stream: Option<u32>,
    timeout_seconds: u64,
    scratch: &Path,
) -> Result<bool> {
    validate_worker_args(worker)?;
    let args: Vec<String> = worker
        .args
        .iter()
        .map(|arg| {
            arg.replace("{input}", &input.to_string_lossy())
                .replace("{output}", &output.to_string_lossy())
                .replace("{language}", language)
                .replace(
                    "{stream}",
                    &stream.map_or_else(String::new, |value| value.to_string()),
                )
        })
        .collect();
    match run_capture(
        &worker.command,
        &args,
        Duration::from_secs(timeout_seconds),
        scratch,
    ) {
        Ok(_) => Ok(true),
        Err(error) => {
            eprintln!(
                "optional worker failed command={} version={} error={error:#}",
                worker.command, worker.version
            );
            Ok(false)
        }
    }
}

fn run_capture(
    program: &str,
    args: &[String],
    timeout: Duration,
    scratch: &Path,
) -> Result<Vec<u8>> {
    ensure_executable(program)?;
    let stdout_path = scratch.join(format!(
        "stdout-{}",
        sha256_bytes(args.join("\0").as_bytes())
    ));
    let stderr_path = scratch.join(format!(
        "stderr-{}",
        sha256_bytes(args.join("\0").as_bytes())
    ));
    let stdout = fs::File::create(&stdout_path)?;
    let stderr = fs::File::create(&stderr_path)?;
    let mut child = Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
        .with_context(|| format!("failed to launch {program}"))?;
    let deadline = std::time::Instant::now() + timeout;
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if std::time::Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            bail!(
                "external process {program} exceeded {} seconds",
                timeout.as_secs()
            );
        }
        std::thread::sleep(Duration::from_millis(100));
    };
    let stderr = read_limited(&stderr_path, 64 * 1024)?;
    if !status.success() {
        bail!(
            "external process {program} failed with {status}: {}",
            String::from_utf8_lossy(&stderr)
        );
    }
    read_limited(&stdout_path, 16 * 1024 * 1024)
}

fn read_limited(path: &Path, limit: usize) -> Result<Vec<u8>> {
    let metadata = fs::metadata(path)?;
    if metadata.len() > limit as u64 {
        bail!("external process output exceeded {limit} bytes");
    }
    Ok(fs::read(path)?)
}

fn validate_worker_args(worker: &ExternalWorkerConfig) -> Result<()> {
    let joined = worker.args.join("\0");
    if !joined.contains("{input}") || !joined.contains("{output}") {
        bail!("worker args must contain both {{input}} and {{output}} placeholders");
    }
    Ok(())
}

fn is_english_track(track: &SubtitleTrack) -> bool {
    let language = track.tags.language.to_ascii_lowercase();
    let title = track.tags.title.to_ascii_lowercase();
    matches!(language.as_str(), "en" | "eng" | "english")
        || language.starts_with("en-")
        || language.starts_with("en_")
        || title.contains("english")
        || title.starts_with("eng")
}

fn track_rank(track: &SubtitleTrack) -> (u8, u8, u8, u8, u32) {
    (
        u8::from(!is_text_codec(&track.codec_name)),
        u8::from(track.disposition.default == 0),
        u8::from(track.disposition.forced != 0),
        u8::from(
            track.disposition.hearing_impaired != 0
                || track.tags.title.to_ascii_lowercase().contains("sdh"),
        ),
        track.index,
    )
}

fn is_text_codec(codec: &str) -> bool {
    matches!(
        codec.to_ascii_lowercase().as_str(),
        "subrip" | "srt" | "ass" | "ssa" | "webvtt" | "mov_text" | "text"
    )
}

fn is_bitmap_codec(codec: &str) -> bool {
    matches!(
        codec.to_ascii_lowercase().as_str(),
        "hdmv_pgs_subtitle" | "dvd_subtitle" | "dvb_subtitle"
    )
}

fn select_videos(entries: &[FileEntry], cfg: &Config, limit: Option<usize>) -> Vec<FileEntry> {
    let extensions: Vec<String> = cfg
        .subtitles
        .video_extensions
        .iter()
        .map(|extension| extension.trim_start_matches('.').to_ascii_lowercase())
        .collect();
    let mut videos: Vec<_> = entries
        .iter()
        .filter(|entry| {
            !entry.is_dir
                && entry.size >= cfg.subtitles.min_video_bytes
                && extension(&entry.path).is_some_and(|candidate| {
                    extensions
                        .iter()
                        .any(|allowed| allowed.eq_ignore_ascii_case(candidate))
                })
        })
        .cloned()
        .collect();
    videos.sort_by(|left, right| left.path.cmp(&right.path));
    videos.truncate(limit.unwrap_or(usize::MAX));
    videos
}

fn index_files(entries: &[FileEntry]) -> HashMap<String, Vec<FileEntry>> {
    let mut index: HashMap<String, Vec<FileEntry>> = HashMap::new();
    for entry in entries.iter().filter(|entry| !entry.is_dir) {
        index
            .entry(parent(&entry.path).into())
            .or_default()
            .push(entry.clone());
    }
    index
}

fn source_rank(path: &str, video_stem: &str) -> Option<(u32, &'static str)> {
    let name = basename(path).to_ascii_lowercase();
    let stem = video_stem.to_ascii_lowercase();
    if name.ends_with(".ai.srt") || name.ends_with(".subtrans.json") {
        return None;
    }
    if name == format!("{stem}.en.srt") || name == format!("{stem}.eng.srt") {
        return Some((500, "external_english"));
    }
    if ["en-us", "en-gb", "english"]
        .iter()
        .any(|language| name == format!("{stem}.{language}.srt"))
    {
        return Some((490, "external_english_variant"));
    }
    if name == format!("{stem}.srt") {
        return Some((450, "external"));
    }
    if name == format!("{stem}.emb.srt") {
        return Some((400, "embedded_cached"));
    }
    if name == format!("{stem}.pgs.srt") {
        return Some((350, "pgs_cached"));
    }
    if name == format!("{stem}.asr.srt") {
        return Some((300, "asr_cached"));
    }
    if name.starts_with(&format!("{stem}.")) && name.ends_with(".srt") {
        return Some((250, "external_variant"));
    }
    None
}

fn subtitle_job_id(video: &FileEntry, acquisition_key: &str) -> String {
    sha256_bytes(format!("subtitle-v2\0{}\0{acquisition_key}", video.path).as_bytes())
}

fn parent(path: &str) -> &str {
    path.rsplit_once('/').map_or("", |(parent, _)| parent)
}

fn basename(path: &str) -> &str {
    path.rsplit('/').next().unwrap_or(path)
}

fn file_stem(path: &str) -> Result<&str> {
    basename(path)
        .rsplit_once('.')
        .map(|(stem, _)| stem)
        .filter(|stem| !stem.is_empty())
        .context("path has no usable file stem")
}

fn extension(path: &str) -> Option<&str> {
    basename(path)
        .rsplit_once('.')
        .map(|(_, extension)| extension)
}

fn sha256_bytes(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn ensure_executable(command: &str) -> Result<PathBuf> {
    let candidate = Path::new(command);
    if candidate.components().count() > 1 {
        if candidate.is_file() {
            return Ok(candidate.to_owned());
        }
        bail!("{} does not exist", candidate.display());
    }
    let path = std::env::var_os("PATH").context("PATH is not set")?;
    std::env::split_paths(&path)
        .map(|directory| directory.join(command))
        .find(|candidate| candidate.is_file())
        .with_context(|| format!("{command} was not found on PATH"))
}

fn endpoint(base: &str, suffix: &str) -> String {
    let trimmed = base.trim_end_matches('/');
    if trimmed.ends_with(suffix) {
        trimmed.into()
    } else {
        format!("{trimmed}/{suffix}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ranks_default_english_text_before_forced_sdh_and_bitmap() {
        let probe: ProbeResult = serde_json::from_str(
            r#"{"streams":[
                {"index":5,"codec_name":"hdmv_pgs_subtitle","tags":{"language":"eng"}},
                {"index":3,"codec_name":"subrip","tags":{"language":"en-US","title":"English SDH"},"disposition":{"hearing_impaired":1}},
                {"index":2,"codec_name":"subrip","tags":{"language":"eng"},"disposition":{"default":1}},
                {"index":1,"codec_name":"subrip","tags":{"language":"chi"}}
            ]}"#,
        )
        .unwrap();
        let mut english: Vec<_> = probe.streams.into_iter().filter(is_english_track).collect();
        english.sort_by_key(track_rank);
        assert_eq!(
            english.iter().map(|track| track.index).collect::<Vec<_>>(),
            vec![2, 3, 5]
        );
    }

    #[test]
    fn external_process_timeout_is_enforced() {
        let scratch = tempfile::tempdir().unwrap();
        let error = run_capture(
            "/bin/sleep",
            &["2".to_owned()],
            Duration::from_millis(10),
            scratch.path(),
        )
        .unwrap_err();
        assert!(error.to_string().contains("exceeded"));
    }
}
