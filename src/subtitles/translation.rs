use std::borrow::Cow;
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

const PROMPT_VERSION: &str = "subtrans-translation-cue-binding-json-v5";

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

#[derive(Debug, Serialize)]
struct AlignmentLine<'a> {
    index: u32,
    source: &'a str,
    translation: &'a str,
    review: bool,
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

#[derive(Debug)]
struct AlignmentTask {
    positions: Vec<usize>,
    attempts: u32,
}

#[derive(Debug, Default)]
struct AlignmentOutcome {
    corrected: usize,
    english_fallback: BTreeSet<u32>,
    unresolved: usize,
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
        println!(
            "translation progress translated={}/{}",
            translated.len(),
            cues.len()
        );
    }
    if cfg.consistency_check && cues.len() > 1 {
        println!("translation consistency_check cues={}", cues.len());
        match audit_consistency(&client, api_key.as_deref(), cues, &mut translated, cfg) {
            Ok(corrected) => println!("translation consistency_check corrected={corrected}"),
            Err(error) => eprintln!(
                "translation consistency_check unresolved=true action=continue_without_consistency_corrections error={error:#}"
            ),
        }
    }
    let mut english_fallback = BTreeSet::new();
    if cfg.alignment_check {
        println!("translation alignment_check cues={}", cues.len());
        let outcome = audit_alignment(&client, api_key.as_deref(), cues, &mut translated, cfg)?;
        println!(
            "translation alignment_check corrected={} english_fallback={} unresolved={}",
            outcome.corrected,
            outcome.english_fallback.len(),
            outcome.unresolved
        );
        english_fallback = outcome.english_fallback;
    }
    let output = render_with_fallback(cues, &translated, cfg.bilingual, &english_fallback)?;
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
        let context = prompt_context_range(range.clone(), cfg.context_cues);
        let ignored_context_indices: BTreeSet<u32> = cues[context]
            .iter()
            .filter(|cue| !expected.iter().any(|item| item.index == cue.index))
            .map(|cue| cue.index)
            .collect();
        // Retry transport/service failures, but split deterministic malformed
        // model output immediately instead of asking for the same bad JSON.
        let result = retry(cfg.max_retries, || {
            request(
                client,
                cfg,
                api_key,
                &cfg.model,
                &prompt,
                cfg.max_output_tokens,
            )
        })
        .and_then(|response| parse_valid_indices(&response, expected, &ignored_context_indices))
        .and_then(|values| {
            if values.is_empty() {
                bail!("translation response contains no requested cue indices");
            }
            Ok(values)
        });
        match result {
            Ok(values) => {
                let missing: Vec<Range<usize>> = range
                    .clone()
                    .filter(|position| !values.contains_key(&cues[*position].index))
                    .map(|position| position..position + 1)
                    .collect();
                for (index, text) in values {
                    if translated.insert(index, text).is_some() {
                        bail!("translation batch produced duplicate cue index {index}");
                    }
                }
                // TranslateGemma can occasionally collapse repeated short cues
                // even though their indices differ. Keep every valid item and
                // repair only omitted indices with the same neighboring context.
                for missing_range in missing.into_iter().rev() {
                    pending.push_front(missing_range);
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
    let output = parse_valid_indices(response, expected, &BTreeSet::new())?;
    if output.len() != expected.len() {
        bail!(
            "translation response item count differs from request: expected {}, received {}",
            expected.len(),
            output.len()
        );
    }
    Ok(output)
}

fn parse_valid_indices(
    response: &str,
    expected: &[Cue],
    ignored_context_indices: &BTreeSet<u32>,
) -> Result<BTreeMap<u32, String>> {
    let normalized = normalize_known_json_keys(response);
    let envelope: TranslationEnvelope = serde_json::from_str(normalized.trim())
        .context("translation response is not the required JSON object")?;
    let expected_indices: BTreeSet<u32> = expected.iter().map(|cue| cue.index).collect();
    let mut output = BTreeMap::new();
    for item in envelope.translations {
        if !expected_indices.contains(&item.index) {
            if ignored_context_indices.contains(&item.index) {
                continue;
            }
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
    Ok(output)
}

pub fn render(
    source: &[Cue],
    translations: &BTreeMap<u32, String>,
    bilingual: bool,
) -> Result<Vec<Cue>> {
    render_with_fallback(source, translations, bilingual, &BTreeSet::new())
}

fn render_with_fallback(
    source: &[Cue],
    translations: &BTreeMap<u32, String>,
    bilingual: bool,
    english_fallback: &BTreeSet<u32>,
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
            text: if english_fallback.contains(&cue.index) {
                original
            } else if bilingual {
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
        let deliberate_english_fallback = bilingual
            && line_count == 1
            && single_line(&output_cue.text).eq_ignore_ascii_case(&single_line(&source_cue.text));
        if !deliberate_english_fallback && line_count != if bilingual { 2 } else { 1 } {
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
    let example_index = cues
        .get(core.start)
        .context("translation prompt core range starts outside source cues")?
        .index;
    let context = prompt_context_range(core.clone(), cfg.context_cues);
    let context_start = context.start;
    let context_end = context.end;
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
         but never copy, translate, complete, or move any of their content into another item. Every index is an indivisible source-to-target binding: \
         each returned text must translate only the source text at that same index. Never merge adjacent cues, split one cue across indices, shift dialogue, \
         or borrow words from a previous or next cue. If a source cue is a sentence fragment, preserve it as a fragment instead of completing it from context. \
         Preserve every speaker and clause present inside that cue. Return exactly one JSON object with shape \
         {{\"translations\":[{{\"index\":{example_index},\"text\":\"translation\"}}]}} containing every translate=true index exactly once. \
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

fn prompt_context_range(core: Range<usize>, context_cues: usize) -> Range<usize> {
    core.start.saturating_sub(context_cues)..core.end
}

fn audit_consistency(
    client: &Client,
    api_key: Option<&str>,
    cues: &[Cue],
    translations: &mut BTreeMap<u32, String>,
    cfg: &TranslationConfig,
) -> Result<usize> {
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
         This is a consistency-only audit, not retranslation or proofreading. Correct only a cross-line conflict where the same named entity, title, \
         place, relationship, or recurring term has incompatible target renderings. Never change a line only for fluency, wording, punctuation, or style. \
         Do not rewrite lines that are already correct. Return at most {} corrections in exactly one JSON object \
         {{\"corrections\":[{{\"index\":{},\"text\":\"corrected translation\"}}]}}. \
         Use an empty corrections array when no change is needed. Each text must contain only the corrected target-language subtitle, never the source. \
         Include only existing indices, with no markdown, reasons, or extra keys.\n\n{}",
        cfg.source_language,
        cfg.source_language_code,
        cfg.target_language,
        cfg.target_language_code,
        cfg.consistency_max_corrections,
        cues[0].index,
        serde_json::to_string(&lines)?
    );
    let expected: BTreeSet<u32> = cues.iter().map(|cue| cue.index).collect();
    let model = cfg.consistency_model.as_deref().unwrap_or(&cfg.model);
    let corrections = request_audit_corrections(
        client,
        cfg,
        api_key,
        model,
        &prompt,
        cfg.consistency_max_output_tokens,
        &expected,
        cfg.consistency_max_corrections,
        "consistency",
    )?;
    let corrected = corrections.len();
    translations.extend(corrections);
    Ok(corrected)
}

fn audit_alignment(
    client: &Client,
    api_key: Option<&str>,
    cues: &[Cue],
    translations: &mut BTreeMap<u32, String>,
    cfg: &TranslationConfig,
) -> Result<AlignmentOutcome> {
    let model = cfg
        .alignment_model
        .as_deref()
        .or(cfg.consistency_model.as_deref())
        .unwrap_or(&cfg.model);
    let mut outcome = AlignmentOutcome::default();
    let mut pending: VecDeque<AlignmentTask> =
        batch_ranges(cues, cfg.alignment_batch_size, cfg.max_batch_chars)
            .into_iter()
            .map(|range| AlignmentTask {
                positions: range.collect(),
                attempts: 0,
            })
            .collect();
    while let Some(task) = pending.pop_front() {
        let first = *task
            .positions
            .first()
            .context("alignment task unexpectedly contains no positions")?;
        let last = *task
            .positions
            .last()
            .context("alignment task unexpectedly contains no positions")?;
        let context = prompt_context_range(first..last + 1, cfg.alignment_context_cues);
        let review_positions: BTreeSet<usize> = task.positions.iter().copied().collect();
        let lines: Vec<AlignmentLine<'_>> = cues[context.clone()]
            .iter()
            .enumerate()
            .map(|(offset, cue)| {
                let position = context.start + offset;
                Ok(AlignmentLine {
                    index: cue.index,
                    source: &cue.text,
                    translation: translations.get(&cue.index).with_context(|| {
                        format!("missing translation for alignment cue {}", cue.index)
                    })?,
                    review: review_positions.contains(&position),
                })
            })
            .collect::<Result<_>>()?;
        let prompt = format!(
            "Protocol: {PROMPT_VERSION}-alignment. You are a strict subtitle source-to-target alignment auditor for {} ({}) to {} ({}). \
             For every item with review=true, decide whether translation faithfully translates only the source at the SAME index. \
             Items with review=false are read-only context. Context may clarify names, pronouns, tone, and an incomplete sentence, but its words must never be \
             added to, moved into, or substituted for a reviewed index. Correct a reviewed item when its translation belongs wholly or partly to a neighboring \
             cue, omits or invents a speaker or clause, changes the meaning, or completes a fragment with content absent from that source. If context is \
             insufficient or the intended meaning is genuinely ambiguous, do not guess and do not return a correction for that item. Preserve fragments \
             as fragments and preserve every speaker and clause that actually occurs at the reviewed index. Account for every content-bearing action, object, \
             negation, title, and domain term; reject a generic paraphrase that drops or replaces one of them. Do not change a faithful line merely for style. \
             Return at most {} corrections in exactly one JSON object \
             {{\"corrections\":[{{\"index\":{},\"text\":\"replacement translation\"}}]}}. Each replacement must be a complete translation of only the \
             source at the same index. Return an empty corrections array when every reviewed item is aligned. Include only review=true indices, with no \
             markdown, reasons, source text, or extra keys.\n\n{}",
            cfg.source_language,
            cfg.source_language_code,
            cfg.target_language,
            cfg.target_language_code,
            cfg.alignment_max_corrections,
            cues[first].index,
            serde_json::to_string(&lines)?
        );
        let expected: BTreeSet<u32> = task
            .positions
            .iter()
            .map(|position| cues[*position].index)
            .collect();
        let result = request_audit_corrections(
            client,
            cfg,
            api_key,
            model,
            &prompt,
            cfg.alignment_max_output_tokens,
            &expected,
            cfg.alignment_max_corrections,
            &format!("alignment cue indices {expected:?}"),
        );
        match result {
            Ok(corrections) => {
                for (index, correction) in corrections {
                    let position = cues
                        .iter()
                        .position(|cue| cue.index == index)
                        .with_context(|| format!("alignment returned unknown cue {index}"))?;
                    let next_attempt = task.attempts.saturating_add(1);
                    if next_attempt >= cfg.alignment_max_attempts {
                        translations.insert(index, single_line(&cues[position].text));
                        outcome.english_fallback.insert(index);
                        eprintln!(
                            "translation alignment_fallback index={index} attempts={next_attempt} action=keep_english"
                        );
                    } else {
                        translations.insert(index, correction);
                        outcome.corrected = outcome.corrected.saturating_add(1);
                        pending.push_back(AlignmentTask {
                            positions: vec![position],
                            attempts: next_attempt,
                        });
                    }
                }
            }
            Err(_) if task.positions.len() > 1 => {
                let midpoint = task.positions.len() / 2;
                println!(
                    "translation alignment_check split_indices={:?} at={midpoint}",
                    task.positions
                );
                pending.push_front(AlignmentTask {
                    positions: task.positions[midpoint..].to_vec(),
                    attempts: task.attempts,
                });
                pending.push_front(AlignmentTask {
                    positions: task.positions[..midpoint].to_vec(),
                    attempts: task.attempts,
                });
            }
            Err(error) => {
                outcome.unresolved = outcome.unresolved.saturating_add(1);
                eprintln!(
                    "translation alignment_check unresolved_index={} action=keep_current_translation error={error:#}",
                    cues[first].index
                );
            }
        }
    }
    Ok(outcome)
}

#[cfg(test)]
fn parse_consistency(
    response: &str,
    expected: &BTreeSet<u32>,
    max_corrections: usize,
) -> Result<BTreeMap<u32, String>> {
    validate_corrections(
        parse_consistency_envelope(response)?,
        expected,
        max_corrections,
    )
}

fn parse_consistency_envelope(response: &str) -> Result<ConsistencyEnvelope> {
    let normalized = normalize_known_json_keys(response);
    let trimmed = strip_single_json_fence(normalized.trim());
    let value: Value = serde_json::from_str(trimmed)
        .context("audit response is not valid JSON after safe wrapper normalization")?;
    match value {
        Value::Array(items) => Ok(ConsistencyEnvelope {
            corrections: serde_json::from_value(Value::Array(items))
                .context("audit correction array contains an invalid item")?,
        }),
        Value::Object(items) if items.is_empty() => Ok(ConsistencyEnvelope {
            corrections: Vec::new(),
        }),
        value => serde_json::from_value(value)
            .context("audit response is not the required corrections object or array"),
    }
}

fn strip_single_json_fence(response: &str) -> &str {
    let Some(inner) = response
        .strip_prefix("```json")
        .or_else(|| response.strip_prefix("```JSON"))
        .or_else(|| response.strip_prefix("```"))
    else {
        return response;
    };
    inner.strip_suffix("```").map(str::trim).unwrap_or(response)
}

fn validate_corrections(
    envelope: ConsistencyEnvelope,
    expected: &BTreeSet<u32>,
    max_corrections: usize,
) -> Result<BTreeMap<u32, String>> {
    if envelope.corrections.len() > max_corrections {
        bail!(
            "consistency response contains {} corrections, exceeding configured maximum {max_corrections}",
            envelope.corrections.len()
        );
    }
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

#[allow(clippy::too_many_arguments)]
fn request_audit_corrections(
    client: &Client,
    cfg: &TranslationConfig,
    api_key: Option<&str>,
    model: &str,
    prompt: &str,
    max_output_tokens: u32,
    expected: &BTreeSet<u32>,
    max_corrections: usize,
    audit_name: &str,
) -> Result<BTreeMap<u32, String>> {
    let response = retry(cfg.max_retries, || {
        request(client, cfg, api_key, model, prompt, max_output_tokens)
    })
    .with_context(|| format!("translation {audit_name} service request failed"))?;
    let envelope = match parse_consistency_envelope(&response) {
        Ok(envelope) => envelope,
        Err(first_error) => {
            println!("translation {audit_name} response_reformat=true");
            let repair_prompt = format!(
                "Protocol: {PROMPT_VERSION}-audit-json-reformat. Your previous {audit_name} response was not valid under the required strict JSON schema. \
                 Reformat the SAME intended corrections without adding, removing, renumbering, translating, or otherwise changing any index or text value. \
                 Return exactly one JSON object {{\"corrections\":[{{\"index\":{},\"text\":\"corrected target text\"}}]}} with at most \
                 {max_corrections} items and no markdown, reasons, or extra keys. Previous response as a JSON string:\n{}",
                expected.iter().next().copied().unwrap_or_default(),
                serde_json::to_string(&response)?
            );
            let repaired = retry(cfg.max_retries, || {
                request(
                    client,
                    cfg,
                    api_key,
                    model,
                    &repair_prompt,
                    max_output_tokens,
                )
            })
            .with_context(|| {
                format!(
                    "translation {audit_name} response reformat request failed after: {first_error:#}"
                )
            })?;
            parse_consistency_envelope(&repaired).with_context(|| {
                format!(
                    "translation {audit_name} response remained structurally invalid after one reformat attempt; first error: {first_error:#}"
                )
            })?
        }
    };
    validate_corrections(envelope, expected, max_corrections)
        .with_context(|| format!("translation {audit_name} failed strict correction checks"))
}

fn normalize_known_json_keys(response: &str) -> Cow<'_, str> {
    if response.contains("\"text:\":") {
        Cow::Owned(response.replace("\"text:\":", "\"text\":"))
    } else {
        Cow::Borrowed(response)
    }
}

fn request(
    client: &Client,
    cfg: &TranslationConfig,
    api_key: Option<&str>,
    model: &str,
    prompt: &str,
    max_output_tokens: u32,
) -> Result<String> {
    let (url, body, response_path): (String, Value, &[&str]) = match &cfg.provider {
        LlmProvider::Ollama => (
            endpoint(&cfg.base_url, "api/generate"),
            json!({
                "model": model,
                "prompt": prompt,
                "stream": false,
                "format": "json",
                "think": false,
                "keep_alive": "10m",
                "options": {
                    "temperature": 0.0,
                    "num_predict": max_output_tokens
                }
            }),
            &["response"],
        ),
        LlmProvider::OpenaiCompatible => (
            endpoint(&cfg.base_url, "chat/completions"),
            json!({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": max_output_tokens,
                "response_format": {"type": "json_object"}
            }),
            &["choices", "0", "message", "content"],
        ),
    };
    let mut request = client.post(url).json(&body);
    if let Some(key) = api_key {
        request = request.bearer_auth(key);
    }
    let response = request
        .send()
        .with_context(|| {
            format!(
                "translation model request failed for model {model:?} at {}. Start/verify the configured service and model, check network/API-key settings, then run `subtrans doctor --config <CONFIG>`",
                cfg.base_url
            )
        })?
        .error_for_status()
        .with_context(|| {
            format!(
                "translation service rejected model {model:?}. Verify the model is installed/enabled (for Ollama: `ollama pull {model}` and `ollama list`), then run `subtrans doctor --config <CONFIG>`"
            )
        })?;
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
        assert!(!prompt.contains("\"index\":7"));
        assert!(prompt.contains("{\"translations\":[{\"index\":3,\"text\":\"translation\"}]}"));
        assert!(prompt.contains("Every index is an indivisible source-to-target binding"));
        assert!(prompt.contains("preserve it as a fragment"));
        assert!(prompt.contains("\n\n["));
    }

    #[test]
    fn consistency_response_only_accepts_known_unique_indices() {
        let expected = BTreeSet::from([1, 2]);
        let corrections = parse_consistency(
            r#"{"corrections":[{"index":2,"text":"修正译文"}]}"#,
            &expected,
            2,
        )
        .unwrap();
        assert_eq!(corrections.get(&2).map(String::as_str), Some("修正译文"));
        assert!(parse_consistency(r#"{"corrections":[]}"#, &expected, 2).is_ok());
        assert!(parse_consistency(r#"[]"#, &expected, 2).is_ok());
        assert!(parse_consistency(r#"{}"#, &expected, 2).is_ok());
        assert!(parse_consistency("```json\n[]\n```", &expected, 2).is_ok());
        assert!(
            parse_consistency(
                r#"{"corrections":[{"index":3,"text":"越界"}]}"#,
                &expected,
                2
            )
            .is_err()
        );
        assert!(
            parse_consistency(
                r#"{"corrections":[{"index":1,"text":"甲"},{"index":1,"text":"乙"}]}"#,
                &expected,
                2
            )
            .is_err()
        );
        assert!(
            parse_consistency(
                r#"{"corrections":[{"index":1,"text":"甲"},{"index":2,"text":"乙"}]}"#,
                &expected,
                1
            )
            .is_err()
        );
        assert!(
            parse_consistency(
                r#"{"corrections":[{"index":2,"text:":"修正译文"}]}"#,
                &expected,
                2
            )
            .is_ok()
        );
        assert!(
            parse_consistency(
                r#"{"corrections":[{"index":2,"translation":"未知字段"}]}"#,
                &expected,
                2
            )
            .is_err()
        );
    }
}
