use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::io::Read;
use std::ops::Range;
use std::time::Duration;

use anyhow::{Context, Result, bail};
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::config::{LlmProvider, TranslationConfig};

use super::quality::validate_translation_quality;
use super::srt::{Cue, single_line};

const PROMPT_VERSION: &str = "subtrans-translation-context-json-v3";

#[derive(Debug, Serialize)]
struct PromptLine<'a> {
    index: u32,
    text: &'a str,
    translate: bool,
}

#[derive(Debug, Serialize)]
struct AuditLine<'a> {
    index: u32,
    source: &'a str,
    translation: &'a str,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct TranslationEnvelope {
    translations: Vec<TranslatedLine>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ConsistencyEnvelope {
    corrections: Vec<TranslatedLine>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct TranslatedLine {
    index: u32,
    text: String,
}

pub fn translate(cues: &[Cue], cfg: &TranslationConfig) -> Result<Vec<Cue>> {
    if cues.is_empty() || cfg.batch_size == 0 || cfg.max_batch_chars == 0 {
        bail!("source cues and translation batch limits must be non-empty");
    }
    let client = Client::builder()
        .timeout(Duration::from_secs(cfg.timeout_seconds))
        .build()?;
    let api_key = cfg.api_key()?;
    let mut translated = BTreeMap::new();

    for range in batch_ranges(cues, cfg.batch_size, cfg.max_batch_chars) {
        translate_range_adaptive(
            &client,
            api_key.as_deref(),
            cues,
            range,
            cfg,
            &mut translated,
        )?;
    }
    if cfg.consistency_check && cues.len() > 1 {
        audit_consistency(&client, api_key.as_deref(), cues, &mut translated, cfg)?;
    }
    let output = render(cues, &translated, cfg.bilingual)?;
    validate_translation_quality(
        cues,
        &output,
        &cfg.target_language,
        cfg.min_target_script_ratio,
    )?;
    Ok(output)
}

fn batch_ranges(cues: &[Cue], max_count: usize, max_chars: usize) -> Vec<Range<usize>> {
    let mut output = Vec::new();
    let mut start = 0usize;
    while start < cues.len() {
        let mut end = start;
        let mut chars = 0usize;
        while end < cues.len() && end - start < max_count {
            let next = cues[end].text.chars().count();
            if end > start && chars.saturating_add(next) > max_chars {
                break;
            }
            chars = chars.saturating_add(next);
            end += 1;
            if chars >= max_chars {
                break;
            }
        }
        output.push(start..end.max(start + 1));
        start = end.max(start + 1);
    }
    output
}

fn translate_range_adaptive(
    client: &Client,
    api_key: Option<&str>,
    cues: &[Cue],
    initial: Range<usize>,
    cfg: &TranslationConfig,
    translated: &mut BTreeMap<u32, String>,
) -> Result<()> {
    let mut pending = VecDeque::from([initial]);
    while let Some(range) = pending.pop_front() {
        let prompt = build_prompt(cues, range.clone(), cfg)?;
        let expected = &cues[range.clone()];
        let result = retry(cfg.max_retries, || {
            request(client, cfg, api_key, &prompt)
                .and_then(|response| parse_aligned(&response, expected))
        });
        match result {
            Ok(values) => {
                for (index, text) in values {
                    if translated.insert(index, text).is_some() {
                        bail!("translation batch produced duplicate cue index {index}");
                    }
                }
            }
            Err(_) if range.len() >= cfg.min_batch_size.saturating_mul(2) => {
                let midpoint = range.start + range.len() / 2;
                pending.push_front(midpoint..range.end);
                pending.push_front(range.start..midpoint);
            }
            Err(error) => {
                return Err(error).with_context(|| {
                    format!(
                        "translation batch {}..{} failed strict checks and cannot be split without going below the configured minimum",
                        range.start, range.end
                    )
                });
            }
        }
    }
    Ok(())
}

fn retry<T>(max_retries: u32, mut operation: impl FnMut() -> Result<T>) -> Result<T> {
    let mut last_error = None;
    for attempt in 0..=max_retries {
        match operation() {
            Ok(value) => return Ok(value),
            Err(error) => {
                last_error = Some(error);
                if attempt < max_retries {
                    std::thread::sleep(Duration::from_millis(
                        250_u64.saturating_mul(1_u64 << attempt.min(4)),
                    ));
                }
            }
        }
    }
    Err(last_error.expect("retry loop executes at least once"))
}

pub fn parse_aligned(response: &str, expected: &[Cue]) -> Result<BTreeMap<u32, String>> {
    let envelope: TranslationEnvelope = serde_json::from_str(response.trim())
        .context("translation response is not the required JSON object")?;
    if envelope.translations.len() != expected.len() {
        bail!("translation response item count differs from request");
    }
    let expected_indices: BTreeSet<u32> = expected.iter().map(|cue| cue.index).collect();
    let mut output = BTreeMap::new();
    for item in envelope.translations {
        if !expected_indices.contains(&item.index) {
            bail!(
                "translation response contains unexpected index {}",
                item.index
            );
        }
        let text = single_line(&item.text);
        if text.is_empty() || output.insert(item.index, text).is_some() {
            bail!(
                "translation response has an empty or duplicate index {}",
                item.index
            );
        }
    }
    if output.keys().copied().collect::<BTreeSet<_>>() != expected_indices {
        bail!("translation response is missing cue indices");
    }
    Ok(output)
}

pub fn render(
    source: &[Cue],
    translations: &BTreeMap<u32, String>,
    bilingual: bool,
) -> Result<Vec<Cue>> {
    let mut output = Vec::with_capacity(source.len());
    for cue in source {
        let target = single_line(
            translations
                .get(&cue.index)
                .with_context(|| format!("missing translation for cue {}", cue.index))?,
        );
        if target.is_empty() {
            bail!("empty translation for cue {}", cue.index);
        }
        let original = single_line(&cue.text);
        output.push(Cue {
            index: cue.index,
            start_ms: cue.start_ms,
            end_ms: cue.end_ms,
            text: if bilingual {
                format!("{target}\n{original}")
            } else {
                target
            },
        });
    }
    validate_output(source, &output, bilingual)?;
    Ok(output)
}

pub fn validate_output(source: &[Cue], output: &[Cue], bilingual: bool) -> Result<()> {
    if source.len() != output.len() {
        bail!("translated subtitle cue count differs from source");
    }
    for (source_cue, output_cue) in source.iter().zip(output) {
        if source_cue.index != output_cue.index
            || source_cue.start_ms != output_cue.start_ms
            || source_cue.end_ms != output_cue.end_ms
        {
            bail!(
                "translated cue {} changed alignment or timing",
                source_cue.index
            );
        }
        let line_count = output_cue
            .text
            .lines()
            .map(str::trim)
            .filter(|line| !line.is_empty())
            .count();
        if line_count != if bilingual { 2 } else { 1 } {
            bail!(
                "translated cue {} has an invalid line structure",
                source_cue.index
            );
        }
    }
    Ok(())
}

pub fn prompt_version() -> &'static str {
    PROMPT_VERSION
}

