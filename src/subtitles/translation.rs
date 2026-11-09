use std::borrow::Cow;
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::io::Read;
use std::ops::Range;
use std::time::Duration;

use anyhow::{Context, Result, bail};
use reqwest::blocking::Client;
use serde::{Deserialize, Deserializer, Serialize, de};
use serde_json::{Value, json};

use crate::artifact::TranslationQualityRecord;
use crate::config::{LlmProvider, TranslationConfig};

use super::quality::{translation_concerns, validate_translation_quality};
use super::srt::{Cue, single_line};

const PROMPT_VERSION: &str = "subtrans-translation-two-stage-review-json-v7";

/// Token window for the one enlarged single-cue rescue request that runs
/// after the configured primary-translation retries are exhausted and
/// before the cue is queued for mandatory review. The observed empty
/// response cluster (2026-11-09, translategemma:4b) survived the normal
/// window but not the widened one. The value is deliberately a code
/// constant: nothing in `[translation]` configuration changes, so cache
/// keys are unaffected.
const PRIMARY_RESCUE_MAX_OUTPUT_TOKENS: u32 = 8_192;

#[derive(Debug, Serialize)]
struct PromptLine<'a> {
    index: u32,
    text: &'a str,
    translate: bool,
}

#[derive(Debug, Serialize)]
struct AlignmentLine<'a> {
    index: u32,
    source: &'a str,
    translation: &'a str,
    review: bool,
    must_correct: bool,
    concerns: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct TranslationEnvelope {
    #[serde(alias = "items", alias = "results")]
    translations: Vec<TranslatedLine>,
}

#[derive(Debug, Deserialize)]
struct ConsistencyEnvelope {
    #[serde(alias = "translations", alias = "items", alias = "results")]
    corrections: Vec<TranslatedLine>,
}

#[derive(Debug, Deserialize)]
struct TranslatedLine {
    #[serde(deserialize_with = "deserialize_model_index")]
    index: u32,
    #[serde(alias = "translation", alias = "translated_text", alias = "target")]
    text: String,
}

#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum ModelIndex {
    Number(u32),
    String(String),
}

fn deserialize_model_index<'de, D>(deserializer: D) -> std::result::Result<u32, D::Error>
where
    D: Deserializer<'de>,
{
    match ModelIndex::deserialize(deserializer)? {
        ModelIndex::Number(index) => Ok(index),
        ModelIndex::String(index) => index
            .parse::<u32>()
            .map_err(|_| de::Error::custom("model index string is not an unsigned integer")),
    }
}

#[derive(Debug)]
struct AlignmentTask {
    positions: Vec<usize>,
}

#[derive(Debug, Default)]
struct AlignmentOutcome {
    corrected: usize,
    flagged: usize,
    unresolved: usize,
    quality_log: Vec<TranslationQualityRecord>,
}

#[derive(Debug)]
pub struct TranslationOutcome {
    pub cues: Vec<Cue>,
    pub quality_log: Vec<TranslationQualityRecord>,
}

#[derive(Debug, Default)]
struct PendingReview {
    candidate: String,
    reasons: BTreeSet<String>,
    primary_error: Option<String>,
}

