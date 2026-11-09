//! Content-addressed cache of raw model responses for the subtitles engine.
//!
//! Before 2026-11-09 the engine held translations only in memory:
//! [`super::translation::translate`] accumulated cues and only the final
//! manifest hit disk, so a run killed half-way through re-burned every cue
//! that had not been published yet. On a 14-title batch one lost session cost
//! roughly 1,300 cues of model time. With `translation.cache_dir` configured,
//! every accepted model response is persisted as soon as it parses, so a
//! restart replays everything already answered and burns only the requests
//! that were in flight when the process died.
//!
//! The key is `sha256(provider ‖ base_url ‖ model ‖ prompt)` with every part
//! length-prefixed so neighbouring parts cannot shift across the boundary. The
//! endpoint and the model name are part of the key on purpose: a litellm
//! deployment repointed at a different backend version must not answer from
//! entries produced by the previous one, and a silently stale translation is
//! far worse than the model time a miss wastes.
//!
//! A cache is an optimisation, never an authority. Every entry read back goes
//! through the same strict parser as a live response (the caller supplies the
//! `accept` predicate); a payload that no longer satisfies it is dropped
//! instead of trusted, and nothing is written before it satisfies it too.
//! With `cache_dir` unset (the default) this module performs no filesystem
//! access at all and the engine behaves exactly as the version-3 baseline.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result};
use sha2::{Digest, Sha256};

use crate::config::{LlmProvider, TranslationConfig};

/// Domain separator mixed into every key, so a future change of the payload
/// format (or of the parts that make up a key) cannot resurrect old entries.
const KEY_DOMAIN: &str = "ds90-resp-cache-v1";

/// Extension of a cache entry on disk. The file holds the raw model response
/// byte for byte, so a hit reproduces exactly what the service returned.
const ENTRY_SUFFIX: &str = "json";

static HITS: AtomicU64 = AtomicU64::new(0);
static MISSES: AtomicU64 = AtomicU64::new(0);
static WRITES: AtomicU64 = AtomicU64::new(0);
static EVICTIONS: AtomicU64 = AtomicU64::new(0);
static WRITE_FAILURES: AtomicU64 = AtomicU64::new(0);

/// Counting of cache activity for the process lifetime. The counters are
/// process-wide rather than per-`ResponseCache` because a run builds one cache
/// per request yet still has to report a single line per video.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct CacheCounters {
    pub hits: u64,
    pub misses: u64,
    pub writes: u64,
    pub evictions: u64,
    pub write_failures: u64,
}

pub fn counters() -> CacheCounters {
    CacheCounters {
        hits: HITS.load(Ordering::Relaxed),
        misses: MISSES.load(Ordering::Relaxed),
        writes: WRITES.load(Ordering::Relaxed),
        evictions: EVICTIONS.load(Ordering::Relaxed),
        write_failures: WRITE_FAILURES.load(Ordering::Relaxed),
    }
}

/// One-line rendering of the counters for the run log, or `None` when no cache
/// is configured, so a disabled run keeps the exact baseline log output.
pub fn summary_line(dir: Option<&Path>) -> Option<String> {
    let dir = dir?;
    let counters = counters();
    Some(format!(
        "response_cache dir={} hits={} misses={} writes={} evictions={} write_failures={}",
        dir.display(),
        counters.hits,
        counters.misses,
        counters.writes,
        counters.evictions,
        counters.write_failures
    ))
}

/// Handles one configured cache directory. Cheap to build; `new` is called per
/// request so a configuration change takes effect without restarting anything.
#[derive(Debug, Clone, Default)]
pub struct ResponseCache {
    dir: Option<PathBuf>,
}

impl ResponseCache {
    /// Bind to `translation.cache_dir`, creating the directory when it is set.
    /// A cache that cannot be created is disabled for the run with a warning
    /// rather than a failure: losing the speed-up must never fail a
    /// translation that would otherwise succeed.
    pub fn new(cfg: &TranslationConfig) -> Self {
        let dir = cfg
            .cache_dir
            .clone()
            .map(|dir| expand_user_dir(&dir))
            .filter(|dir| !dir.as_os_str().is_empty());
        if let Some(dir) = dir.as_ref()
            && let Err(error) = fs::create_dir_all(dir)
        {
            eprintln!(
                "translation response_cache disabled dir={} error={error:#}",
                dir.display()
            );
            return Self::default();
        }
        Self { dir }
    }

    pub fn disabled(&self) -> bool {
        self.dir.is_none()
    }

    pub fn dir(&self) -> Option<&Path> {
        self.dir.as_deref()
    }

    /// Key for one request, or `None` when no cache is configured.
    pub fn key(&self, cfg: &TranslationConfig, model: &str, prompt: &str) -> Option<String> {
        if self.disabled() {
            return None;
        }
        Some(response_key(&cfg.provider, &cfg.base_url, model, prompt))
    }