fn build_prompt(cues: &[Cue], core: Range<usize>, cfg: &TranslationConfig) -> Result<String> {
    let context_start = core.start.saturating_sub(cfg.context_cues);
    let context_end = core.end.saturating_add(cfg.context_cues).min(cues.len());
    let lines: Vec<PromptLine<'_>> = cues[context_start..context_end]
        .iter()
        .enumerate()
        .map(|(offset, cue)| PromptLine {
            index: cue.index,
            text: &cue.text,
            translate: (context_start + offset) >= core.start
                && (context_start + offset) < core.end,
        })
        .collect();
    Ok(format!(
        "Protocol: {PROMPT_VERSION}. You are a professional {} ({}) to {} ({}) translator. \
         Accurately convey meaning and nuances while following {} grammar, vocabulary, and cultural conventions. \
         Input items with translate=false are read-only neighboring context: use them for pronouns, names, tone, and continuity, \
         but do not return them. Return exactly one JSON object with shape \
         {{\"translations\":[{{\"index\":1,\"text\":\"translation\"}}]}} containing every translate=true index exactly once. \
         Produce only {} translations, with no markdown, explanations, extra keys, or untranslated source text. \
         Please translate the following {} subtitle cues into {}:\n\n{}",
        cfg.source_language,
        cfg.source_language_code,
        cfg.target_language,
        cfg.target_language_code,
        cfg.target_language,
        cfg.target_language,
        cfg.source_language,
        cfg.target_language,
        serde_json::to_string(&lines)?
    ))
}

