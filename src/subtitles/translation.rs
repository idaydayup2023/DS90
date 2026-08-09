use std::collections::{BTreeMap, BTreeSet};
use std::io::Read;
use std::time::Duration;

use anyhow::{Context, Result, bail};
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::config::{LlmProvider, TranslationConfig};

use super::quality::validate_translation_quality;
use super::srt::{Cue, single_line};

const PROMPT_VERSION: &str = "subtrans-translation-json-v2";

#[derive(Debug, Serialize)]
struct PromptLine<'a> {
    index: u32,
    text: &'a str,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct TranslationEnvelope {
    translations: Vec<TranslatedLine>,
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

    for batch in batches(cues, cfg.batch_size, cfg.max_batch_chars) {
        let prompt = build_prompt(batch, cfg)?;
        let mut last_error = None;
        for attempt in 0..=cfg.max_retries {
            match request(&client, cfg, api_key.as_deref(), &prompt)
                .and_then(|response| parse_aligned(&response, batch))
            {
                Ok(values) => {
                    translated.extend(values);
                    last_error = None;
                    break;
                }
                Err(error) => {
                    last_error = Some(error);
                    if attempt < cfg.max_retries {
                        std::thread::sleep(Duration::from_millis(
                            250_u64.saturating_mul(1_u64 << attempt.min(4)),
                        ));
                    }
                }
            }
        }
        if let Some(error) = last_error {
            return Err(error).context("translation batch failed strict alignment checks");
        }
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

fn batches(cues: &[Cue], max_count: usize, max_chars: usize) -> Vec<&[Cue]> {
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
        output.push(&cues[start..end.max(start + 1)]);
        start = end.max(start + 1);
    }
    output
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

fn build_prompt(cues: &[Cue], cfg: &TranslationConfig) -> Result<String> {
    let lines: Vec<PromptLine<'_>> = cues
        .iter()
        .map(|cue| PromptLine {
            index: cue.index,
            text: &cue.text,
        })
        .collect();
    Ok(format!(
        "Protocol: {PROMPT_VERSION}. Translate from {} to {}. Return exactly one JSON object with shape \
         {{\"translations\":[{{\"index\":1,\"text\":\"translation\"}}]}}. Preserve each input index exactly once, \
         emit no markdown or extra keys, and never copy untranslated source text. Input: {}",
        cfg.source_language,
        cfg.target_language,
        serde_json::to_string(&lines)?
    ))
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