    pub fn path_for(&self, key: &str) -> Option<PathBuf> {
        Some(self.dir()?.join(format!("{key}.{ENTRY_SUFFIX}")))
    }

    /// Read a stored response. An entry that is missing, unreadable, or not
    /// valid UTF-8 counts as a miss: the caller then asks the model again.
    pub fn get(&self, key: &str) -> Option<String> {
        let path = self.path_for(key)?;
        let bytes = match fs::read(&path) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                MISSES.fetch_add(1, Ordering::Relaxed);
                return None;
            }
            Err(error) => {
                MISSES.fetch_add(1, Ordering::Relaxed);
                eprintln!(
                    "translation response_cache read_failed path={} error={error:#}",
                    path.display()
                );
                return None;
            }
        };
        match String::from_utf8(bytes) {
            Ok(text) => {
                HITS.fetch_add(1, Ordering::Relaxed);
                Some(text)
            }
            Err(_) => {
                MISSES.fetch_add(1, Ordering::Relaxed);
                eprintln!(
                    "translation response_cache entry_not_utf8 path={} evicting",
                    path.display()
                );
                self.evict(key);
                None
            }
        }
    }

    /// Persist an accepted response atomically: write a unique temporary file,
    /// flush it, then rename. Concurrent runs may write the same key with the
    /// same bytes; the last rename wins and the content is identical either
    /// way. Failures are logged and swallowed for the same reason `new`
    /// swallows them: a cache that cannot be written must not fail the run.
    pub fn put(&self, key: &str, response: &str) {
        let Some(path) = self.path_for(key) else {
            return;
        };
        if let Some(Err(error)) = path.parent().map(fs::create_dir_all) {
            record_write_failure(&path, &error);
            return;
        }
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|elapsed| elapsed.as_nanos())
            .unwrap_or_default();
        let temp = path.with_file_name(format!(".{key}.{}.{stamp}.tmp", std::process::id()));
        let written = (|| -> Result<()> {
            let mut file = fs::File::create(&temp)
                .with_context(|| format!("cannot create cache entry {}", temp.display()))?;
            file.write_all(response.as_bytes())?;
            file.flush()?;
            fs::rename(&temp, &path)
                .with_context(|| format!("cannot publish cache entry {}", path.display()))?;
            Ok(())
        })();
        if let Err(error) = written {
            let _ = fs::remove_file(&temp);
            record_write_failure(&path, &error);
            return;
        }
        WRITES.fetch_add(1, Ordering::Relaxed);
    }

    /// Forget an entry. Used when a stored response no longer satisfies the
    /// strict parser, so a stale or tampered entry cannot pin a batch.
    pub fn evict(&self, key: &str) {
        let Some(path) = self.path_for(key) else {
            return;
        };
        match fs::remove_file(&path) {
            Ok(()) => {
                EVICTIONS.fetch_add(1, Ordering::Relaxed);
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => eprintln!(
                "translation response_cache evict_failed path={} error={error:#}",
                path.display()
            ),
        }
    }
}

fn record_write_failure(path: &Path, error: &dyn std::fmt::Display) {
    WRITE_FAILURES.fetch_add(1, Ordering::Relaxed);
    eprintln!(
        "translation response_cache write_failed path={} error={error:#}",
        path.display()
    );
}

/// `sha256(provider ‖ base_url ‖ model ‖ prompt)` over length-prefixed parts.
pub fn response_key(provider: &LlmProvider, base_url: &str, model: &str, prompt: &str) -> String {
    let mut digest = Sha256::new();
    for part in [
        KEY_DOMAIN.as_bytes(),
        provider_name(provider).as_bytes(),
        base_url.as_bytes(),
        model.as_bytes(),
        prompt.as_bytes(),
    ] {
        digest.update((part.len() as u64).to_le_bytes());
        digest.update(part);
    }
    hex::encode(digest.finalize())
}

fn provider_name(provider: &LlmProvider) -> String {
    match provider {
        LlmProvider::Ollama => "ollama".to_owned(),
        LlmProvider::OpenaiCompatible => "openai_compatible".to_owned(),
    }
}