fn audit_consistency(
    client: &Client,
    api_key: Option<&str>,
    cues: &[Cue],
    translations: &mut BTreeMap<u32, String>,
    cfg: &TranslationConfig,
) -> Result<()> {
    let characters = cues.iter().try_fold(0usize, |total, cue| {
        let translation = translations
            .get(&cue.index)
            .with_context(|| format!("missing translation for consistency cue {}", cue.index))?;
        Ok::<usize, anyhow::Error>(
            total
                .saturating_add(cue.text.chars().count())
                .saturating_add(translation.chars().count()),
        )
    })?;
    if characters > cfg.consistency_max_chars {
        bail!(
            "translation consistency input has {characters} characters, exceeding configured limit {}",
            cfg.consistency_max_chars
        );
    }
    let lines: Vec<AuditLine<'_>> = cues
        .iter()
        .map(|cue| {
            Ok(AuditLine {
                index: cue.index,
                source: &cue.text,
                translation: translations
                    .get(&cue.index)
                    .context("translation disappeared before consistency audit")?,
            })
        })
        .collect::<Result<_>>()?;
    let prompt = format!(
        "Protocol: {PROMPT_VERSION}-consistency. You are a professional subtitle translation editor for {} ({}) to {} ({}). \
         Review the complete subtitle for inconsistent character names, places, titles, terminology, pronouns, register, and recurring phrases. \
         Do not rewrite lines that are already correct. Return exactly one JSON object \
         {{\"corrections\":[{{\"index\":1,\"text\":\"corrected translation\"}}]}}. \
         Use an empty corrections array when no change is needed. Each text must contain only the corrected target-language subtitle, never the source. \
         Include only existing indices, with no markdown, reasons, or extra keys.\n\n{}",
        cfg.source_language,
        cfg.source_language_code,
        cfg.target_language,
        cfg.target_language_code,
        serde_json::to_string(&lines)?
    );
    let expected: BTreeSet<u32> = cues.iter().map(|cue| cue.index).collect();
    let corrections = retry(cfg.max_retries, || {
        request(client, cfg, api_key, &prompt)
            .and_then(|response| parse_consistency(&response, &expected))
    })
    .context("translation consistency audit failed strict checks")?;
    translations.extend(corrections);
    Ok(())
}

fn parse_consistency(response: &str, expected: &BTreeSet<u32>) -> Result<BTreeMap<u32, String>> {
    let envelope: ConsistencyEnvelope = serde_json::from_str(response.trim())
        .context("consistency response is not the required JSON object")?;
    let mut corrections = BTreeMap::new();
    for item in envelope.corrections {
        if !expected.contains(&item.index) {
            bail!(
                "consistency response contains unexpected index {}",
                item.index
            );
        }
        let text = single_line(&item.text);
        if text.is_empty() || corrections.insert(item.index, text).is_some() {
            bail!(
                "consistency response has an empty or duplicate index {}",
                item.index
            );
        }
    }
    Ok(corrections)
}

