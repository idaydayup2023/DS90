use std::cmp::Ordering;
use std::collections::HashSet;
use std::io::{Cursor, Read};
use std::path::Path;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};
use reqwest::StatusCode;
use reqwest::blocking::{Client, Response};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::config::{Config, MetadataConfig, MetadataOverride, OverrideKind};
use crate::migration::{Classification, MediaKind, classify_path};
use crate::storage::{FileEntry, Storage, open_storage};

pub const METADATA_SCHEMA: u32 = 1;
const PROVIDER: &str = "tmdb";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FetchMode {
    Default,
    Supplement,
    Force,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetadataArtifact {
    pub role: String,
    pub path: String,
    pub sha256: String,
    pub managed: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetadataManifest {
    pub schema: u32,
    pub status: String,
    pub provider: String,
    pub tmdb_id: u64,
    pub episode_tmdb_id: Option<u64>,
    pub media_kind: String,
    pub title: String,
    pub original_title: Option<String>,
    pub year: Option<u16>,
    pub season: Option<u16>,
    pub episode: Option<u16>,
    pub language: String,
    pub video_path: String,
    pub video_identity_sha256: String,
    pub config_sha256: String,
    pub fetched_unix_seconds: u64,
    pub artifacts: Vec<MetadataArtifact>,
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct MetadataSummary {
    pub scanned: usize,
    pub fetched: usize,
    pub cached: usize,
    pub pending: usize,
    pub failed: usize,
}

#[derive(Debug, Clone)]
struct ResolvedMedia {
    kind: MediaKind,
    tmdb_id: u64,
    item_tmdb_id: u64,
    title: String,
    episode_title: Option<String>,
    original_title: Option<String>,
    year: Option<u16>,
    season: Option<u16>,
    episode: Option<u16>,
    overview: String,
    tagline: Option<String>,
    release_date: Option<String>,
    runtime: Option<u64>,
    rating: Option<f64>,
    genres: Vec<String>,
    studios: Vec<String>,
    countries: Vec<String>,
    directors: Vec<String>,
    cast: Vec<CastMember>,
    imdb_id: Option<String>,
    poster_path: Option<String>,
    backdrop_path: Option<String>,
}

#[derive(Debug, Clone)]
struct CastMember {
    name: String,
    role: Option<String>,
}

#[derive(Debug, Deserialize)]
struct SearchResponse {
    #[serde(default)]
    results: Vec<SearchResult>,
}

#[derive(Debug, Clone, Deserialize)]
struct SearchResult {
    id: u64,
    title: Option<String>,
    name: Option<String>,
    original_title: Option<String>,
    original_name: Option<String>,
    release_date: Option<String>,
    first_air_date: Option<String>,
}

pub fn run(
    cfg: &Config,
    mode: FetchMode,
    dry_run: bool,
    limit: Option<usize>,
) -> Result<MetadataSummary> {
    if !cfg.metadata.enabled {
        bail!("metadata is disabled; set metadata.enabled=true in the configuration");
    }
    let storage = open_storage(&cfg.source).context("failed to open metadata source storage")?;
    run_on_storage(cfg, storage.as_ref(), mode, dry_run, limit)
}

pub fn ensure_before(cfg: &Config, dry_run: bool, limit: Option<usize>) -> Result<()> {
    if !cfg.metadata.enabled {
        return Ok(());
    }
    let summary = run(cfg, FetchMode::Default, dry_run, limit)?;
    // Incomplete downloads are pending by design and each downstream stage
    // independently skips the exact marked video. They must not block metadata-
    // ready sibling videos in the same FTP source tree.
    if !dry_run && summary.failed > 0 {
        bail!(
            "metadata prerequisite is not ready: failed={}; resolve the reported title or configure [metadata.overrides] before continuing",
            summary.failed
        );
    }
    Ok(())
}

fn run_on_storage(
    cfg: &Config,
    storage: &dyn Storage,
    mode: FetchMode,
    dry_run: bool,
    limit: Option<usize>,
) -> Result<MetadataSummary> {
    let entries = storage.list_recursive("")?;
    let extensions: HashSet<_> = cfg
        .subtitles
        .video_extensions
        .iter()
        .map(|value| value.trim_start_matches('.').to_ascii_lowercase())
        .collect();
    let mut videos: Vec<_> = entries
        .iter()
        .filter(|entry| {
            !entry.is_dir
                && entry.size >= cfg.subtitles.min_video_bytes
                && extension(&entry.path).is_some_and(|value| extensions.contains(&value))
        })
        .cloned()
        .collect();
    videos.sort_by(|left, right| left.path.cmp(&right.path));
    videos.truncate(limit.unwrap_or(usize::MAX));

    let mut client = None;
    let mut summary = MetadataSummary {
        scanned: videos.len(),
        ..MetadataSummary::default()
    };
    let mut failures = Vec::new();
    for video in videos {
        if let Some(marker) = incomplete_marker(&entries, &video, cfg) {
            summary.pending += 1;
            println!(
                "metadata pending video={} reason=incomplete_download_marker marker={marker}",
                video.path
            );
            continue;
        }
        if dry_run {
            let selection = selection_for(cfg, &video.path);
            println!(
                "metadata dry_run video={} classification={} title={} year={}",
                video.path,
                kind_name(selection.kind),
                selection.title.as_deref().unwrap_or("<pending>"),
                selection
                    .year
                    .map(|value| value.to_string())
                    .as_deref()
                    .unwrap_or("<unknown>")
            );
            continue;
        }
        if mode != FetchMode::Force && read_ready_metadata(storage, &video, cfg)?.is_some() {
            summary.cached += 1;
            println!("metadata cached video={}", video.path);
            continue;
        }
        if client.is_none() {
            client = Some(TmdbClient::new(&cfg.metadata)?);
        }
        match process_video(
            cfg,
            storage,
            client.as_ref().expect("client was initialized"),
            &video,
            mode,
        ) {
            Ok(()) => summary.fetched += 1,
            Err(error) => {
                summary.failed += 1;
                eprintln!("metadata failed video={} error={error:#}", video.path);
                failures.push(format!("{}: {error:#}", video.path));
            }
        }
    }
    println!(
        "metadata complete scanned={} fetched={} cached={} pending={} failed={} provider=TMDB",
        summary.scanned, summary.fetched, summary.cached, summary.pending, summary.failed
    );
    if failures.is_empty() {
        Ok(summary)
    } else {
        bail!(
            "{} metadata job(s) failed: {}",
            failures.len(),
            failures.join(" | ")
        )
    }
}

fn process_video(
    cfg: &Config,
    storage: &dyn Storage,
    client: &TmdbClient,
    video: &FileEntry,
    mode: FetchMode,
) -> Result<()> {
    let paths = artifact_paths(&video.path)?;
    let manifest_exists = storage.exists(&paths.manifest)?;
    let previous_manifest = manifest_exists
        .then(|| storage.read(&paths.manifest))
        .transpose()?
        .and_then(|bytes| serde_json::from_slice::<MetadataManifest>(&bytes).ok());
    let unmanaged_paths: HashSet<_> = previous_manifest
        .as_ref()
        .into_iter()
        .flat_map(|manifest| manifest.artifacts.iter())
        .filter(|artifact| !artifact.managed)
        .map(|artifact| artifact.path.as_str())
        .collect();
    let mut occupied = Vec::new();
    for path in [&paths.nfo, &paths.poster, &paths.fanart] {
        if storage.exists(path)? {
            occupied.push(path.clone());
        }
    }
    if mode == FetchMode::Default && !manifest_exists && !occupied.is_empty() {
        bail!(
            "existing local artwork/metadata is not managed by subtrans: {}; use --supplement to keep it or --force to replace it",
            occupied.join(", ")
        );
    }

    let selection = selection_for(cfg, &video.path);
    if selection.is_pending() {
        bail!(
            "media classification is not safe enough for metadata lookup: {}; add an exact [metadata.overrides.{}] entry with kind and tmdb_id",
            selection
                .pending_reason
                .as_deref()
                .unwrap_or("missing type/title evidence"),
            serde_json::to_string(&video.path)?
        );
    }
    let direct = cfg.metadata.overrides.get(&video.path);
    let resolved = client.resolve(&selection, direct).with_context(|| {
        format!(
            "TMDB lookup failed; add [metadata.overrides.{}] with the exact TMDB ID if the title is ambiguous",
            serde_json::to_string(&video.path).unwrap_or_else(|_| format!("{:?}", video.path))
        )
    })?;
    let nfo = render_nfo(&resolved).into_bytes();
    let poster_path = resolved
        .poster_path
        .as_deref()
        .context("TMDB record has no poster artwork")?;
    let poster = client.image(poster_path)?;
    validate_jpeg(&poster, "poster")?;
    let fanart = resolved
        .backdrop_path
        .as_deref()
        .map(|path| client.image(path))
        .transpose()?;
    if let Some(bytes) = fanart.as_deref() {
        validate_jpeg(bytes, "fanart")?;
    }

    let mut artifacts = Vec::new();
    publish_artifact(
        storage,
        &paths.nfo,
        "nfo",
        &nfo,
        mode,
        unmanaged_paths.contains(paths.nfo.as_str()),
        &mut artifacts,
    )?;
    publish_artifact(
        storage,
        &paths.poster,
        "poster",
        &poster,
        mode,
        unmanaged_paths.contains(paths.poster.as_str()),
        &mut artifacts,
    )?;
    if let Some(bytes) = fanart.as_deref() {
        publish_artifact(
            storage,
            &paths.fanart,
            "fanart",
            bytes,
            mode,
            unmanaged_paths.contains(paths.fanart.as_str()),
            &mut artifacts,
        )?;
    }
    let manifest = MetadataManifest {
        schema: METADATA_SCHEMA,
        status: "ready".into(),
        provider: PROVIDER.into(),
        tmdb_id: resolved.tmdb_id,
        episode_tmdb_id: (resolved.kind == MediaKind::Tv).then_some(resolved.item_tmdb_id),
        media_kind: kind_name(resolved.kind).into(),
        title: resolved.title,
        original_title: resolved.original_title,
        year: resolved.year,
        season: resolved.season,
        episode: resolved.episode,
        language: cfg.metadata.language.clone(),
        video_path: video.path.clone(),
        video_identity_sha256: video_identity(video),
        config_sha256: config_hash(&cfg.metadata)?,
        fetched_unix_seconds: now_seconds()?,
        artifacts,
    };
    let bytes = serde_json::to_vec_pretty(&manifest)?;
    storage.upload_atomic(&paths.manifest, &mut Cursor::new(bytes))?;
    println!(
        "metadata fetched video={} tmdb_id={} kind={}",
        video.path, manifest.tmdb_id, manifest.media_kind
    );
    Ok(())
}

fn publish_artifact(
    storage: &dyn Storage,
    path: &str,
    role: &str,
    bytes: &[u8],
    mode: FetchMode,
    was_unmanaged: bool,
    artifacts: &mut Vec<MetadataArtifact>,
) -> Result<()> {
    if (mode == FetchMode::Supplement || (mode == FetchMode::Default && was_unmanaged))
        && storage.exists(path)?
    {
        artifacts.push(MetadataArtifact {
            role: role.into(),
            path: path.into(),
            sha256: storage.sha256(path)?,
            managed: false,
        });
        return Ok(());
    }
    storage
        .upload_atomic(path, &mut Cursor::new(bytes))
        .with_context(|| format!("failed to publish {role} {path}"))?;
    artifacts.push(MetadataArtifact {
        role: role.into(),
        path: path.into(),
        sha256: hash(bytes),
        managed: true,
    });
    Ok(())
}

pub fn read_ready_metadata(
    storage: &dyn Storage,
    video: &FileEntry,
    cfg: &Config,
) -> Result<Option<MetadataManifest>> {
    if !cfg.metadata.enabled {
        return Ok(None);
    }
    let path = artifact_paths(&video.path)?.manifest;
    if !storage.exists(&path)? {
        return Ok(None);
    }
    let manifest: MetadataManifest = match serde_json::from_slice(&storage.read(&path)?) {
        Ok(value) => value,
        Err(_) => return Ok(None),
    };
    if manifest.schema != METADATA_SCHEMA
        || manifest.status != "ready"
        || manifest.provider != PROVIDER
        || manifest.video_path != video.path
        || manifest.video_identity_sha256 != video_identity(video)
        || manifest.config_sha256 != config_hash(&cfg.metadata)?
    {
        return Ok(None);
    }
    let age = now_seconds()?.saturating_sub(manifest.fetched_unix_seconds);
    if age > u64::from(cfg.metadata.refresh_after_days) * 86_400 {
        return Ok(None);
    }
    if !manifest.artifacts.iter().any(|value| value.role == "nfo")
        || !manifest
            .artifacts
            .iter()
            .any(|value| value.role == "poster")
    {
        return Ok(None);
    }
    for artifact in &manifest.artifacts {
        if !storage.exists(&artifact.path)? || storage.sha256(&artifact.path)? != artifact.sha256 {
            return Ok(None);
        }
    }
    Ok(Some(manifest))
}

pub fn doctor(cfg: &Config) -> Result<()> {
    if !cfg.metadata.enabled {
        println!("metadata disabled");
        return Ok(());
    }
    let client = TmdbClient::new(&cfg.metadata)?;
    let _: Value = client.json("configuration", &[])?;
    println!(
        "metadata provider=TMDB language={} fallback={} ready",
        cfg.metadata.language, cfg.metadata.fallback_language
    );
    Ok(())
}

struct ArtifactPaths {
    nfo: String,
    poster: String,
    fanart: String,
    manifest: String,
}

fn artifact_paths(video: &str) -> Result<ArtifactPaths> {
    let path = Path::new(video);
    let parent = path.parent().and_then(Path::to_str).unwrap_or("");
    let stem = path
        .file_stem()
        .and_then(|value| value.to_str())
        .context("video path is not valid UTF-8")?;
    let joined = |name: String| {
        if parent.is_empty() {
            name
        } else {
            format!("{parent}/{name}")
        }
    };
    Ok(ArtifactPaths {
        nfo: joined(format!("{stem}.nfo")),
        poster: joined(format!("{stem}.jpg")),
        fanart: joined(format!("{stem}-fanart.jpg")),
        manifest: joined(format!("{stem}.subtrans.metadata.json")),
    })
}

fn selection_for(cfg: &Config, path: &str) -> Classification {
    let base = if let Some(value) = cfg.migration.overrides.get(path) {
        Classification {
            kind: match value.kind {
                OverrideKind::Movie => MediaKind::Movie,
                OverrideKind::Tv => MediaKind::Tv,
            },
            title: Some(value.title.clone()),
            year: value.year,
            season: value.season,
            episode: value.episode,
            is_4k: value.is_4k.unwrap_or(false),
            confidence: 1.0,
            evidence: Vec::new(),
            pending_reason: None,
        }
    } else {
        classify_path(path)
    };
    cfg.metadata
        .overrides
        .get(path)
        .map(|value| apply_metadata_override(base.clone(), value))
        .unwrap_or(base)
}

fn apply_metadata_override(base: Classification, value: &MetadataOverride) -> Classification {
    let override_kind = match value.kind {
        OverrideKind::Movie => MediaKind::Movie,
        OverrideKind::Tv => MediaKind::Tv,
    };
    if !base.is_pending()
        && (base.kind != override_kind
            || (override_kind == MediaKind::Tv
                && (base.season != value.season || base.episode != value.episode)))
    {
        return Classification {
            kind: MediaKind::Unknown,
            title: None,
            year: None,
            season: value.season,
            episode: value.episode,
            is_4k: base.is_4k,
            confidence: 0.0,
            evidence: base.evidence,
            pending_reason: Some(
                "metadata override conflicts with deterministic or migration classification".into(),
            ),
        };
    }
    if base.is_pending() {
        Classification {
            kind: override_kind,
            title: None,
            year: None,
            season: value.season,
            episode: value.episode,
            is_4k: base.is_4k,
            confidence: 1.0,
            evidence: base.evidence,
            pending_reason: None,
        }
    } else {
        base
    }
}

struct TmdbClient {
    client: Client,
    token: String,
    config: MetadataConfig,
}

impl TmdbClient {
    fn new(config: &MetadataConfig) -> Result<Self> {
        let client = Client::builder()
            .timeout(Duration::from_secs(config.timeout_seconds))
            .user_agent(concat!("subtrans/", env!("CARGO_PKG_VERSION")))
            .build()
            .context("failed to create TMDB HTTP client")?;
        Ok(Self {
            client,
            token: config.api_token()?,
            config: config.clone(),
        })
    }

    fn resolve(
        &self,
        selection: &Classification,
        direct: Option<&MetadataOverride>,
    ) -> Result<ResolvedMedia> {
        let id = match direct {
            Some(value) => value.tmdb_id,
            None => self.search(selection)?,
        };
        match selection.kind {
            MediaKind::Movie => self.movie(id),
            MediaKind::Tv => self.episode(
                id,
                selection.season.context("TV season is missing")?,
                selection.episode.context("TV episode is missing")?,
            ),
            MediaKind::Unknown => bail!("unknown media type cannot be sent to TMDB"),
        }
    }

    fn search(&self, selection: &Classification) -> Result<u64> {
        let title = selection
            .title
            .as_deref()
            .context("media title is missing")?;
        let endpoint = match selection.kind {
            MediaKind::Movie => "search/movie",
            MediaKind::Tv => "search/tv",
            MediaKind::Unknown => bail!("unknown media type cannot be searched"),
        };
        let year = selection.year.map(|value| value.to_string());
        let mut parameters = vec![
            ("query", title),
            ("language", self.config.language.as_str()),
            ("include_adult", "false"),
        ];
        if let Some(year) = year.as_deref() {
            parameters.push((
                if selection.kind == MediaKind::Movie {
                    "year"
                } else {
                    "first_air_date_year"
                },
                year,
            ));
        }
        let response: SearchResponse = self.json(endpoint, &parameters)?;
        let mut ranked: Vec<_> = response
            .results
            .into_iter()
            .map(|candidate| {
                let score = match_score(title, selection.year, &candidate);
                (candidate, score)
            })
            .collect();
        ranked.sort_by(|left, right| right.1.partial_cmp(&left.1).unwrap_or(Ordering::Equal));
        let Some((best, best_score)) = ranked.first() else {
            bail!("TMDB returned no matching results for {title:?}");
        };
        let second_score = ranked.get(1).map(|value| value.1).unwrap_or(0.0);
        if *best_score < self.config.match_threshold {
            bail!(
                "best TMDB result for {title:?} scored {:.2}, below threshold {:.2}",
                best_score,
                self.config.match_threshold
            );
        }
        if *best_score - second_score < self.config.ambiguity_gap {
            bail!(
                "TMDB results for {title:?} are ambiguous (scores {:.2} and {:.2})",
                best_score,
                second_score
            );
        }
        Ok(best.id)
    }

    fn movie(&self, id: u64) -> Result<ResolvedMedia> {
        let primary: Value = self.json(
            &format!("movie/{id}"),
            &[
                ("language", self.config.language.as_str()),
                ("append_to_response", "credits"),
            ],
        )?;
        let fallback = self.fallback("movie", id);
        Ok(ResolvedMedia {
            kind: MediaKind::Movie,
            tmdb_id: id,
            item_tmdb_id: id,
            title: text(&primary, "title")
                .or_else(|| text(&fallback, "title"))
                .context("TMDB movie title is missing")?,
            episode_title: None,
            original_title: text(&primary, "original_title"),
            year: text(&primary, "release_date").and_then(|value| parse_year(&value)),
            season: None,
            episode: None,
            overview: text(&primary, "overview")
                .filter(|value| !value.is_empty())
                .or_else(|| text(&fallback, "overview"))
                .unwrap_or_default(),
            tagline: text(&primary, "tagline").or_else(|| text(&fallback, "tagline")),
            release_date: text(&primary, "release_date"),
            runtime: primary.get("runtime").and_then(Value::as_u64),
            rating: primary.get("vote_average").and_then(Value::as_f64),
            genres: names(&primary, "genres"),
            studios: names(&primary, "production_companies"),
            countries: names(&primary, "production_countries"),
            directors: crew_by_job(&primary, "/credits/crew", "Director"),
            cast: cast_members(&primary, "/credits/cast", "character", 20),
            imdb_id: text(&primary, "imdb_id"),
            poster_path: image_path(&primary, &fallback, "poster_path"),
            backdrop_path: image_path(&primary, &fallback, "backdrop_path"),
        })
    }

    fn episode(&self, id: u64, season: u16, episode: u16) -> Result<ResolvedMedia> {
        let show: Value = self.json(
            &format!("tv/{id}"),
            &[
                ("language", self.config.language.as_str()),
                ("append_to_response", "aggregate_credits"),
            ],
        )?;
        let show_fallback = self.fallback("tv", id);
        let episode_value: Value = self.json(
            &format!("tv/{id}/season/{season}/episode/{episode}"),
            &[("language", self.config.language.as_str())],
        )?;
        let episode_endpoint = format!("tv/{id}/season/{season}/episode/{episode}");
        let episode_fallback: Value = self.optional_fallback(&episode_endpoint);
        let episode_title = text(&episode_value, "name")
            .filter(|value| !value.is_empty())
            .or_else(|| text(&episode_fallback, "name"))
            .unwrap_or_else(|| format!("Episode {episode}"));
        Ok(ResolvedMedia {
            kind: MediaKind::Tv,
            tmdb_id: id,
            item_tmdb_id: episode_value
                .get("id")
                .and_then(Value::as_u64)
                .unwrap_or(id),
            title: text(&show, "name")
                .or_else(|| text(&show_fallback, "name"))
                .context("TMDB TV title is missing")?,
            episode_title: Some(episode_title),
            original_title: text(&show, "original_name"),
            year: text(&show, "first_air_date").and_then(|value| parse_year(&value)),
            season: Some(season),
            episode: Some(episode),
            overview: text(&episode_value, "overview")
                .filter(|value| !value.is_empty())
                .or_else(|| text(&episode_fallback, "overview"))
                .unwrap_or_default(),
            tagline: text(&show, "tagline").or_else(|| text(&show_fallback, "tagline")),
            release_date: text(&episode_value, "air_date"),
            runtime: episode_value.get("runtime").and_then(Value::as_u64),
            rating: episode_value.get("vote_average").and_then(Value::as_f64),
            genres: names(&show, "genres"),
            studios: names(&show, "production_companies"),
            countries: show
                .get("origin_country")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect(),
            directors: crew_by_job(&episode_value, "/crew", "Director"),
            cast: {
                let mut cast = cast_members(&episode_value, "/guest_stars", "character", 20);
                if cast.is_empty() {
                    cast = aggregate_cast_members(&show, 20);
                }
                cast
            },
            imdb_id: None,
            poster_path: text(&episode_value, "still_path")
                .or_else(|| text(&episode_fallback, "still_path"))
                .or_else(|| image_path(&show, &show_fallback, "poster_path")),
            backdrop_path: image_path(&show, &show_fallback, "backdrop_path"),
        })
    }

    fn fallback(&self, kind: &str, id: u64) -> Value {
        if self.config.language == self.config.fallback_language {
            return Value::Null;
        }
        self.optional_fallback(&format!("{kind}/{id}"))
    }

    fn optional_fallback(&self, endpoint: &str) -> Value {
        if self.config.language == self.config.fallback_language {
            return Value::Null;
        }
        match self.json(
            endpoint,
            &[("language", self.config.fallback_language.as_str())],
        ) {
            Ok(value) => value,
            Err(error) => {
                eprintln!(
                    "metadata warning provider=TMDB endpoint={endpoint} fallback_language={} error={error:#}",
                    self.config.fallback_language
                );
                Value::Null
            }
        }
    }

    fn json<T: for<'de> Deserialize<'de>>(
        &self,
        endpoint: &str,
        parameters: &[(&str, &str)],
    ) -> Result<T> {
        let response = self.request(endpoint, parameters)?;
        let bytes = bounded_bytes(response, self.config.max_response_bytes)?;
        serde_json::from_slice(&bytes).context("TMDB returned invalid JSON")
    }

    fn image(&self, path: &str) -> Result<Vec<u8>> {
        let url = format!(
            "{}/{}",
            self.config.image_base_url.trim_end_matches('/'),
            path.trim_start_matches('/')
        );
        let response = self.request_url(&url, &[], false)?;
        bounded_bytes(response, self.config.max_image_bytes)
    }

    fn request(&self, endpoint: &str, parameters: &[(&str, &str)]) -> Result<Response> {
        let url = format!(
            "{}/{}",
            self.config.base_url.trim_end_matches('/'),
            endpoint.trim_start_matches('/')
        );
        self.request_url(&url, parameters, true)
    }

    fn request_url(
        &self,
        url: &str,
        parameters: &[(&str, &str)],
        authenticated: bool,
    ) -> Result<Response> {
        let mut last = None;
        for attempt in 0..=self.config.max_retries {
            let request = self.client.get(url).query(parameters);
            let request = if authenticated {
                request.bearer_auth(&self.token)
            } else {
                request
            };
            match request.send() {
                Ok(response) if response.status().is_success() => return Ok(response),
                Ok(response)
                    if response.status() == StatusCode::TOO_MANY_REQUESTS
                        || response.status().is_server_error() =>
                {
                    last = Some(anyhow::anyhow!("TMDB returned HTTP {}", response.status()));
                }
                Ok(response)
                    if matches!(
                        response.status(),
                        StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN
                    ) =>
                {
                    bail!(
                        "TMDB rejected the API Read Access Token from environment variable {} with HTTP {}; verify the token and rerun `subtrans doctor`",
                        self.config.api_token_env,
                        response.status()
                    )
                }
                Ok(response) => bail!("TMDB returned HTTP {} for {url}", response.status()),
                Err(error) => last = Some(error.into()),
            }
            if attempt < self.config.max_retries {
                thread::sleep(Duration::from_millis(250 * u64::from(attempt + 1)));
            }
        }
        Err(last.unwrap_or_else(|| anyhow::anyhow!("TMDB request failed")))
            .with_context(|| format!("TMDB request failed after retries: {url}"))
    }
}

fn render_nfo(media: &ResolvedMedia) -> String {
    let mut xml = String::from("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n");
    let root = if media.kind == MediaKind::Movie {
        "movie"
    } else {
        "episodedetails"
    };
    xml.push_str(&format!("<{root}>\n"));
    element(
        &mut xml,
        "title",
        media.episode_title.as_deref().unwrap_or(&media.title),
    );
    if media.kind == MediaKind::Tv {
        element(&mut xml, "showtitle", &media.title);
    }
    if let Some(value) = media
        .original_title
        .as_deref()
        .filter(|_| media.kind == MediaKind::Movie)
    {
        element(&mut xml, "originaltitle", value);
    }
    element(&mut xml, "plot", &media.overview);
    if let Some(value) = media.tagline.as_deref() {
        element(&mut xml, "tagline", value);
    }
    if let Some(value) = media.year {
        element(&mut xml, "year", &value.to_string());
    }
    if let Some(value) = media.release_date.as_deref() {
        element(
            &mut xml,
            if media.kind == MediaKind::Movie {
                "premiered"
            } else {
                "aired"
            },
            value,
        );
    }
    if let Some(value) = media.runtime {
        element(&mut xml, "runtime", &value.to_string());
    }
    if let Some(value) = media.rating {
        element(&mut xml, "rating", &format!("{value:.1}"));
    }
    if let Some(value) = media.season {
        element(&mut xml, "season", &value.to_string());
    }
    if let Some(value) = media.episode {
        element(&mut xml, "episode", &value.to_string());
    }
    for value in &media.genres {
        element(&mut xml, "genre", value);
    }
    for value in &media.studios {
        element(&mut xml, "studio", value);
    }
    for value in &media.countries {
        element(&mut xml, "country", value);
    }
    for value in &media.directors {
        element(&mut xml, "director", value);
    }
    for value in &media.cast {
        xml.push_str("  <actor>\n");
        element_indented(&mut xml, "name", &value.name, 4);
        if let Some(role) = value.role.as_deref() {
            element_indented(&mut xml, "role", role, 4);
        }
        xml.push_str("  </actor>\n");
    }
    xml.push_str(&format!(
        "  <uniqueid type=\"tmdb\" default=\"true\">{}</uniqueid>\n",
        media.item_tmdb_id
    ));
    if let Some(value) = media.imdb_id.as_deref() {
        xml.push_str(&format!(
            "  <uniqueid type=\"imdb\">{}</uniqueid>\n",
            escape_xml(value)
        ));
    }
    xml.push_str(&format!("</{root}>\n"));
    xml
}

fn element(xml: &mut String, name: &str, value: &str) {
    xml.push_str(&format!("  <{name}>{}</{name}>\n", escape_xml(value)));
}

fn element_indented(xml: &mut String, name: &str, value: &str, spaces: usize) {
    xml.push_str(&" ".repeat(spaces));
    xml.push_str(&format!("<{name}>{}</{name}>\n", escape_xml(value)));
}

fn escape_xml(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

fn match_score(query: &str, year: Option<u16>, candidate: &SearchResult) -> f32 {
    let titles = [
        candidate.title.as_deref(),
        candidate.name.as_deref(),
        candidate.original_title.as_deref(),
        candidate.original_name.as_deref(),
    ];
    let title_score = titles
        .into_iter()
        .flatten()
        .map(|value| title_similarity(query, value))
        .fold(0.0, f32::max);
    let candidate_year = candidate
        .release_date
        .as_deref()
        .or(candidate.first_air_date.as_deref())
        .and_then(parse_year);
    match (year, candidate_year) {
        (Some(expected), Some(actual)) if expected == actual => (title_score + 0.10).min(1.0),
        (Some(_), Some(_)) => title_score * 0.80,
        _ => title_score,
    }
}

fn title_similarity(left: &str, right: &str) -> f32 {
    let left = normalized_title(left);
    let right = normalized_title(right);
    if left == right {
        return 0.90;
    }
    let left_tokens: HashSet<_> = left.split_whitespace().collect();
    let right_tokens: HashSet<_> = right.split_whitespace().collect();
    if left_tokens.is_empty() || right_tokens.is_empty() {
        return 0.0;
    }
    let intersection = left_tokens.intersection(&right_tokens).count() as f32;
    let union = left_tokens.union(&right_tokens).count() as f32;
    0.85 * intersection / union
}

fn normalized_title(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_alphanumeric() {
                character.to_ascii_lowercase()
            } else {
                ' '
            }
        })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn bounded_bytes(mut response: Response, maximum: usize) -> Result<Vec<u8>> {
    if response
        .content_length()
        .is_some_and(|length| length > maximum as u64)
    {
        bail!("TMDB response exceeds configured size limit of {maximum} bytes");
    }
    let mut bytes = Vec::new();
    response
        .by_ref()
        .take(maximum as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        bail!("TMDB response exceeds configured size limit of {maximum} bytes");
    }
    Ok(bytes)
}

fn validate_jpeg(bytes: &[u8], role: &str) -> Result<()> {
    if bytes.len() < 4 || !bytes.starts_with(&[0xff, 0xd8]) || !bytes.ends_with(&[0xff, 0xd9]) {
        bail!("TMDB {role} response is not a complete JPEG image");
    }
    Ok(())
}

fn image_path(primary: &Value, fallback: &Value, field: &str) -> Option<String> {
    text(primary, field).or_else(|| text(fallback, field))
}

fn text(value: &Value, field: &str) -> Option<String> {
    value
        .get(field)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
}

fn names(value: &Value, field: &str) -> Vec<String> {
    value
        .get(field)
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|item| text(item, "name"))
        .collect()
}

fn crew_by_job(value: &Value, pointer: &str, job: &str) -> Vec<String> {
    value
        .pointer(pointer)
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|person| text(person, "job").as_deref() == Some(job))
        .filter_map(|person| text(person, "name"))
        .collect()
}

fn cast_members(value: &Value, pointer: &str, role_field: &str, limit: usize) -> Vec<CastMember> {
    value
        .pointer(pointer)
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|person| {
            Some(CastMember {
                name: text(person, "name")?,
                role: text(person, role_field),
            })
        })
        .take(limit)
        .collect()
}