pub fn translate(cues: &[Cue], cfg: &TranslationConfig) -> Result<TranslationOutcome> {
    if cues.is_empty() || cfg.batch_size == 0 || cfg.max_batch_chars == 0 {
        bail!("source cues and translation batch limits must be non-empty");
    }
    let client = Client::builder()
        .timeout(Duration::from_secs(cfg.timeout_seconds))
        .build()?;
    let api_key = cfg.api_key()?;
    let mut translated = BTreeMap::new();
    let mut pending_review = BTreeMap::new();

    for range in batch_ranges(cues, cfg.batch_size, cfg.max_batch_chars) {
        translate_range_adaptive(
            &client,
            api_key.as_deref(),
            cues,
            range,
            cfg,
            &mut translated,
            &mut pending_review,
        )?;
        println!(
            "translation progress translated={}/{}",
            translated.len(),
            cues.len()
        );
    }
    queue_quality_concerns(cues, &translated, cfg, &mut pending_review);
    let mut quality_log = Vec::new();
    if cfg.alignment_check || cfg.consistency_check || !pending_review.is_empty() {
        println!("translation review_check cues={}", cues.len());
        let outcome = audit_alignment(
            &client,
            api_key.as_deref(),
            cues,
            &mut translated,
            cfg,
            &mut pending_review,
        )?;
        println!(
            "translation review_check corrected={} flagged={} unresolved={}",
            outcome.corrected, outcome.flagged, outcome.unresolved
        );
        quality_log = outcome.quality_log;
    }
    if !pending_review.is_empty() {
        bail!(
            "review model did not resolve required cue indices {:?}; refusing to publish untranslated or questionable text",
            pending_review.keys().collect::<Vec<_>>()
        );
    }
    let output = render(cues, &translated, cfg.bilingual)?;
    validate_translation_quality(
        cues,
        &output,
        &cfg.target_language,
        cfg.min_target_script_ratio,
    )?;
    Ok(TranslationOutcome {
        cues: output,
        quality_log,
    })
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
    pending_review: &mut BTreeMap<u32, PendingReview>,
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
        let request_and_validate = || {
            let response = request(
                client,
                cfg,
                api_key,
                &cfg.model,
                &prompt,
                cfg.max_output_tokens,
            )?;
            parse_valid_indices(&response, expected, &ignored_context_indices)
                .with_context(|| format!("raw_model_response={}", log_preview(&response)))
                .and_then(|values| {
                    if values.is_empty() {
                        bail!("translation response contains no requested cue indices");
                    }
                    Ok(values)
                })
        };
        // Malformed multi-cue responses are split immediately. A single cue
        // retries the complete request and strict parse before it is preserved
        // in English, so one bad model response cannot discard an entire film.
        let result = if range.len() == 1 {
            retry(cfg.max_retries, request_and_validate)
        } else {
            retry(cfg.max_retries, || {
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
            })
        };
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
            Err(_) if range.len() > 1 => {
                let midpoint = range.start + range.len() / 2;
                pending.push_front(midpoint..range.end);
                pending.push_front(range.start..midpoint);
            }
            Err(error) => {
                let cue = &cues[range.start];
                // One widened rescue request before conceding: the empty
                // response cluster survived every configured retry at the
                // normal token window, so widen the window exactly once
                // (a single request, no retry loop) for this one cue.
                let rescue = request(
                    client,
                    cfg,
                    api_key,
                    &cfg.model,
                    &prompt,
                    PRIMARY_RESCUE_MAX_OUTPUT_TOKENS,
                )
                .and_then(|response| {
                    parse_valid_indices(&response, expected, &ignored_context_indices)
                        .with_context(|| format!("raw_model_response={}", log_preview(&response)))
                })
                .and_then(|values| match values.get(&cue.index) {
                    Some(text) => Ok(text.clone()),
                    None => bail!("rescue response omitted cue index {}", cue.index),
                });
                match rescue {
                    Ok(text) => {
                        println!(
                            "translation rescue index={} action=primary_retry_enlarged_budget max_tokens={PRIMARY_RESCUE_MAX_OUTPUT_TOKENS} result=ok",
                            cue.index
                        );
                        if translated.insert(cue.index, text).is_some() {
                            bail!(
                                "translation batch produced duplicate cue index {}",
                                cue.index
                            );
                        }
                    }
                    Err(rescue_error) => {
                        translated.insert(cue.index, single_line(&cue.text));
                        let primary_error = format!("{error:#}; rescue: {rescue_error:#}");
                        queue_mandatory_review(
                            pending_review,
                            cue,
                            "primary_translation_failed",
                            Some(primary_error.clone()),
                        );
                        eprintln!(
                            "translation review_required index={} attempts={} reason=primary_translation_failed error={primary_error}",
                            cue.index,
                            cfg.max_retries.saturating_add(1)
                        );
                    }
                }
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

fn queue_quality_concerns(
    cues: &[Cue],
    translations: &BTreeMap<u32, String>,
    cfg: &TranslationConfig,
    pending: &mut BTreeMap<u32, PendingReview>,
) {
    for cue in cues {
        let Some(candidate) = translations.get(&cue.index) else {
            continue;
        };
        for reason in translation_concerns(
            &cue.text,
            candidate,
            &cfg.target_language,
            cfg.min_target_script_ratio,
        ) {
            queue_review_candidate(pending, cue, candidate, &reason, None);
        }
    }
}

fn queue_mandatory_review(
    pending: &mut BTreeMap<u32, PendingReview>,
    cue: &Cue,
    reason: &str,
    primary_error: Option<String>,
) {
    queue_review_candidate(pending, cue, &single_line(&cue.text), reason, primary_error);
}

fn queue_review_candidate(
    pending: &mut BTreeMap<u32, PendingReview>,
    cue: &Cue,
    candidate: &str,
    reason: &str,
    primary_error: Option<String>,
) {
    let entry = pending.entry(cue.index).or_insert_with(|| PendingReview {
        candidate: single_line(candidate),
        reasons: BTreeSet::new(),
        primary_error: None,
    });
    entry.reasons.insert(reason.to_owned());
    if let Some(error) = primary_error {
        entry.primary_error = Some(log_preview(&error));
    }
}

fn log_preview(value: &str) -> String {
    const MAX_CHARS: usize = 2_000;
    let mut preview: String = value.chars().take(MAX_CHARS).collect();
    if value.chars().count() > MAX_CHARS {
        preview.push_str("...[truncated]");
    }
    preview.replace(['\r', '\n'], "\\n")
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
    let envelope = parse_translation_envelope(response)?;
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
        if text.is_empty() {
            bail!("translation response has an empty index {}", item.index);
        }
        // TranslateGemma sometimes splits one multi-line source cue into
        // several items that share a single index. Merging them keeps the
        // full translation instead of discarding the whole batch.
        if let Some(existing) = output.get(&item.index) {
            let merged = format!("{} {}", existing, text);
            eprintln!(
                "translation merged duplicate index {} chars={}",
                item.index,
                merged.chars().count()
            );
            output.insert(item.index, merged);
            continue;
        }
        output.insert(item.index, text);
    }
    Ok(output)
}

fn parse_translation_envelope(response: &str) -> Result<TranslationEnvelope> {
    let normalized = normalize_known_json_keys(response);
    let trimmed = strip_single_json_fence(normalized.trim());
    let value: Value = serde_json::from_str(trimmed)
        .context("translation response is not valid JSON after safe wrapper normalization")?;
    match value {
        Value::Array(items) => Ok(TranslationEnvelope {
            translations: serde_json::from_value(Value::Array(items))
                .context("translation array contains an invalid item")?,
        }),
        Value::Object(items) if items.contains_key("index") => Ok(TranslationEnvelope {
            translations: vec![
                serde_json::from_value(Value::Object(items))
                    .context("translation object contains an invalid item")?,
            ],
        }),
        value => serde_json::from_value(value).context(
            "translation response is not the required translations object, item, or array",
        ),
    }
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

fn audit_alignment(
    client: &Client,
    api_key: Option<&str>,
    cues: &[Cue],
    translations: &mut BTreeMap<u32, String>,
    cfg: &TranslationConfig,
    pending_review: &mut BTreeMap<u32, PendingReview>,
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
                let reviewed = review_positions.contains(&position);
                Ok(AlignmentLine {
                    index: cue.index,
                    source: &cue.text,
                    translation: translations.get(&cue.index).with_context(|| {
                        format!("missing translation for alignment cue {}", cue.index)
                    })?,
                    review: reviewed,
                    must_correct: reviewed && pending_review.contains_key(&cue.index),
                    concerns: reviewed
                        .then(|| pending_review.get(&cue.index))
                        .flatten()
                        .map(|trigger| trigger.reasons.iter().cloned().collect())
                        .unwrap_or_default(),
                })
            })
            .collect::<Result<_>>()?;
        let prompt = format!(
            "Protocol: {PROMPT_VERSION}-final-review. You are the one-pass final subtitle reviewer for {} ({}) to {} ({}). \
             For every item with review=true, decide whether the translation is accurate, complete, natural, consistent, and bound only to the source at the SAME index. \
             Items with review=false are read-only context. Context may clarify names, pronouns, tone, and an incomplete sentence, but its words must never be \
             added to, moved into, or substituted for a reviewed index. Correct a reviewed item when its translation belongs wholly or partly to a neighboring \
             cue, repeats untranslated source prose, has inadequate target-language content, uses inconsistent terminology, omits or invents a speaker or clause, \
             changes the meaning, or completes a fragment with content absent from that source. Every item with must_correct=true has already failed a hard check: \
             you MUST return a complete final target-language correction for that index. Preserve fragments \
             as fragments and preserve every speaker and clause that actually occurs at the reviewed index. Account for every content-bearing action, object, \
             negation, title, and domain term; reject a generic paraphrase that drops or replaces one of them. This is the only review pass: return the final result \
             directly and do not ask the translation model to revise it. \
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
            Ok(AuditResolution {
                corrections,
                unresolved_empty,
                unresolved_unparseable,
            }) => {
                let unresolved_empty: BTreeSet<u32> = unresolved_empty.into_iter().collect();
                let unresolved_unparseable: BTreeSet<u32> =
                    unresolved_unparseable.into_iter().collect();
                let required: BTreeSet<u32> = expected
                    .iter()
                    .filter(|index| {
                        pending_review.contains_key(index)
                            && !unresolved_empty.contains(index)
                            && !unresolved_unparseable.contains(index)
                    })
                    .copied()
                    .collect();
                let missing_required: Vec<u32> = required
                    .iter()
                    .filter(|index| !corrections.contains_key(index))
                    .copied()
                    .collect();
                if !missing_required.is_empty() && task.positions.len() > 1 {
                    let midpoint = task.positions.len() / 2;
                    eprintln!(
                        "translation review_check split_indices={:?} reason=missing_required_corrections indices={missing_required:?}",
                        task.positions
                    );
                    pending.push_front(AlignmentTask {
                        positions: task.positions[midpoint..].to_vec(),
                    });
                    pending.push_front(AlignmentTask {
                        positions: task.positions[..midpoint].to_vec(),
                    });
                    continue;
                }
                if !missing_required.is_empty() {
                    bail!(
                        "review model omitted mandatory correction for cue indices {missing_required:?}"
                    );
                }
                for (index, correction) in corrections {
                    let position = cues
                        .iter()
                        .position(|cue| cue.index == index)
                        .with_context(|| format!("alignment returned unknown cue {index}"))?;
                    let previous = translations
                        .get(&index)
                        .cloned()
                        .unwrap_or_else(|| single_line(&cues[position].text));
                    let concerns = translation_concerns(
                        &cues[position].text,
                        &correction,
                        &cfg.target_language,
                        cfg.min_target_script_ratio,
                    );
                    if !concerns.is_empty() {
                        bail!(
                            "review model returned a questionable final correction for cue {index}: {}",
                            concerns.join(",")
                        );
                    }
                    let trigger = pending_review.remove(&index);
                    let reasons = trigger
                        .as_ref()
                        .map(|value| value.reasons.iter().cloned().collect())
                        .unwrap_or_else(|| vec!["review_model_quality_correction".to_owned()]);
                    let primary_error = trigger
                        .as_ref()
                        .and_then(|value| value.primary_error.clone());
                    let candidate_before_review =
                        trigger.map(|value| value.candidate).unwrap_or(previous);
                    let reviewed_translation = correction;
                    translations.insert(index, reviewed_translation.clone());
                    outcome.corrected = outcome.corrected.saturating_add(1);
                    outcome.flagged = outcome.flagged.saturating_add(1);
                    outcome.quality_log.push(TranslationQualityRecord {
                        cue_index: index,
                        source: single_line(&cues[position].text),
                        candidate_before_review,
                        reviewed_translation,
                        reasons,
                        primary_error,
                        translation_model: cfg.model.clone(),
                        review_model: model.to_owned(),
                    });
                }
                // Indices still answering with empty corrections after the
                // rescue round, and indices whose consistency/rescue response
                // never parsed at all (model outage), both keep the current
                // translation and downgrade to unresolved instead of aborting
                // the run. Mandatory cues are recorded in the quality log so
                // the review trail survives; a parsed response that simply
                // omits a mandatory correction is still a hard bail.
                let downgrades = unresolved_empty
                    .iter()
                    .map(|index| (*index, "review_empty_correction_unresolved"))
                    .chain(
                        unresolved_unparseable
                            .iter()
                            .map(|index| (*index, "review_unparseable_correction_unresolved")),
                    );
                for (index, downgrade_reason) in downgrades {
                    outcome.unresolved = outcome.unresolved.saturating_add(1);
                    let trigger = pending_review.remove(&index);
                    if let Some(trigger) = trigger {
                        let position = cues
                            .iter()
                            .position(|cue| cue.index == index)
                            .with_context(|| format!("alignment returned unknown cue {index}"))?;
                        let current = translations
                            .get(&index)
                            .cloned()
                            .unwrap_or_else(|| single_line(&cues[position].text));
                        let mut reasons: Vec<String> = trigger.reasons.iter().cloned().collect();
                        reasons.push(downgrade_reason.to_owned());
                        outcome.quality_log.push(TranslationQualityRecord {
                            cue_index: index,
                            source: single_line(&cues[position].text),
                            candidate_before_review: trigger.candidate,
                            reviewed_translation: current,
                            reasons,
                            primary_error: trigger.primary_error,
                            translation_model: cfg.model.clone(),
                            review_model: model.to_owned(),
                        });
                    }
                    eprintln!(
                        "translation review_check unresolved_index={index} action=keep_current_translation reason={downgrade_reason}"
                    );
                }
            }
            Err(_) if task.positions.len() > 1 => {
                let midpoint = task.positions.len() / 2;
                println!(
                    "translation review_check split_indices={:?} at={midpoint}",
                    task.positions
                );
                pending.push_front(AlignmentTask {
                    positions: task.positions[midpoint..].to_vec(),
                });
                pending.push_front(AlignmentTask {
                    positions: task.positions[..midpoint].to_vec(),
                });
            }
            Err(error) => {
                // Leaf task (a single cue): a review response that never
                // parsed even after the one reformat re-ask is a model
                // outage, not a refusal (2026-11-10, item-5 cue-419 rerun:
                // the drill-down reached the exact cue and the model kept
                // answering with an empty body). The cue keeps its current
                // translation and downgrades to unresolved so the file
                // still publishes. A parsed-but-refused response (strict
                // correction checks, omitted mandatory corrections) keeps
                // its hard bail: outage must not launder a real refusal.
                let index = cues[first].index;
                let trigger = pending_review.remove(&index);
                let outage = error.to_string().contains("remained structurally invalid");
                if trigger.is_some() && !outage {
                    return Err(error).with_context(|| {
                        format!(
                            "review failed for mandatory cue {index}; refusing to publish questionable text"
                        )
                    });
                }
                outcome.unresolved = outcome.unresolved.saturating_add(1);
                if let Some(trigger) = trigger {
                    let current = translations
                        .get(&index)
                        .cloned()
                        .unwrap_or_else(|| single_line(&cues[first].text));
                    let mut reasons: Vec<String> = trigger.reasons.iter().cloned().collect();
                    reasons.push("review_unparseable_correction_unresolved".to_owned());
                    outcome.quality_log.push(TranslationQualityRecord {
                        cue_index: index,
                        source: single_line(&cues[first].text),
                        candidate_before_review: trigger.candidate,
                        reviewed_translation: current,
                        reasons,
                        primary_error: trigger.primary_error,
                        translation_model: cfg.model.clone(),
                        review_model: model.to_owned(),
                    });
                }
                eprintln!(
                    "translation review_check unresolved_index={index} action=keep_current_translation error={error:#}"
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
        Value::Object(items) if items.contains_key("index") => Ok(ConsistencyEnvelope {
            corrections: vec![
                serde_json::from_value(Value::Object(items))
                    .context("audit correction object contains an invalid item")?,
            ],
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

/// Split a corrections envelope into accepted items and the indices whose
/// text came back empty. Empty-text items are collected rather than bailing
/// so the caller can run the empty-correction rescue round; every other
/// violation keeps the strict bail behaviour.
fn partition_corrections(
    envelope: ConsistencyEnvelope,
    expected: &BTreeSet<u32>,
    max_corrections: usize,
) -> Result<(BTreeMap<u32, String>, Vec<u32>)> {
    if envelope.corrections.len() > max_corrections {
        bail!(
            "consistency response contains {} corrections, exceeding configured maximum {max_corrections}",
            envelope.corrections.len()
        );
    }
    let mut corrections = BTreeMap::new();
    let mut empty = Vec::new();
    for item in envelope.corrections {
        if !expected.contains(&item.index) {
            bail!(
                "consistency response contains unexpected index {}",
                item.index
            );
        }
        let text = single_line(&item.text);
        if text.is_empty() {
            if !empty.contains(&item.index) {
                empty.push(item.index);
            }
            continue;
        }
        if corrections.insert(item.index, text).is_some() {
            bail!(
                "consistency response has an empty or duplicate index {}",
                item.index
            );
        }
    }
    Ok((corrections, empty))
}

/// Strict one-shot validation used by tests and callers that want the
/// pre-rescue behaviour: any empty correction text is a hard bail. The
/// production audit path goes through [`partition_corrections`] so the
/// empty-correction rescue round can run first.
#[cfg(test)]
fn validate_corrections(
    envelope: ConsistencyEnvelope,
    expected: &BTreeSet<u32>,
    max_corrections: usize,
) -> Result<BTreeMap<u32, String>> {
    let (corrections, empty) = partition_corrections(envelope, expected, max_corrections)?;
    if let Some(index) = empty.first() {
        bail!(
            "consistency response has an empty or duplicate index {}",
            index
        );
    }
    Ok(corrections)
}

/// Outcome of one audit request round: the accepted corrections plus the
/// two unresolved-downgrade lists — indices answered with an empty `text`
/// even after the empty-correction rescue round, and indices whose response
/// never parsed at all (model outage). Both lists keep the current
/// translation and downgrade to unresolved; neither aborts the run.
struct AuditResolution {
    corrections: BTreeMap<u32, String>,
    unresolved_empty: Vec<u32>,
    unresolved_unparseable: Vec<u32>,
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
) -> Result<AuditResolution> {
    let response = retry(cfg.max_retries, || {
        request(client, cfg, api_key, model, prompt, max_output_tokens)
    })
    .with_context(|| format!("translation {audit_name} service request failed"))?;
    let envelope = match parse_consistency_envelope(&response) {
        Ok(envelope) => envelope,
        Err(first_error) => {
            println!("translation {audit_name} response_reformat=true");
            let repair_prompt = build_reformat_prompt(
                audit_name,
                expected.iter().next().copied().unwrap_or_default(),
                max_corrections,
                &response,
            )
            .with_context(|| {
                format!(
                    "translation {audit_name} reformat prompt could not embed the previous response"
                )
            })?;
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
            // An initial (or reformat-repaired) audit response that never
            // parses must keep hard-failing: `audit_alignment` uses this
            // error to binary-split the batch until the exact offending
            // indices are auditable (see the split-until-auditable pin).
            // Downgrading here would silently kill the splitter. The
            // model-outage downgrade instead lives in the leaf handling of
            // `audit_alignment` and in the empty-correction rescue round
            // below (2026-11-10, item-5 cue-419 rerun death site).
            parse_consistency_envelope(&repaired).with_context(|| {
                format!(
                    "translation {audit_name} response remained structurally invalid after one reformat attempt; first error: {first_error:#}"
                )
            })?
        }
    };
    let (mut corrections, empty) = partition_corrections(envelope, expected, max_corrections)
        .with_context(|| format!("translation {audit_name} failed strict correction checks"))?;
    if empty.is_empty() {
        return Ok(AuditResolution {
            corrections,
            unresolved_empty: Vec::new(),
            unresolved_unparseable: Vec::new(),
        });
    }
    // Empty-text corrections used to abort entire runs (2026-11-09, item 5
    // cue 419: a one-word line burned 4h of translation plus 1h of review).
    // Give the review model exactly one more round with the same prompt
    // before those indices are handed back for unresolved downgrade; any
    // valid correction the retry adds is kept.
    eprintln!("translation {audit_name} empty_correction_retry=true indices={empty:?}");
    let retry_response = retry(cfg.max_retries, || {
        request(client, cfg, api_key, model, prompt, max_output_tokens)
    })
    .with_context(|| {
        format!("translation {audit_name} empty-correction retry request failed after {empty:?}")
    })?;
    let (retry_corrections, retry_empty, retry_unparseable) = match parse_consistency_envelope(
        &retry_response,
    ) {
        Ok(envelope) => {
            let (retry_corrections, retry_empty) =
                    partition_corrections(envelope, expected, max_corrections).with_context(
                        || {
                            format!(
                                "translation {audit_name} failed strict correction checks after one empty-correction retry"
                            )
                        },
                    )?;
            (retry_corrections, retry_empty, Vec::new())
        }
        Err(error) => {
            // The stubborn-empty model answers this round with an empty
            // body (EOF) or garbage too: still a model outage, so every
            // index still waiting keeps its current translation and is
            // downgraded instead of bailing the whole file.
            eprintln!(
                "translation {audit_name} empty_correction_retry_unparseable=true indices={empty:?} error={error:#}"
            );
            (BTreeMap::new(), Vec::new(), empty.clone())
        }
    };
    corrections.extend(retry_corrections);
    Ok(AuditResolution {
        corrections,
        unresolved_empty: retry_empty,
        unresolved_unparseable: retry_unparseable,
    })
}

/// Build the repair prompt that asks the model to reformat its previous
/// audit response into the strict corrections envelope.
///
/// The schema outline deliberately carries no example text body: small
/// models (translategemma:4b) were observed copying an English example
/// literal verbatim into every `text` value, which then failed the target
/// script ratio gate and aborted the whole batch. Describing the shape in
/// words, and forbidding invented values, keeps the original text intact.
fn build_reformat_prompt(
    audit_name: &str,
    first_index: u32,
    max_corrections: usize,
    previous_response: &str,
) -> Result<String> {
    let quoted = serde_json::to_string(previous_response)?;
    Ok(format!(
        "Protocol: {PROMPT_VERSION}-audit-json-reformat. Your previous {audit_name} response was not valid under the required strict JSON schema. \
         Reformat the SAME intended corrections without adding, removing, renumbering, translating, or otherwise changing any index or text value. \
         Return exactly one JSON object {{\"corrections\":[...]}} with at most {max_corrections} items and no markdown, reasons, or extra keys. \
         Each item has exactly two keys: \"index\", the unchanged number (the first item keeps index {first_index}), and \"text\", the unchanged string. \
         Copy every \"text\" value character-for-character from your previous response; never substitute an example, a placeholder, a translation, or any new wording for a text value. \
         Previous response as a JSON string:\n{quoted}"
    ))
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
model = "translategemma:4b"
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
    fn translation_response_accepts_safe_model_format_variants() {
        let expected = cues(2);
        let actual_translategemma = r#"{"translations":[{"index":1,"text":"第一行","translate":true,"confidence":0.98},{"index":2,"text":"第二行","translate":true}]}"#;
        let parsed = parse_aligned(actual_translategemma, &expected).unwrap();
        assert_eq!(parsed.get(&1).map(String::as_str), Some("第一行"));
        assert_eq!(parsed.get(&2).map(String::as_str), Some("第二行"));

        let fenced_bare_array = "```json\n[{\"index\":\"1\",\"translation\":\"甲\"},{\"index\":2,\"translated_text\":\"乙\"}]\n```";
        let parsed = parse_aligned(fenced_bare_array, &expected).unwrap();
        assert_eq!(parsed.get(&1).map(String::as_str), Some("甲"));
        assert_eq!(parsed.get(&2).map(String::as_str), Some("乙"));

        let single = parse_aligned(
            r#"{"index":"1","target":"单条","explanation":"ignored transport metadata"}"#,
            &expected[..1],
        )
        .unwrap();
        assert_eq!(single.get(&1).map(String::as_str), Some("单条"));
    }

    #[test]
    fn flexible_translation_format_keeps_strict_semantic_checks() {
        let expected = cues(2);
        assert!(
            parse_aligned(
                r#"[{"index":1,"text":"甲"},{"index":1,"text":"乙"}]"#,
                &expected,
            )
            .is_err()
        );
        assert!(
            parse_aligned(
                r#"[{"index":1,"text":"甲"},{"index":3,"text":"越界"}]"#,
                &expected,
            )
            .is_err()
        );
        assert!(parse_aligned(r#"[{"index":1,"text":"甲"}]"#, &expected).is_err());
        assert!(
            parse_aligned(
                r#"[{"index":1,"text":"甲"},{"index":2,"text":"   "}]"#,
                &expected,
            )
            .is_err()
        );
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
                r#"{"results":[{"index":"2","translated_text":"兼容译文","confidence":0.9}]}"#,
                &expected,
                2
            )
            .is_ok()
        );
        assert!(
            parse_consistency(
                r#"{"corrections":[{"index":2,"unexpected_text":"未知字段"}]}"#,
                &expected,
                2
            )
            .is_err()
        );
    }

    #[test]
    fn duplicate_index_items_are_merged_into_one_line() {
        let expected = cues(2);
        let parsed = parse_aligned(
            r#"[{"index":1,"text":"第一行"},{"index":2,"text":"第二行上"},{"index":2,"text":"第二行下"}]"#,
            &expected,
        )
        .unwrap();
        assert_eq!(parsed.get(&1).map(String::as_str), Some("第一行"));
        assert_eq!(
            parsed.get(&2).map(String::as_str),
            Some("第二行上 第二行下")
        );
    }

    #[test]
    fn duplicate_index_merge_still_rejects_empty_text() {
        let expected = cues(1);
        assert!(
            parse_aligned(
                r#"[{"index":1,"text":"甲"},{"index":1,"text":"   "}]"#,
                &expected,
            )
            .is_err()
        );
    }

    #[test]
    fn reformat_prompt_carries_no_copyable_text_example() {
        let prompt = build_reformat_prompt("reviewer", 3, 5, "PREVIOUS-RESPONSE-MARKER").unwrap();
        assert!(prompt.contains("audit-json-reformat"));
        assert!(prompt.contains("PREVIOUS-RESPONSE-MARKER"));
        assert!(prompt.contains("character-for-character"));
        assert!(prompt.contains("keeps index 3"));
        assert!(prompt.contains("at most 5 items"));
        // Regression: an English example body literal was copied verbatim by
        // translategemma:4b into every text value, tripping the target script
        // ratio gate. The prompt must never pair a "text" key with a string
        // example value, and must keep only the bare structural outline.
        assert!(!prompt.contains("corrected target text"));
        assert!(!prompt.contains(r#""text":""#));
        assert!(prompt.contains(r#"{"corrections":[...]}"#));
    }

    // ----- empty-response mandatory rescue (2026-11-09 item-5 cluster) -----

    use std::io::{BufRead, BufReader, Write};
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex};

    fn prompt_items(prompt: &str) -> Vec<Value> {
        let start = prompt.rfind("\n\n").expect("prompt body separator") + 2;
        serde_json::from_str(&prompt[start..]).expect("prompt body is a JSON array")
    }

    fn ollama_reply(content: Value) -> String {
        json!({ "response": content.to_string() }).to_string()
    }

    /// Mock Ollama endpoint: every request body is recorded and answered by
    /// `responder`. The accept loop is intentionally unbounded and detached;
    /// the test process exits once assertions run.
    fn llm_server(
        responder: impl Fn(&Value) -> String + Send + 'static,
    ) -> (String, Arc<Mutex<Vec<Value>>>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let base_url = format!("http://{}", listener.local_addr().unwrap());
        let seen = Arc::new(Mutex::new(Vec::new()));
        let seen_thread = Arc::clone(&seen);
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { continue };
                let mut reader = BufReader::new(stream.try_clone().unwrap());
                let mut content_length = 0usize;
                loop {
                    let mut line = String::new();
                    if reader.read_line(&mut line).unwrap() == 0 {
                        break;
                    }
                    let trimmed = line.trim_end();
                    if trimmed.is_empty() {
                        break;
                    }
                    if trimmed.to_ascii_lowercase().starts_with("content-length:") {
                        content_length = trimmed[15..].trim().parse().unwrap();
                    }
                }
                let mut body = vec![0u8; content_length];
                reader.read_exact(&mut body).unwrap();
                let body: Value = serde_json::from_slice(&body).unwrap();
                seen_thread.lock().unwrap().push(body.clone());
                let reply = responder(&body);
                let http = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    reply.len(),
                    reply
                );
                stream.write_all(http.as_bytes()).unwrap();
                stream.flush().unwrap();
            }
        });
        (base_url, seen)
    }

    #[test]
    fn partition_corrections_splits_empty_from_valid_items() {
        let expected = BTreeSet::from([1, 2, 3]);
        let envelope = parse_consistency_envelope(
            r#"{"corrections":[{"index":1,"text":"甲"},{"index":2,"text":"  "},{"index":3,"text":" "}]}"#,
        )
        .unwrap();
        let (corrections, empty) = partition_corrections(envelope, &expected, 3).unwrap();
        assert_eq!(corrections.get(&1).map(String::as_str), Some("甲"));
        assert!(!corrections.contains_key(&2));
        assert_eq!(empty, vec![2, 3]);
    }

    #[test]
    fn strict_validate_corrections_still_bails_on_empty_text() {
        let expected = BTreeSet::from([1]);
        assert!(
            parse_consistency(r#"{"corrections":[{"index":1,"text":"  "}]}"#, &expected, 1)
                .is_err()
        );
    }

    #[test]
    fn primary_rescue_retry_widens_token_window_before_mandatory_queue() {
        // Every normal-window attempt answers with an empty translation (the
        // item-5 cue-419 cluster); only the widened rescue window succeeds,
        // so the cue must never reach the mandatory review queue.
        let (base_url, seen) = llm_server(|body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
                return ollama_reply(json!({ "corrections": [] }));
            }
            let window = body["options"]["num_predict"].as_u64().unwrap();
            if window == u64::from(PRIMARY_RESCUE_MAX_OUTPUT_TOKENS) {
                return ollama_reply(json!({
                    "translations": [{ "index": 1, "text": "第一行。" }]
                }));
            }
            ollama_reply(json!({ "translations": [{ "index": 1, "text": "" }] }))
        });
        let mut cfg = config();
        cfg.base_url = base_url;
        cfg.timeout_seconds = 10;
        cfg.max_retries = 1;
        let outcome = translate(&cues(1), &cfg).unwrap();
        assert_eq!(outcome.cues[0].text, "第一行。\nLine 1");
        assert!(outcome.quality_log.is_empty());
        let windows: Vec<u64> = seen
            .lock()
            .unwrap()
            .iter()
            .filter(|body| !body["prompt"].as_str().unwrap().contains("final-review"))
            .map(|body| body["options"]["num_predict"].as_u64().unwrap())
            .collect();
        assert_eq!(
            windows,
            vec![
                u64::from(cfg.max_output_tokens),
                u64::from(cfg.max_output_tokens),
                u64::from(PRIMARY_RESCUE_MAX_OUTPUT_TOKENS)
            ]
        );
    }

    #[test]
    fn empty_review_correction_retries_then_downgrades_mandatory_cue() {
        // Primary translation fails at every window, so cue 1 is mandatory;
        // the review model keeps answering with an empty correction text.
        // Before the rescue this combination aborted the whole run.
        let review_calls = Arc::new(AtomicUsize::new(0));
        let review_seen = Arc::clone(&review_calls);
        let (base_url, _seen) = llm_server(move |body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
                review_seen.fetch_add(1, Ordering::SeqCst);
                if prompt.contains("\"must_correct\":true") {
                    return ollama_reply(json!({
                        "corrections": [{ "index": 1, "text": "" }]
                    }));
                }
                return ollama_reply(json!({ "corrections": [] }));
            }
            let translations: Vec<Value> = prompt_items(prompt)
                .iter()
                .filter(|item| item["translate"] == Value::Bool(true))
                .map(|item| {
                    let index = item["index"].as_u64().unwrap();
                    if index == 1 {
                        json!({ "index": 1, "text": "" })
                    } else {
                        json!({ "index": index, "text": format!("第{index}行。") })
                    }
                })
                .collect();
            ollama_reply(json!({ "translations": translations }))
        });
        let mut cfg = config();
        cfg.base_url = base_url;
        cfg.timeout_seconds = 10;
        cfg.max_retries = 1;
        let outcome = translate(&cues(10), &cfg).unwrap();
        // The failed cue keeps its current text instead of killing the run.
        assert_eq!(outcome.cues[0].text, "Line 1\nLine 1");
        assert_eq!(outcome.cues[1].text, "第2行。\nLine 2");
        // The audit model got exactly one extra round for the empty text
        // (task containing cue 1) on top of the other alignment task.
        assert_eq!(review_calls.load(Ordering::SeqCst), 3);
        assert_eq!(outcome.quality_log.len(), 1);
        let record = &outcome.quality_log[0];
        assert_eq!(record.cue_index, 1);
        assert_eq!(record.reviewed_translation, "Line 1");
        assert_eq!(record.candidate_before_review, "Line 1");
        assert!(
            record
                .reasons
                .iter()
                .any(|reason| reason == "primary_translation_failed")
        );
        assert!(
            record
                .reasons
                .iter()
                .any(|reason| reason == "review_empty_correction_unresolved")
        );
        assert!(
            record
                .primary_error
                .as_deref()
                .is_some_and(|error| error.contains("rescue:"))
        );
    }

    #[test]
    fn omitted_mandatory_correction_still_bails() {
        // The empty-correction downgrade must not weaken the omission rule:
        // a review model that never mentions the mandatory cue is still fatal.
        let (base_url, _seen) = llm_server(|body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
                return ollama_reply(json!({ "corrections": [] }));
            }
            ollama_reply(json!({ "translations": [{ "index": 1, "text": "" }] }))
        });
        let mut cfg = config();
        cfg.base_url = base_url;
        cfg.timeout_seconds = 10;
        cfg.max_retries = 1;
        let error = translate(&cues(1), &cfg).unwrap_err().to_string();
        assert!(error.contains("omitted mandatory correction"), "{error}");
    }

    /// 2026-11-10 item-5 rerun: the review leg answers the mandatory-cue
    /// consistency request (and its reformat + empty-correction rescue
    /// rounds) with a response that never parses — an entirely empty body
    /// (EOF) or plain garbage. That is a model outage, not a refusal: the
    /// cue must keep its current translation, downgrade to unresolved with
    /// `review_unparseable_correction_unresolved`, and the file must publish.
    fn mandatory_cue_downgrades_when_review_never_parses(bad_response: Value) {
        let (base_url, seen) = llm_server(move |body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("audit-json-reformat") {
                return ollama_reply(bad_response.clone());
            }
            if prompt.contains("final-review") {
                if prompt.contains("\"must_correct\":true") {
                    return ollama_reply(bad_response.clone());
                }
                return ollama_reply(json!({ "corrections": [] }));
            }
            let translations: Vec<Value> = prompt_items(prompt)
                .iter()
                .filter(|item| item["translate"] == Value::Bool(true))
                .map(|item| {
                    let index = item["index"].as_u64().unwrap();
                    if index == 1 {
                        json!({ "index": 1, "text": "" })
                    } else {
                        json!({ "index": index, "text": format!("第{index}行。") })
                    }
                })
                .collect();
            ollama_reply(json!({ "translations": translations }))
        });
        let mut cfg = config();
        cfg.base_url = base_url;
        cfg.timeout_seconds = 10;
        cfg.max_retries = 1;
        let outcome = translate(&cues(10), &cfg).unwrap();
        // The run publishes: the failed cue keeps its current translation.
        assert_eq!(outcome.cues[0].text, "Line 1\nLine 1");
        assert_eq!(outcome.cues[1].text, "第2行。\nLine 2");
        // Every broken review round got exactly one reformat re-ask and no
        // more: the drill-down splits the mandatory batch one halving per
        // level (8→4→2→1), each broken round asking one reformat, and the
        // leaf then downgrades without a second round or a rescue storm.
        let seen = seen.lock().unwrap();
        let broken_rounds = seen
            .iter()
            .filter(|body| {
                body["prompt"].as_str().unwrap().contains("final-review")
                    && body["prompt"]
                        .as_str()
                        .unwrap()
                        .contains("\"must_correct\":true")
            })
            .count();
        let reformats = seen
            .iter()
            .filter(|body| {
                body["prompt"]
                    .as_str()
                    .unwrap()
                    .contains("audit-json-reformat")
            })
            .count();
        assert!(broken_rounds >= 1, "{broken_rounds}");
        assert_eq!(reformats, broken_rounds);
        drop(seen);
        assert_eq!(outcome.quality_log.len(), 1);
        let record = &outcome.quality_log[0];
        assert_eq!(record.cue_index, 1);
        assert_eq!(record.reviewed_translation, "Line 1");
        assert_eq!(record.candidate_before_review, "Line 1");
        assert!(
            record
                .reasons
                .iter()
                .any(|reason| reason == "primary_translation_failed")
        );
        assert!(
            record
                .reasons
                .iter()
                .any(|reason| reason == "review_unparseable_correction_unresolved")
        );
        assert!(
            record
                .primary_error
                .as_deref()
                .is_some_and(|error| error.contains("rescue:"))
        );
    }

    #[test]
    fn empty_review_response_downgrades_mandatory_cue_and_publishes() {
        mandatory_cue_downgrades_when_review_never_parses(json!(""));
    }

    #[test]
    fn garbage_review_response_downgrades_mandatory_cue_and_publishes() {
        mandatory_cue_downgrades_when_review_never_parses(json!(
            "I cannot review this line, sorry {corrections:"
        ));
    }
}