/// Keep a `~`-prefixed `cache_dir` anchored where the operator meant it.
/// Anything else is used verbatim, so a relative path keeps the ordinary
/// "relative to the working directory" meaning every other configuration path
/// has.
fn expand_user_dir(dir: &Path) -> PathBuf {
    let text = dir.to_string_lossy();
    let relative = match text.as_ref() {
        "~" => Some(""),
        other => other.strip_prefix("~/"),
    };
    match (relative, std::env::var_os("HOME")) {
        (Some(relative), Some(home)) => PathBuf::from(home).join(relative),
        _ => dir.to_path_buf(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(cache_dir: Option<&str>) -> TranslationConfig {
        toml::from_str(&format!(
            r#"
provider = "ollama"
base_url = "http://127.0.0.1:11434"
model = "translategemma:4b"
source_language = "English"
source_language_code = "en"
target_language = "Simplified Chinese"
target_language_code = "zh-CN"
{}"#,
            cache_dir
                .map(|dir| format!("cache_dir = \"{dir}\"\n"))
                .unwrap_or_default()
        ))
        .unwrap()
    }

    fn ollama() -> LlmProvider {
        LlmProvider::Ollama
    }

    #[test]
    fn key_covers_every_part_that_selects_the_answer() {
        let base = response_key(
            &ollama(),
            "http://127.0.0.1:11434",
            "translategemma:4b",
            "P",
        );
        // Same inputs, same key: a restart must find its own entries.
        assert_eq!(
            base,
            response_key(
                &ollama(),
                "http://127.0.0.1:11434",
                "translategemma:4b",
                "P"
            )
        );
        // Repointing the endpoint or swapping the model must never replay an
        // entry produced somewhere else.
        assert_ne!(
            base,
            response_key(
                &ollama(),
                "http://127.0.0.1:8888/v1",
                "translategemma:4b",
                "P"
            )
        );
        assert_ne!(
            base,
            response_key(&ollama(), "http://127.0.0.1:11434", "qwen3:8b", "P")
        );
        assert_ne!(
            base,
            response_key(
                &LlmProvider::OpenaiCompatible,
                "http://127.0.0.1:11434",
                "translategemma:4b",
                "P"
            )
        );
        assert_ne!(
            base,
            response_key(
                &ollama(),
                "http://127.0.0.1:11434",
                "translategemma:4b",
                "Q"
            )
        );
    }

    #[test]
    fn key_matches_the_vector_the_selftest_recomputes() {
        // Independent reimplementation (tools/l2_resp_cache_selftest_20261109.py)
        // computes these same digests in Python. If the derivation changes, both
        // this test and that check go red, so the on-disk identity cannot drift
        // silently between the engine and the tooling that inspects it.
        assert_eq!(
            response_key(
                &ollama(),
                "http://127.0.0.1:11434",
                "translategemma:4b",
                "PROMPT-VECTOR-1"
            ),
            "ffa862f185ca0a66e964d7cb3af9e5ebee79c84cc7c030b5e7932c3ce06f7634"
        );
        assert_eq!(
            response_key(
                &LlmProvider::OpenaiCompatible,
                "https://litellm.invalid/v1",
                "Qwen3.8-Flash-Next",
                "提示词"
            ),
            "41ca4a55257fa41f7396c9ae2c7f8c4f957859133c254f23e000f9dc2fa23c6d"
        );
    }

    #[test]
    fn key_parts_cannot_shift_across_the_boundary() {
        // Without the length prefixes these two would hash identically.
        let first = response_key(&ollama(), "http://host/mode", "l", "prompt");
        let second = response_key(&ollama(), "http://host", "model", "prompt");
        assert_ne!(first, second);
    }

    #[test]
    fn entries_round_trip_and_evict() {
        let root = tempfile::tempdir().unwrap();
        let cache = ResponseCache {
            dir: Some(root.path().to_path_buf()),
        };
        let key = response_key(&ollama(), "http://h", "m", "p");
        assert!(cache.get(&key).is_none());
        cache.put(&key, "{\"translations\":[]}");
        assert_eq!(cache.get(&key).as_deref(), Some("{\"translations\":[]}"));
        cache.evict(&key);
        assert!(cache.get(&key).is_none());
    }

    #[test]
    fn a_disabled_cache_never_touches_the_filesystem() {
        let cache = ResponseCache::new(&config(None));
        assert!(cache.disabled());
        assert!(cache.get("deadbeef").is_none());
        assert!(cache.path_for("deadbeef").is_none());
        cache.put("deadbeef", "payload");
        assert!(cache.disabled());
    }

    #[test]
    fn a_write_failure_is_reported_but_never_fatal() {
        let root = tempfile::tempdir().unwrap();
        // A directory sitting where the entry file belongs makes the rename
        // fail; the run must simply continue without the entry.
        let key = "cafebabe";
        fs::create_dir_all(root.path().join(format!("{key}.json"))).unwrap();
        let cache = ResponseCache {
            dir: Some(root.path().to_path_buf()),
        };
        cache.put(key, "payload");
        assert!(cache.get(key).is_none());
    }

    #[test]
    fn cache_dir_does_not_reach_the_serialized_configuration() {
        // `cache_key` hashes the serialized translation section, so this knob
        // must not appear in it: enabling a cache cannot invalidate every
        // published manifest the way a model or prompt bump does.
        let with = config(Some("/tmp/ds90-resp-cache-test"));
        let without = config(None);
        assert_eq!(
            serde_json::to_vec(&without).unwrap(),
            serde_json::to_vec(&with).unwrap()
        );
        assert_eq!(
            with.cache_dir.unwrap().display().to_string(),
            "/tmp/ds90-resp-cache-test"
        );
    }
}