fn aggregate_cast_members(value: &Value, limit: usize) -> Vec<CastMember> {
    value
        .pointer("/aggregate_credits/cast")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|person| {
            let role = person
                .get("roles")
                .and_then(Value::as_array)
                .and_then(|roles| roles.first())
                .and_then(|role| text(role, "character"));
            Some(CastMember {
                name: text(person, "name")?,
                role,
            })
        })
        .take(limit)
        .collect()
}

fn parse_year(value: &str) -> Option<u16> {
    value.get(..4)?.parse().ok()
}

fn config_hash(config: &MetadataConfig) -> Result<String> {
    Ok(hash(&serde_json::to_vec(config)?))
}

fn hash(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn video_identity(entry: &FileEntry) -> String {
    #[derive(Serialize)]
    struct Identity<'a> {
        path: &'a str,
        size: u64,
        modified: Option<u64>,
    }
    let modified = entry
        .modified
        .and_then(|value| value.duration_since(UNIX_EPOCH).ok())
        .map(|value| value.as_secs());
    hash(
        &serde_json::to_vec(&Identity {
            path: &entry.path,
            size: entry.size,
            modified,
        })
        .expect("metadata identity serialization cannot fail"),
    )
}

fn incomplete_marker(entries: &[FileEntry], video: &FileEntry, cfg: &Config) -> Option<String> {
    cfg.migration
        .incomplete_marker_extensions
        .iter()
        .map(|value| format!("{}.{}", video.path, value.trim_start_matches('.')))
        .find(|candidate| {
            entries
                .iter()
                .any(|entry| !entry.is_dir && entry.path.eq_ignore_ascii_case(candidate))
        })
}