fn request(
    client: &Client,
    cfg: &TranslationConfig,
    api_key: Option<&str>,
    prompt: &str,
) -> Result<String> {
    let (url, body, response_path): (String, Value, &[&str]) = match &cfg.provider {
        LlmProvider::Ollama => (
            endpoint(&cfg.base_url, "api/generate"),
            json!({
                "model": cfg.model,
                "prompt": prompt,
                "stream": false,
                "format": "json",
                "keep_alive": "10m",
                "options": { "temperature": 0.0 }
            }),
            &["response"],
        ),
        LlmProvider::OpenaiCompatible => (
            endpoint(&cfg.base_url, "chat/completions"),
            json!({
                "model": cfg.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "response_format": {"type": "json_object"}
            }),
            &["choices", "0", "message", "content"],
        ),
    };
    let mut request = client.post(url).json(&body);
    if let Some(key) = api_key {
        request = request.bearer_auth(key);
    }
    let response = request.send()?.error_for_status()?;
    let mut bytes = Vec::new();
    response
        .take(cfg.max_response_bytes as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > cfg.max_response_bytes {
        bail!("translation service response exceeds configured size limit");
    }
    let response: Value =
        serde_json::from_slice(&bytes).context("translation service returned invalid JSON")?;
    value_at(&response, response_path)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .context("translation service response is missing generated content")
}

fn endpoint(base: &str, suffix: &str) -> String {
    let trimmed = base.trim_end_matches('/');
    if trimmed.ends_with(suffix) {
        trimmed.to_owned()
    } else {
        format!("{trimmed}/{suffix}")
    }
}

fn value_at<'a>(mut value: &'a Value, path: &[&str]) -> Option<&'a Value> {
    for component in path {
        value = if let Ok(index) = component.parse::<usize>() {
            value.as_array()?.get(index)?
        } else {
            value.get(*component)?
        };
    }
    Some(value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::TranslationConfig;

    fn cues(count: usize) -> Vec<Cue> {
        (1..=count)
            .map(|index| Cue {
                index: index as u32,
                start_ms: index as u64 * 1_000,
                end_ms: index as u64 * 1_000 + 900,
                text: format!("Line {index}"),
            })
            .collect()
    }

    fn config() -> TranslationConfig {
        toml::from_str(
            r#"
provider = "ollama"
base_url = "http://127.0.0.1:11434"
model = "translategemma:12b"
source_language = "English"
source_language_code = "en"
target_language = "Simplified Chinese"
target_language_code = "zh-CN"
"#,
        )
        .unwrap()
    }

    #[test]
    fn batching_keeps_the_configured_maximum() {
        let values = cues(85);
        assert_eq!(batch_ranges(&values, 80, 8_000), vec![0..80, 80..85]);
    }

    #[test]
    fn translation_prompt_marks_neighboring_context_as_read_only() {
        let values = cues(8);
        let mut cfg = config();
        cfg.context_cues = 2;
        let prompt = build_prompt(&values, 2..6, &cfg).unwrap();
        assert!(prompt.contains("professional English (en) to Simplified Chinese (zh-CN)"));
        assert!(prompt.contains("\"index\":1,\"text\":\"Line 1\",\"translate\":false"));
        assert!(prompt.contains("\"index\":3,\"text\":\"Line 3\",\"translate\":true"));
        assert!(prompt.contains("\n\n["));
    }

    #[test]
    fn consistency_response_only_accepts_known_unique_indices() {
        let expected = BTreeSet::from([1, 2]);
        let corrections = parse_consistency(
            r#"{"corrections":[{"index":2,"text":"修正译文"}]}"#,
            &expected,
        )
        .unwrap();
        assert_eq!(corrections.get(&2).map(String::as_str), Some("修正译文"));
        assert!(parse_consistency(r#"{"corrections":[]}"#, &expected).is_ok());
        assert!(
            parse_consistency(r#"{"corrections":[{"index":3,"text":"越界"}]}"#, &expected).is_err()
        );
        assert!(
            parse_consistency(
                r#"{"corrections":[{"index":1,"text":"甲"},{"index":1,"text":"乙"}]}"#,
                &expected
            )
            .is_err()
        );
    }
}
