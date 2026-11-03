use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::ops::Range;
use std::time::Duration;

use anyhow::{Context, Result, bail};
use serde::Serialize;
use subtrans_core::remote::{LlmApi, LlmClient, LlmCompletion};

use crate::artifact::TranslationQualityRecord;
use crate::config::{LlmProvider, TranslationConfig};
pub use subtrans_core::protocol::validate_output;
use subtrans_core::protocol::{
    parse_consistency_envelope, parse_valid_indices, render, validate_corrections,
};
use subtrans_core::quality::{translation_concerns, validate_translation_quality};
use subtrans_core::srt::{Cue, single_line};

const PROMPT_VERSION: &str = "subtrans-translation-two-stage-review-json-v7";

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

pub fn translate(
    cues: &[Cue],
    cfg: &TranslationConfig,
    client: &dyn LlmClient,
    video: &str,
) -> Result<TranslationOutcome> {
    if cues.is_empty() || cfg.batch_size == 0 || cfg.max_batch_chars == 0 {
        bail!("source cues and translation batch limits must be non-empty");
    }
    let api_key = cfg.api_key()?;
    let mut translated = BTreeMap::new();
    let mut pending_review = BTreeMap::new();

    for range in batch_ranges(cues, cfg.batch_size, cfg.max_batch_chars) {
        translate_range_adaptive(
            client,
            api_key.as_deref(),
            cues,
            range,
            cfg,
            &mut translated,
            &mut pending_review,
        )?;
        subtrans_core::report_line!(
            out,
            "translation.progress",
            serde_json::json!({"translated": translated.len(), "cues": cues.len()}),
            "translation progress translated={}/{}",
            translated.len(),
            cues.len()
        );
    }
    queue_quality_concerns(cues, &translated, cfg, &mut pending_review);
    let mut quality_log = Vec::new();
    if cfg.alignment_check || cfg.consistency_check || !pending_review.is_empty() {
        subtrans_core::report_line!(
            out,
            "translation.review_check",
            serde_json::json!({"cues": cues.len()}),
            "translation review_check cues={}",
            cues.len()
        );
        let outcome = audit_alignment(
            client,
            api_key.as_deref(),
            cues,
            &mut translated,
            cfg,
            &mut pending_review,
            video,
        )?;
        subtrans_core::report_line!(
            out,
            "translation.review_check",
            serde_json::json!({
                "corrected": outcome.corrected,
                "flagged": outcome.flagged,
                "unresolved": outcome.unresolved
            }),
            "translation review_check corrected={} flagged={} unresolved={}",
            outcome.corrected,
            outcome.flagged,
            outcome.unresolved
        );
        quality_log = outcome.quality_log;
    }
    if !pending_review.is_empty() {
        for (index, review) in &pending_review {
            report_blocked(video, *index, &blocked_reason(Some(review)));
        }
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
    client: &dyn LlmClient,
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
                translated.insert(cue.index, single_line(&cue.text));
                queue_mandatory_review(
                    pending_review,
                    cue,
                    "primary_translation_failed",
                    Some(format!("{error:#}")),
                );
                subtrans_core::report_line!(
                    err,
                    "translation.review_required",
                    serde_json::json!({
                        "index": cue.index,
                        "attempts": cfg.max_retries.saturating_add(1),
                        "reason": "primary_translation_failed",
                        "error": format!("{error:#}")
                    }),
                    "translation review_required index={} attempts={} reason=primary_translation_failed error={error:#}",
                    cue.index,
                    cfg.max_retries.saturating_add(1)
                );
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

fn report_blocked(video: &str, index: u32, reason: &str) {
    subtrans_core::report::emit(
        subtrans_core::report::Stream::Stdout,
        "",
        "subtitle.blocked",
        serde_json::json!({"video": video, "reason": reason, "index": index}),
    );
}

fn blocked_reason(review: Option<&PendingReview>) -> String {
    match review {
        Some(review) if !review.reasons.is_empty() => {
            review.reasons.iter().cloned().collect::<Vec<_>>().join(",")
        }
        _ => "review_failed".to_owned(),
    }
}

fn audit_alignment(
    client: &dyn LlmClient,
    api_key: Option<&str>,
    cues: &[Cue],
    translations: &mut BTreeMap<u32, String>,
    cfg: &TranslationConfig,
    pending_review: &mut BTreeMap<u32, PendingReview>,
    video: &str,
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
            Ok(corrections) => {
                let required: BTreeSet<u32> = expected
                    .iter()
                    .filter(|index| pending_review.contains_key(index))
                    .copied()
                    .collect();
                let missing_required: Vec<u32> = required
                    .iter()
                    .filter(|index| !corrections.contains_key(index))
                    .copied()
                    .collect();
                if !missing_required.is_empty() && task.positions.len() > 1 {
                    let midpoint = task.positions.len() / 2;
                    subtrans_core::report_line!(
                        err,
                        "translation.review_split",
                        serde_json::json!({
                            "indices": task.positions,
                            "reason": "missing_required_corrections",
                            "missing": missing_required
                        }),
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
                    for index in &missing_required {
                        report_blocked(video, *index, &blocked_reason(pending_review.get(index)));
                    }
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
                        report_blocked(video, index, &concerns.join(","));
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
            }
            Err(_) if task.positions.len() > 1 => {
                let midpoint = task.positions.len() / 2;
                subtrans_core::report_line!(
                    out,
                    "translation.review_split",
                    serde_json::json!({"indices": task.positions, "at": midpoint}),
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
                outcome.unresolved = outcome.unresolved.saturating_add(1);
                if pending_review.contains_key(&cues[first].index) {
                    report_blocked(
                        video,
                        cues[first].index,
                        &blocked_reason(pending_review.get(&cues[first].index)),
                    );
                    return Err(error).with_context(|| {
                        format!(
                            "review failed for mandatory cue {}; refusing to publish questionable text",
                            cues[first].index
                        )
                    });
                }
                subtrans_core::report_line!(
                    err,
                    "translation.review_unresolved",
                    serde_json::json!({
                        "index": cues[first].index,
                        "action": "keep_current_translation",
                        "error": format!("{error:#}")
                    }),
                    "translation review_check unresolved_index={} action=keep_current_translation error={error:#}",
                    cues[first].index
                );
            }
        }
    }
    Ok(outcome)
}

#[allow(clippy::too_many_arguments)]
fn request_audit_corrections(
    client: &dyn LlmClient,
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
            subtrans_core::report_line!(
                out,
                "translation.reformat",
                serde_json::json!({"audit": audit_name, "response_reformat": true}),
                "translation {audit_name} response_reformat=true"
            );
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

fn request(
    client: &dyn LlmClient,
    cfg: &TranslationConfig,
    api_key: Option<&str>,
    model: &str,
    prompt: &str,
    max_output_tokens: u32,
) -> Result<String> {
    client.complete(&LlmCompletion {
        api: match cfg.provider {
            LlmProvider::Ollama => LlmApi::Ollama,
            LlmProvider::OpenaiCompatible => LlmApi::OpenaiCompatible,
        },
        base_url: &cfg.base_url,
        model,
        api_key,
        prompt,
        max_output_tokens,
        max_response_bytes: cfg.max_response_bytes,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::TranslationConfig;
    use anyhow::bail;

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

    #[test]
    fn unresolved_review_emits_subtitle_blocked_only_on_the_json_channel() {
        struct Fail;
        impl LlmClient for Fail {
            fn complete(
                &self,
                _request: &subtrans_core::remote::LlmCompletion<'_>,
            ) -> Result<String> {
                bail!("scripted failure")
            }
            fn probe(&self, _request: &subtrans_core::remote::LlmProbe<'_>) -> Result<String> {
                Ok(String::new())
            }
        }

        let mut cfg = config();
        cfg.alignment_check = false;
        cfg.consistency_check = false;
        cfg.max_retries = 0;

        let _human = subtrans_core::report::capture(false);
        let error = translate(&cues(1), &cfg, &Fail, "Show/episode.mkv").unwrap_err();
        assert!(error.to_string().contains("refusing to publish"));
        let human_lines = subtrans_core::report::captured();
        assert!(
            human_lines
                .iter()
                .any(|(_, line)| line.contains("translation review_required index=1"))
        );
        assert!(
            human_lines
                .iter()
                .all(|(_, line)| !line.contains("subtitle.blocked"))
        );
        drop(_human);

        let _json = subtrans_core::report::capture(true);
        let _ = translate(&cues(1), &cfg, &Fail, "Show/episode.mkv").unwrap_err();
        let blocked = subtrans_core::report::captured()
            .into_iter()
            .filter_map(|(_, line)| serde_json::from_str::<serde_json::Value>(&line).ok())
            .find(|value| value["event"] == "subtitle.blocked")
            .expect("json channel emits subtitle.blocked");
        assert_eq!(blocked["video"], "Show/episode.mkv");
        assert!(
            blocked["reason"]
                .as_str()
                .unwrap()
                .split(',')
                .any(|reason| reason == "primary_translation_failed")
        );
        assert_eq!(blocked["index"], 1);
    }
}