fn extension(path: &str) -> Option<String> {
    Path::new(path)
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_ascii_lowercase)
}

fn kind_name(kind: MediaKind) -> &'static str {
    match kind {
        MediaKind::Movie => "movie",
        MediaKind::Tv => "tv",
        MediaKind::Unknown => "unknown",
    }
}

fn now_seconds() -> Result<u64> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .context("system clock is before Unix epoch")?
        .as_secs())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_title_and_year_wins() {
        let result = SearchResult {
            id: 1,
            title: Some("Supergirl".into()),
            name: None,
            original_title: None,
            original_name: None,
            release_date: Some("2026-06-01".into()),
            first_air_date: None,
        };
        assert_eq!(match_score("Supergirl", Some(2026), &result), 1.0);
    }

    #[test]
    fn wrong_year_is_penalized() {
        let result = SearchResult {
            id: 1,
            title: Some("Supergirl".into()),
            name: None,
            original_title: None,
            original_name: None,
            release_date: Some("1984-01-01".into()),
            first_air_date: None,
        };
        assert!(match_score("Supergirl", Some(2026), &result) < 0.85);
    }

    #[test]
    fn nfo_escapes_xml() {
        assert_eq!(escape_xml("A & <B>"), "A &amp; &lt;B&gt;");
    }

    #[test]
    fn metadata_override_cannot_silently_change_a_known_media_type() {
        let base = classify_path("Supergirl.2026.2160p.WEB-DL.mkv");
        let decision = MetadataOverride {
            kind: OverrideKind::Tv,
            tmdb_id: 42,
            season: Some(1),
            episode: Some(1),
        };
        let merged = apply_metadata_override(base, &decision);
        assert!(merged.is_pending());
        assert!(
            merged
                .pending_reason
                .as_deref()
                .unwrap()
                .contains("conflicts")
        );
    }
}
