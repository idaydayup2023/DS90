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
use crate::config::{FallbackEngine, LlmProvider, TranslationConfig};

use super::quality::{
    is_target_script_ratio_concern, target_text_is_degenerate, translation_concerns,
    validate_translation_quality,
};
use super::resp_cache::{ResponseCache, summary_line};
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

/// Upper bound on the tag-stripped length of a cue that still counts as a
/// "short line" for the stubborn-cue profile. The three confirmed death
/// cases (station 2026-11-10, item-5 cue 527 family) are far below this.
const STUBBORN_PROFILE_MAX_STRIPPED_CHARS: usize = 120;

/// One request endpoint: either the primary `[translation]` engine or the
/// stubborn-cue fallback. `max_output_tokens` deliberately stays a
/// per-request argument (the rescue arm widens it for a single cue); the
/// endpoint identity and its budget limits belong to the engine.
#[derive(Debug)]
struct Engine<'a> {
    provider: &'a LlmProvider,
    base_url: &'a str,
    model: &'a str,
    api_key: Option<&'a str>,
    max_retries: u32,
    max_response_bytes: usize,
    disable_thinking: bool,
}

impl<'a> Engine<'a> {
    fn primary(cfg: &'a TranslationConfig, api_key: Option<&'a str>) -> Self {
        Self {
            provider: &cfg.provider,
            base_url: &cfg.base_url,
            model: &cfg.model,
            api_key,
            max_retries: cfg.max_retries,
            max_response_bytes: cfg.max_response_bytes,
            disable_thinking: cfg.disable_thinking,
        }
    }

    /// Primary endpoint with an explicit model, for the review legs that may
    /// name their own `alignment_model` / `consistency_model`.
    fn primary_with_model(
        cfg: &'a TranslationConfig,
        api_key: Option<&'a str>,
        model: &'a str,
    ) -> Self {
        let mut engine = Self::primary(cfg, api_key);
        engine.model = model;
        engine
    }

    fn fallback(fallback: &'a FallbackEngine, api_key: Option<&'a str>) -> Self {
        Self {
            provider: &fallback.provider,
            base_url: &fallback.base_url,
            model: &fallback.model,
            api_key,
            max_retries: fallback.max_retries,
            max_response_bytes: fallback.max_response_bytes,
            // The rescue route is provisioned as an Ollama translategemma,
            // whose branch pins `"think": false` unconditionally, and
            // `FallbackEngine` deliberately carries no knob of its own: the
            // rescue behavior must stay frozen while the primary route is
            // tuned. Revisit if a fallback is ever pointed at an
            // OpenAI-compatible endpoint.
            disable_thinking: false,
        }
    }
}

/// The fallback endpoint resolved once per run: its own HTTP client (own
/// timeout budget, so a slow fallback never borrows the primary one) and
/// its API key (resolved eagerly: a missing key must fail at start, not
/// halfway through a burn).
#[derive(Debug)]
struct FallbackRoute {
    client: Client,
    api_key: Option<String>,
}

/// Everything a translation request needs beyond prompt and parser: the
/// primary client and credentials, the configuration, the shared response
/// cache, and the optional stubborn-cue fallback route. Bundled so the
/// batch loop passes one context instead of a nine-argument signature.
#[derive(Debug)]
struct RequestCtx<'a> {
    client: &'a Client,
    api_key: Option<&'a str>,
    cfg: &'a TranslationConfig,
    cache: &'a ResponseCache,
    fallback: Option<(&'a FallbackEngine, &'a FallbackRoute)>,
}

/// 日志用的短引用：按**字符**截断（CJK 一字一 char，不会像字节截断那样劈开多字节字符），
/// 超长补 `…`。只服务诊断输出，不参与任何判据。
fn ellipsis(text: &str, max_chars: usize) -> String {
    let mut out: String = text.chars().take(max_chars).collect();
    if text.chars().count() > max_chars {
        out.push('…');
    }
    out
}

/// Pure-rule pre-check for the stubborn empty-response profile (station
/// 2026-11-10 death-case family: Qwen answers these with a reasoning loop
/// that burns the whole token window, while translategemma:4b answers 3/3
/// correctly). A cue matches when ALL of the following hold, no model call
/// involved:
/// * it contains at least one complete `<i>…</i>` italic span,
/// * after stripping markup it has at least two `- ` speaker lines,
/// * the stripped text is a short line (see [`STUBBORN_PROFILE_MAX_STRIPPED_CHARS`]).
///
/// The pins `matches_stubborn_profile_rejects_item5_cue_419_and_429` keep
/// the two cues the primary engine rescued correctly on the primary route.
fn matches_stubborn_profile(text: &str) -> bool {
    let lower = text.to_ascii_lowercase();
    let opens = lower.matches("<i>").count();
    if opens == 0 || opens != lower.matches("</i>").count() {
        return false;
    }
    let stripped = strip_markup(text);
    let lines: Vec<&str> = stripped
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect();
    if lines.len() < 2 {
        return false;
    }
    lines.iter().filter(|line| line.starts_with('-')).count() >= 2
        && stripped.chars().count() <= STUBBORN_PROFILE_MAX_STRIPPED_CHARS
}

/// Drop `<…>` tags and `{…}` override blocks so the profile can measure the
/// spoken text itself. Deliberately forgiving: unbalanced brackets just stop
/// suppressing characters.
fn strip_markup(text: &str) -> String {
    let mut output = String::with_capacity(text.len());
    let mut inside = false;
    for ch in text.chars() {
        match ch {
            '<' | '{' => inside = true,
            '>' | '}' => inside = false,
            _ if !inside => output.push(ch),
            _ => {}
        }
    }
    output
}

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
    /// 本批是否已经为「退化修正文」重问过一轮。退化只给**一轮**机会
    /// （站长 2026-11-14 批复②：重试一轮 → 仍退化则回退翻译腿初稿并标 review 待核），
    /// 标志位就是这一轮的闸门，防重问无限循环。
    degenerate_retried: bool,
}

/// 占比闸逮住、且形态属「退化修正文」的一条审校回包（判据见 `quality::target_text_is_degenerate`）。
/// 带上 `position` 与退化文本本身：重问一轮仍退化时，才判得出「回退初稿」还是「真漏翻判红」。
#[derive(Debug)]
struct AlignmentDegenerate {
    index: u32,
    position: usize,
    correction: String,
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
    let cache = ResponseCache::new(cfg);
    // Resolve the fallback route once per run so a missing key or a broken
    // client fails at start instead of halfway through a burn. `None`
    // (the default when `[translation].fallback` is absent) keeps every
    // request on the primary engine, exactly like before this feature.
    let fallback_route = cfg
        .fallback
        .as_ref()
        .map(|fallback| -> Result<FallbackRoute> {
            Ok(FallbackRoute {
                client: Client::builder()
                    .timeout(Duration::from_secs(fallback.timeout_seconds))
                    .build()?,
                api_key: fallback.api_key()?,
            })
        })
        .transpose()?;
    if let Some(fallback) = &cfg.fallback {
        println!(
            "translation fallback_route armed model={:?} at {} (stubborn-cue profile)",
            fallback.model, fallback.base_url
        );
    }
    let ctx = RequestCtx {
        client: &client,
        api_key: api_key.as_deref(),
        cfg,
        cache: &cache,
        fallback: cfg.fallback.as_ref().zip(fallback_route.as_ref()),
    };
    let mut translated = BTreeMap::new();
    let mut pending_review = BTreeMap::new();

    for range in batch_ranges(cues, cfg.batch_size, cfg.max_batch_chars) {
        translate_range_adaptive(&ctx, cues, range, &mut translated, &mut pending_review)?;
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
    // Counters are per process, so this line is cumulative across the videos
    // one run has translated so far; it is only printed when a cache is
    // configured, leaving the disabled baseline log byte-identical.
    if let Some(summary) = summary_line(cache.dir()) {
        println!("translation {summary}");
    }
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
    ctx: &RequestCtx,
    cues: &[Cue],
    initial: Range<usize>,
    translated: &mut BTreeMap<u32, String>,
    pending_review: &mut BTreeMap<u32, PendingReview>,
) -> Result<()> {
    let cfg = ctx.cfg;
    let mut pending = VecDeque::from([initial]);
    while let Some(range) = pending.pop_front() {
        // Cue-level routing (station 2026-11-10 engine-swap landing order):
        // positions matching the stubborn empty-response profile leave the
        // batch BEFORE any primary request is issued; each gets one dedicated
        // fallback-engine request instead. Positions already translated (an
        // earlier leg of this loop, or an earlier half of a re-queued split)
        // drop out of the want set, so nothing is ever requested or inserted
        // twice. Without a `[translation].fallback` section the want set is
        // the open range and every prompt is byte-identical to the pre-
        // feature behaviour, keeping existing response caches warm.
        let open: Vec<usize> = range
            .clone()
            .filter(|position| !translated.contains_key(&cues[*position].index))
            .collect();
        if open.is_empty() {
            continue;
        }
        let stubborn: BTreeSet<usize> = if ctx.fallback.is_some() {
            open.iter()
                .copied()
                .filter(|position| matches_stubborn_profile(&cues[*position].text))
                .collect()
        } else {
            BTreeSet::new()
        };
        if ctx.fallback.is_some() {
            for position in &stubborn {
                translate_stubborn_cue(ctx, cues, *position, translated, pending_review)?;
            }
        }
        let want: Vec<usize> = open
            .iter()
            .copied()
            .filter(|position| !stubborn.contains(position))
            .collect();
        if want.is_empty() {
            continue;
        }
        let want_set: BTreeSet<usize> = want.iter().copied().collect();
        let prompt = build_prompt_wanting(cues, range.clone(), cfg, &want_set)?;
        let expected: Vec<Cue> = want
            .iter()
            .map(|position| cues[*position].clone())
            .collect();
        let context = prompt_context_range(range.clone(), cfg.context_cues);
        let ignored_context_indices: BTreeSet<u32> = cues[context]
            .iter()
            .filter(|cue| {
                !want_set
                    .iter()
                    .any(|position| cues[*position].index == cue.index)
            })
            .map(|cue| cue.index)
            .collect();
        // The response cache only stores what this strict parser accepts, and
        // a hit is parsed again below exactly like a live response.
        let accepts = |response: &str| -> bool {
            parse_valid_indices(response, &expected, &ignored_context_indices)
                .is_ok_and(|values| !values.is_empty())
        };
        let engine = Engine::primary(cfg, ctx.api_key);
        let request_and_validate = || {
            let response = request(
                ctx.client,
                ctx.cache,
                &engine,
                &prompt,
                cfg.max_output_tokens,
                &accepts,
            )?;
            parse_valid_indices(&response, &expected, &ignored_context_indices)
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
        let result = if want.len() == 1 {
            retry(engine.max_retries, request_and_validate)
        } else {
            retry(engine.max_retries, || {
                request(
                    ctx.client,
                    ctx.cache,
                    &engine,
                    &prompt,
                    cfg.max_output_tokens,
                    &accepts,
                )
            })
            .and_then(|response| {
                parse_valid_indices(&response, &expected, &ignored_context_indices)
            })
            .and_then(|values| {
                if values.is_empty() {
                    bail!("translation response contains no requested cue indices");
                }
                Ok(values)
            })
        };
        match result {
            Ok(values) => {
                let missing: Vec<Range<usize>> = want
                    .iter()
                    .copied()
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
            Err(_) if want.len() > 1 => {
                let midpoint = range.start + range.len() / 2;
                pending.push_front(midpoint..range.end);
                pending.push_front(range.start..midpoint);
            }
            Err(error) => {
                let cue = &cues[want[0]];
                // One widened rescue request before conceding: the empty
                // response cluster survived every configured retry at the
                // normal token window, so widen the window exactly once
                // (a single request, no retry loop) for this one cue.
                let rescue = request(
                    ctx.client,
                    ctx.cache,
                    &engine,
                    &prompt,
                    PRIMARY_RESCUE_MAX_OUTPUT_TOKENS,
                    &accepts,
                )
                .and_then(|response| {
                    parse_valid_indices(&response, &expected, &ignored_context_indices)
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

/// The fallback leg for one profile-matched cue: same prompt shape and the
/// same strict parser as the primary single-cue path, but the endpoint, key,
/// retries and token window come from `[translation.fallback]`. Deliberately
/// no primary-engine rescue afterwards — the 2026-11-10 direct probes showed
/// the primary answers these cues only with a window-consuming reasoning
/// loop, so re-asking it after a failed fallback would burn minutes to fail
/// the same way. A failed fallback cue keeps its original text and joins the
/// mandatory review queue, exactly like a failed primary single.
fn translate_stubborn_cue(
    ctx: &RequestCtx,
    cues: &[Cue],
    position: usize,
    translated: &mut BTreeMap<u32, String>,
    pending_review: &mut BTreeMap<u32, PendingReview>,
) -> Result<()> {
    let (fallback, route) = ctx
        .fallback
        .expect("the stubborn route is only entered with a configured fallback");
    let cfg = ctx.cfg;
    let cue = &cues[position];
    let index = cue.index;
    let prompt = build_prompt(cues, position..position + 1, cfg)?;
    let expected = [cue.clone()];
    let context = prompt_context_range(position..position + 1, cfg.context_cues);
    let ignored_context_indices: BTreeSet<u32> = cues[context]
        .iter()
        .filter(|item| item.index != index)
        .map(|item| item.index)
        .collect();
    let accepts = |response: &str| -> bool {
        parse_valid_indices(response, &expected, &ignored_context_indices)
            .is_ok_and(|values| values.contains_key(&index))
    };
    let engine = Engine::fallback(fallback, route.api_key.as_deref());
    println!(
        "translation fallback_route index={} action=fallback_request model={:?} base_url={} max_tokens={}",
        index, fallback.model, fallback.base_url, fallback.max_output_tokens
    );
    let result = retry(engine.max_retries, || {
        let response = request(
            &route.client,
            ctx.cache,
            &engine,
            &prompt,
            fallback.max_output_tokens,
            &accepts,
        )?;
        parse_valid_indices(&response, &expected, &ignored_context_indices)
            .with_context(|| format!("raw_model_response={}", log_preview(&response)))
            .and_then(|values| match values.get(&index) {
                Some(text) => Ok(text.clone()),
                None => bail!("fallback response omitted cue index {index}"),
            })
    });
    match result {
        Ok(text) => {
            println!(
                "translation fallback_route index={} action=fallback_request result=ok",
                index
            );
            if translated.insert(index, text).is_some() {
                bail!("translation batch produced duplicate cue index {index}");
            }
        }
        Err(error) => {
            translated.insert(index, single_line(&cue.text));
            let primary_error = format!("{error:#}");
            queue_mandatory_review(
                pending_review,
                cue,
                "fallback_translation_failed",
                Some(primary_error.clone()),
            );
            eprintln!(
                "translation review_required index={} attempts={} reason=fallback_translation_failed error={primary_error}",
                index,
                fallback.max_retries.saturating_add(1)
            );
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
                // 确定性 4xx（鉴权／请求体被拒）重打一百遍也是同一个 400：当场交出错误，
                // 不进退避重试（2026-11-14 E04 alignment 段：8 分钟 1539 发同形 400）。
                if is_deterministic_rejection(&error) {
                    return Err(error);
                }
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
    let want: BTreeSet<usize> = core.clone().collect();
    build_prompt_wanting(cues, core, cfg, &want)
}

/// [`build_prompt`] with an explicit set of positions to ask for inside
/// `core`. The stubborn-cue route drops profile-matched cues from a batch's
/// want set while keeping them as read-only context lines. When `want`
/// equals `core` the prompt is byte-identical to the plain form, so the
/// primary response cache of every existing batch stays warm.
fn build_prompt_wanting(
    cues: &[Cue],
    core: Range<usize>,
    cfg: &TranslationConfig,
    want: &BTreeSet<usize>,
) -> Result<String> {
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
            translate: want.contains(&(context_start + offset)),
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
                degenerate_retried: false,
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
        // The indices this batch must receive a correction for: the strict
        // `missing_required_corrections` check below treats anything less as
        // a failed round, so the cache gate must demand the same coverage.
        let mandatory: BTreeSet<u32> = expected
            .iter()
            .filter(|index| pending_review.contains_key(index))
            .copied()
            .collect();
        let result = request_audit_corrections(
            client,
            cfg,
            api_key,
            model,
            &prompt,
            cfg.alignment_max_output_tokens,
            &expected,
            &mandatory,
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
                        degenerate_retried: task.degenerate_retried,
                    });
                    pending.push_front(AlignmentTask {
                        positions: task.positions[..midpoint].to_vec(),
                        degenerate_retried: task.degenerate_retried,
                    });
                    continue;
                }
                if !missing_required.is_empty() {
                    bail!(
                        "review model omitted mandatory correction for cue indices {missing_required:?}"
                    );
                }
                let mut degenerate: Vec<AlignmentDegenerate> = Vec::new();
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
                        // 站长 2026-11-14 批复②：审校腿交回**退化修正文**（非空、但零目标语种
                        // 字符，实测形态就是 `。`）时，不再让整片 rc=1，改走一轮重问 + 回退
                        // 翻译腿初稿并标 review 待核。界分线（本 PR 生死线）：
                        //   · concerns 只有占比闸这一条 **且** 修正文零汉字 ⇒ 退化，进重问/降级面；
                        //   · concerns 混有其它判据，或占比落在 0 < ratio < 0.150（真·低质译文形态）
                        //     ⇒ 判据一字未动，照旧当场判红。
                        if concerns
                            .iter()
                            .all(|concern| is_target_script_ratio_concern(concern))
                            && target_text_is_degenerate(&correction, &cfg.target_language)
                        {
                            degenerate.push(AlignmentDegenerate {
                                index,
                                position,
                                correction: correction.clone(),
                            });
                            continue;
                        }
                        // 取证上下文（2026-11-14 Zero.Day E04 c365 案）：占比闸只报比值，
                        // 分不出「修正文真不合格」与「审校回包 index 与文本错位」。
                        // 引擎实测同形两案：c365 的修正文 `轴心猎鹰，LD，Alpha India November。`
                        // 按本 cue 源文判 concerns 为空（PR #27 的豁免生效），按**相邻 cue 源文**
                        // 判恰好打出同一条 `target_chinese_script_ratio_0.148_below_0.150`。
                        // 故把闸**实际看到的**源文与修正文一并落日志，一次跑批即可定性。
                        // 纯诊断输出：判据、阈值、豁免面一字未动。
                        let neighbours: Vec<String> = [position.saturating_sub(1), position + 1]
                            .into_iter()
                            .filter(|&p| p < cues.len())
                            .map(|p| format!("{}:{}", cues[p].index, ellipsis(&cues[p].text, 60)))
                            .collect();
                        bail!(
                            "review model returned a questionable final correction for cue {index}: {} \
                             judged_source={} correction={} neighbours={}",
                            concerns.join(","),
                            ellipsis(&cues[position].text, 120),
                            ellipsis(&correction, 120),
                            neighbours.join(" | ")
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
                // 退化修正文（站长 2026-11-14 批复②）：先给**一轮**重问。这一问必须真问到模型
                // ——含退化修正文的审校回包不入缓存（见 `audit_response_is_cachable`），否则
                // 重问只会把同一发 `。` 从缓存里再取一次，等于没重问。
                if !degenerate.is_empty() && !task.degenerate_retried {
                    let indices: Vec<u32> = degenerate.iter().map(|item| item.index).collect();
                    eprintln!(
                        "translation review_check degenerate_correction_retry=true indices={indices:?} action=reask_same_prompt reason=review_degenerate_correction"
                    );
                    pending.push_front(AlignmentTask {
                        positions: task.positions.clone(),
                        degenerate_retried: true,
                    });
                    continue;
                }
                // 重问一轮仍退化 ⇒ 回退翻译腿初稿并标 review 待核（quality_log 落痕）。
                // 但初稿自己也是零目标语种字符（真漏翻形态）时不放行：退化面不得给真漏翻洗白，
                // 照旧当场判红 —— 这条界线是本 PR 的生死线，测试 `degenerate_*` 两组钉住。
                for item in degenerate {
                    let AlignmentDegenerate {
                        index,
                        position,
                        correction,
                    } = item;
                    let current = translations
                        .get(&index)
                        .cloned()
                        .unwrap_or_else(|| single_line(&cues[position].text));
                    let kept_concerns = translation_concerns(
                        &cues[position].text,
                        &current,
                        &cfg.target_language,
                        cfg.min_target_script_ratio,
                    );
                    let kept_is_untranslated =
                        target_text_is_degenerate(&current, &cfg.target_language)
                            || kept_concerns.iter().any(|concern| {
                                concern == "empty_translation"
                                    || is_target_script_ratio_concern(concern)
                            });
                    if kept_is_untranslated {
                        // 双腿同退化 ⇒ 先做**一次定向重问**（单 cue＋禁合并约束，站长 2026-11-14 批②）。
                        // 重问仍拿不到目标语种文本才判红：真漏翻的生死线一个字都不放宽。
                        match targeted_reask_single_cue(client, cfg, api_key, cues, position) {
                            Ok(reasked)
                                if !target_text_is_degenerate(&reasked, &cfg.target_language)
                                    && translation_concerns(
                                        &cues[position].text,
                                        &reasked,
                                        &cfg.target_language,
                                        cfg.min_target_script_ratio,
                                    )
                                    .is_empty() =>
                            {
                                eprintln!(
                                    "translation review_check retranslated_index={index} action=targeted_single_cue_reask constraint=no_merge reason=review_degenerate_correction result=ok"
                                );
                                translations.insert(index, reasked.clone());
                                let trigger = pending_review.remove(&index);
                                let candidate_before_review = trigger
                                    .as_ref()
                                    .map(|value| value.candidate.clone())
                                    .unwrap_or_else(|| current.clone());
                                let primary_error = trigger
                                    .as_ref()
                                    .and_then(|value| value.primary_error.clone());
                                let mut reasons: Vec<String> = trigger
                                    .as_ref()
                                    .map(|value| value.reasons.iter().cloned().collect())
                                    .unwrap_or_else(|| {
                                        vec!["review_model_quality_correction".to_owned()]
                                    });
                                reasons
                                    .push("review_degenerate_correction_retranslated".to_owned());
                                outcome.quality_log.push(TranslationQualityRecord {
                                    cue_index: index,
                                    source: single_line(&cues[position].text),
                                    candidate_before_review,
                                    reviewed_translation: reasked,
                                    reasons,
                                    primary_error,
                                    translation_model: cfg.model.clone(),
                                    review_model: model.to_owned(),
                                });
                                // 重问救回来＝这一枚既不是回退初稿也不算 unresolved，
                                // 直接进下一条，别落到下面的 unresolved 记账面。
                                continue;
                            }
                            Ok(reasked) => bail!(
                                "review model returned a degenerate final correction for cue {index} \
                                 (correction={} kept_translation={}) and the translation leg left the cue untranslated: {}; \
                                 targeted re-ask left cue {index} untranslated: reask_text={}",
                                ellipsis(&correction, 60),
                                ellipsis(&current, 60),
                                kept_concerns.join(","),
                                ellipsis(&reasked, 60)
                            ),
                            Err(reask_error) => bail!(
                                "review model returned a degenerate final correction for cue {index} \
                                 (correction={} kept_translation={}) and the translation leg left the cue untranslated: {}; targeted re-ask failed: {reask_error:#}",
                                ellipsis(&correction, 60),
                                ellipsis(&current, 60),
                                kept_concerns.join(",")
                            ),
                        }
                    }
                    outcome.unresolved = outcome.unresolved.saturating_add(1);
                    let trigger = pending_review.remove(&index);
                    let candidate_before_review = trigger
                        .as_ref()
                        .map(|value| value.candidate.clone())
                        .unwrap_or_else(|| current.clone());
                    let primary_error = trigger
                        .as_ref()
                        .and_then(|value| value.primary_error.clone());
                    let mut reasons: Vec<String> = trigger
                        .as_ref()
                        .map(|value| value.reasons.iter().cloned().collect())
                        .unwrap_or_else(|| vec!["review_model_quality_correction".to_owned()]);
                    reasons.push("review_degenerate_correction_unresolved".to_owned());
                    outcome.quality_log.push(TranslationQualityRecord {
                        cue_index: index,
                        source: single_line(&cues[position].text),
                        candidate_before_review,
                        reviewed_translation: current,
                        reasons,
                        primary_error,
                        translation_model: cfg.model.clone(),
                        review_model: model.to_owned(),
                    });
                    eprintln!(
                        "translation review_check unresolved_index={index} action=keep_current_translation reason=review_degenerate_correction_unresolved degenerate_correction={}",
                        ellipsis(&correction, 60)
                    );
                }
            }
            // 确定性 4xx（鉴权／请求体被拒）：既不切批也不降级，当场把状态码与服务回包交出去。
            // 2026-11-14 E04 案：key 不对时整窗 400，切批＋逐批重烧在 8 分钟里打出 1539 发
            // 同形请求，而 keep_current_translation 把整段审校的空转盖成了"跑通了"。
            Err(error) if is_deterministic_rejection(&error) => {
                return Err(error.context(
                    "alignment aborted: the review service rejected the request (deterministic client error, no retry)",
                ));
            }
            Err(_) if task.positions.len() > 1 => {
                let midpoint = task.positions.len() / 2;
                println!(
                    "translation review_check split_indices={:?} at={midpoint}",
                    task.positions
                );
                pending.push_front(AlignmentTask {
                    positions: task.positions[midpoint..].to_vec(),
                    degenerate_retried: task.degenerate_retried,
                });
                pending.push_front(AlignmentTask {
                    positions: task.positions[..midpoint].to_vec(),
                    degenerate_retried: task.degenerate_retried,
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
/// empty-correction rescue round can run first. The audit response cache
/// gate builds on it — see [`audit_response_is_cachable`].
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

/// The audit response cache gate: an answer may reach disk only if this call
/// site would treat it as a success, not merely as a shape that parses.
///
/// Two classes of response fail here although `parse_consistency_envelope`
/// and even `validate_corrections` pass them:
///
/// * a structurally valid **zero-item envelope** (`{"corrections":[]}`, `[]`,
///   `{}`). For a batch holding a mandatory cue this is a failed round —
///   `audit_alignment`'s own `missing_required_corrections` check re-splits
///   it and eventually bails — so freezing one random empty answer into the
///   cache replays that death deterministically on every later burn
///   (2026-11-10, item-4 cue 429: 12+ consecutive empty answers, one shell
///   into the cache and no binary could save the file). Per the station
///   order an empty shell counts as a failed response and is never cached,
///   even for a batch without mandatory cues, so the next burn re-rolls it.
/// * a non-empty envelope that **omits a mandatory index**: the caller
///   treats it as the same failure as above, so it must not be frozen either.
///
/// Responses with empty-text items keep failing `validate_corrections` as
/// before, which keeps the empty-correction rescue round a genuine re-ask.
fn audit_response_is_cachable(
    response: &str,
    expected: &BTreeSet<u32>,
    mandatory: &BTreeSet<u32>,
    max_corrections: usize,
    target_language: &str,
) -> bool {
    let Ok(envelope) = parse_consistency_envelope(response) else {
        return false;
    };
    if envelope.corrections.is_empty() {
        return false;
    }
    match validate_corrections(envelope, expected, max_corrections) {
        Ok(corrections) => {
            // 退化修正文（`。` 这类零目标语种字符的回包）与空修正文同性质：**一次失败的回合
            // 不得冻进缓存**，否则 `audit_alignment` 为它安排的那一轮重问只会把同一发退化
            // 回包再取一次（2026-11-14 E04 c628 案）。
            if corrections
                .values()
                .any(|text| target_text_is_degenerate(text, target_language))
            {
                return false;
            }
            mandatory
                .iter()
                .all(|index| corrections.contains_key(index))
        }
        Err(_) => false,
    }
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
    mandatory: &BTreeSet<u32>,
    max_corrections: usize,
    audit_name: &str,
) -> Result<AuditResolution> {
    // Audit responses are cached only when `audit_response_is_cachable`
    // accepts them — the strict success test of this very call site, not
    // just a parseable shape — and re-checked on every replay, so a cache
    // can never freeze a failed round (empty corrections shell, or a shell
    // missing a mandatory correction) into a deterministic death across
    // burns; those rounds always re-ask the model for real.
    let accepts = |response: &str| -> bool {
        audit_response_is_cachable(
            response,
            expected,
            mandatory,
            max_corrections,
            &cfg.target_language,
        )
    };
    // The review legs always run on the primary engine (station 2026-11-10
    // landing order: the second-opinion surface stays untouched); they only
    // name their own model, never a different endpoint.
    let engine = Engine::primary_with_model(cfg, api_key, model);
    let cache = ResponseCache::new(cfg);
    let response = retry(cfg.max_retries, || {
        request(client, &cache, &engine, prompt, max_output_tokens, &accepts)
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
                    &cache,
                    &engine,
                    &repair_prompt,
                    max_output_tokens,
                    &accepts,
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
        request(client, &cache, &engine, prompt, max_output_tokens, &accepts)
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

/// Ask the model, through the response cache when one is configured.
///
/// `accept` is the same strict check the caller applies to the value it gets
/// back (translation envelope, corrections envelope, index coverage): an entry
/// is only stored after it passes, and an entry that no longer passes is
/// evicted and refetched rather than trusted. That keeps a corrupted,
/// truncated, or hand-edited file from pinning a batch to a bad answer, and it
/// means a cache hit never skips the parse a live response would have had to
/// survive.
/// 定向重问窗专用的「逐 cue 对齐、禁止合并」约束（站长 2026-11-14 批②）。
///
/// 病灶：从句续行形态的 cue（源文无句末标点、或从介词/连词起）被模型并进前一 cue，
/// 自己只剩一个孤立句号 `。`（E04 c628 与同形 c292 两枚，宽窗救援腿也照犯）。
///
/// **红线（站长钉死）**：这段文字只准出现在定向重问的请求里，严禁进主腿
/// `[translation]` 的 prompt —— 那是 cache_key 的输入面，动一下就是全片重译灾难。
/// 测试 `targeted_reask_constraint_never_reaches_the_main_leg_prompt` 钉住这条。
const TARGETED_REASK_CONSTRAINT: &str = "\n\nTranslate each requested cue on its own. \
Never merge a cue into a neighbouring cue: even when a cue is only a continuation clause of \
the previous one, it must receive its own complete translation instead of punctuation. \
Never answer a cue with punctuation or whitespace only.";

/// 定向重问一枚可疑 cue：单 cue 批 ＋ [`TARGETED_REASK_CONSTRAINT`]。
///
/// 只在「审校修正文退化 且 翻译腿初稿也退化」这一条路上走到这里。prompt 与主腿不同形
/// ⇒ 缓存 key 天然不同 ⇒ 老的坏 cache 复用不了，也不需要去改主腿 prompt。
/// 回包仍退化时**不入缓存**（`accept` 面拦掉），免得把 `。` 再钉一层。
fn targeted_reask_single_cue(
    client: &Client,
    cfg: &TranslationConfig,
    api_key: Option<&str>,
    cues: &[Cue],
    position: usize,
) -> Result<String> {
    let cue = &cues[position];
    let mut prompt = build_prompt(cues, position..position + 1, cfg)?;
    // 约束插在 cue 列表（`\n\n` 之后的 JSON 体）**之前**：模型先读到规则再看到要译的那一枚，
    // 而所有按「最后一个 `\n\n` 之后＝JSON 体」解析请求的工具面（含本模块测试的 `prompt_items`）
    // 照旧能用。
    match prompt.rfind("\n\n") {
        Some(at) => prompt.insert_str(at, TARGETED_REASK_CONSTRAINT),
        None => prompt.push_str(TARGETED_REASK_CONSTRAINT),
    }
    let engine = Engine::primary(cfg, api_key);
    let cache = ResponseCache::new(cfg);
    let expected = std::slice::from_ref(cue);
    let ignored: BTreeSet<u32> = BTreeSet::new();
    let target_language = cfg.target_language.clone();
    let index = cue.index;
    let accept = |response: &str| -> bool {
        parse_valid_indices(response, expected, &ignored)
            .map(|values| {
                values
                    .get(&index)
                    .is_some_and(|text| !target_text_is_degenerate(text, &target_language))
            })
            .unwrap_or(false)
    };
    let response = request(
        client,
        &cache,
        &engine,
        &prompt,
        cfg.max_output_tokens,
        &accept,
    )?;
    let values = parse_valid_indices(&response, expected, &ignored)
        .with_context(|| format!("raw_model_response={}", log_preview(&response)))?;
    let Some((_index, text)) = values.into_iter().next() else {
        bail!("targeted re-ask omitted cue {index}");
    };
    Ok(text)
}

fn request(
    client: &Client,
    cache: &ResponseCache,
    engine: &Engine,
    prompt: &str,
    max_output_tokens: u32,
    accept: &dyn Fn(&str) -> bool,
) -> Result<String> {
    // Engine identity (provider + base_url + model) enters the key, so the
    // primary and the fallback route share one cache directory without ever
    // colliding (station 2026-11-10 landing order, point 2).
    let key = cache.key_engine(engine.provider, engine.base_url, engine.model, prompt);
    cached_response(cache, key.as_deref(), accept, &|| {
        request_model(client, engine, prompt, max_output_tokens)
    })
}

/// The caching decision, split out so the "did we call the model again?"
/// behaviour can be tested without a network: `live` stands in for the HTTP
/// round trip and counts how often the cache forced it to run.
fn cached_response(
    cache: &ResponseCache,
    key: Option<&str>,
    accept: &dyn Fn(&str) -> bool,
    live: &dyn Fn() -> Result<String>,
) -> Result<String> {
    let Some(key) = key else {
        return live();
    };
    if let Some(cached) = cache.get(key) {
        if accept(&cached) {
            return Ok(cached);
        }
        cache.evict(key);
    }
    let response = live()?;
    if accept(&response) {
        cache.put(key, &response);
    }
    Ok(response)
}

/// Chat-completions request body for OpenAI-compatible endpoints, extracted
/// pure so the thinking-pin contract is asserted without a live server.
/// With `disable_thinking` set, the vLLM/SGLang-style `chat_template_kwargs`
/// switch pins server-side reasoning off: litellm gateways default it *on*,
/// and the chain-of-thought then consumes the whole `max_tokens` budget and
/// answers with an empty `content` (2026-11-11 full-library sweep, ten
/// empty-content events on one root cause; probe-verified one-shot fix).
fn chat_completions_body(
    model: &str,
    prompt: &str,
    max_output_tokens: u32,
    disable_thinking: bool,
) -> Value {
    let mut body = json!({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_output_tokens,
        "response_format": {"type": "json_object"}
    });
    if disable_thinking {
        body["chat_template_kwargs"] = json!({"thinking": false});
    }
    body
}

/// 模型服务对**这一发请求本身**的拒绝（HTTP 状态码 + 响应体头部）。
///
/// 两条用处：
///   1. 诊断：状态码与服务回包的头部一起报出来，不再只剩引擎自己那句
///      「rejected model」（任何非 2xx 都打同一句，把 litellm 的真实拒因整个丢掉）。
///   2. 重试面分流：[`is_deterministic_rejection`] 认出的那一类（鉴权／请求体被拒）
///      重打也是同一个结果，`retry` 与 `audit_alignment` 的切批/重问面一律绕行，当场报错。
///      429 与 5xx 属可重试类（限流／服务抖动），不进这一类。
#[derive(Debug)]
struct ModelRequestRejected {
    status: u16,
    model: String,
    base_url: String,
    body: String,
}

impl std::fmt::Display for ModelRequestRejected {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "translation service answered HTTP {} for model {:?} at {}: {}",
            self.status, self.model, self.base_url, self.body
        )
    }
}

impl std::error::Error for ModelRequestRejected {}

/// 这一类 4xx 是**确定性的**：同一发请求重打只会得到同一个状态码（鉴权没通、模型名/请求体
/// 不被接受、路径不存在）。站长 2026-11-14 批复③：不逐批重烧，fail-fast ＋ 当档显式报错。
fn is_deterministic_rejection(error: &anyhow::Error) -> bool {
    error
        .downcast_ref::<ModelRequestRejected>()
        .is_some_and(|rejection| {
            matches!(
                rejection.status,
                400 | 401 | 403 | 404 | 405 | 406 | 415 | 422
            )
        })
}

fn request_model(
    client: &Client,
    engine: &Engine,
    prompt: &str,
    max_output_tokens: u32,
) -> Result<String> {
    let model = engine.model;
    let (url, body, response_path): (String, Value, &[&str]) = match engine.provider {
        LlmProvider::Ollama => (
            endpoint(engine.base_url, "api/generate"),
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
            endpoint(engine.base_url, "chat/completions"),
            chat_completions_body(model, prompt, max_output_tokens, engine.disable_thinking),
            &["choices", "0", "message", "content"],
        ),
    };
    let mut request = client.post(url).json(&body);
    if let Some(key) = engine.api_key {
        request = request.bearer_auth(key);
    }
    let response = request
        .send()
        .with_context(|| {
            format!(
                "translation model request failed for model {model:?} at {}. Start/verify the configured service and model, check network/API-key settings, then run `subtrans doctor --config <CONFIG>`",
                engine.base_url
            )
        })?;
    // 状态码自己判：`error_for_status()` 会把响应体丢掉，而 4xx 的真拒因只写在体里
    // （2026-11-14 E04 alignment 案：litellm 回的是鉴权层的 `No connected db.`，
    // 引擎当时只会打印 "translation service rejected model …" 这句自己的话）。
    let status = response.status();
    if !status.is_success() {
        let mut head = Vec::new();
        response.take(1_024).read_to_end(&mut head)?;
        return Err(ModelRequestRejected {
            status: status.as_u16(),
            model: model.to_owned(),
            base_url: engine.base_url.to_owned(),
            body: ellipsis(&String::from_utf8_lossy(&head), 400),
        }
        .into());
    }
    let mut bytes = Vec::new();
    response
        .take(engine.max_response_bytes as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > engine.max_response_bytes {
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
    /// 可指定 HTTP 状态码的 mock 模型端点：`responder` 返回 `(status, 响应体)`。
    /// 确定性 4xx 的 fail-fast 面只有在这里才测得到（`llm_server` 只会回 200）。
    fn llm_server_http(
        responder: impl Fn(&Value) -> (u16, String) + Send + 'static,
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
                let (status, reply) = responder(&body);
                let reason = if status == 200 { "OK" } else { "REJECTED" };
                let http = format!(
                    "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    reply.len(),
                    reply
                );
                stream.write_all(http.as_bytes()).unwrap();
                stream.flush().unwrap();
            }
        });
        (base_url, seen)
    }

    /// 既有用例的 200-only 包装。
    fn llm_server(
        responder: impl Fn(&Value) -> String + Send + 'static,
    ) -> (String, Arc<Mutex<Vec<Value>>>) {
        llm_server_http(move |body| (200, responder(body)))
    }

    // ----- 确定性 4xx fail-fast（站长 2026-11-14 批复③）-----

    /// 鉴权／请求体被拒这一类 4xx：一发即止，不进 `max_retries` 退避重烧；错误里带上状态码与
    /// 服务回包头部（litellm 当时回的是 `No connected db.`，老错误串里一个字都看不到）。
    #[test]
    fn deterministic_4xx_fails_fast_and_reports_the_service_body() {
        let (base_url, seen) = llm_server_http(|_| {
            (
                400,
                r#"{"error":{"message":"No connected db.","type":"no_db_connection"}}"#.to_owned(),
            )
        });
        let mut cfg = config();
        cfg.base_url = base_url;
        cfg.timeout_seconds = 10;
        cfg.max_retries = 3;
        cfg.alignment_check = false;
        cfg.consistency_check = false;
        let error = translate(&cues(1), &cfg)
            .expect_err("确定性 400 必须报错，不得被 keep_current_translation 盖掉");
        let message = format!("{error:#}");
        assert!(message.contains("HTTP 400"), "{message}");
        assert!(message.contains("No connected db."), "{message}");
        assert!(
            error.downcast_ref::<ModelRequestRejected>().is_some(),
            "typed error 必须能被下钻出来：{message}"
        );
        // 3 发＝主腿 1 ＋ 宽窗救援 1 ＋ 审校腿 1，每腿都是**一发即止**；
        // max_retries=3 若生效，单腿就该打出 4 发（对照下面 429 那一发）。
        assert_eq!(seen.lock().unwrap().len(), 3);
    }

    /// 429 是限流不是确定性拒：重试面照旧保留（fail-fast 不许把该重烧的也掐掉）。
    #[test]
    fn rate_limited_429_is_still_retried() {
        let (base_url, seen) = llm_server_http(|_| {
            (
                429,
                r#"{"error":{"message":"Too Many Requests"}}"#.to_owned(),
            )
        });
        let mut cfg = config();
        cfg.base_url = base_url;
        cfg.timeout_seconds = 10;
        cfg.max_retries = 2;
        cfg.alignment_check = false;
        cfg.consistency_check = false;
        let error = translate(&cues(1), &cfg).expect_err("429 用尽重试预算后仍须报错");
        let message = format!("{error:#}");
        assert!(message.contains("HTTP 429"), "{message}");
        assert!(
            error.downcast_ref::<ModelRequestRejected>().is_some(),
            "{message}"
        );
        // 同一套腿（主腿＋救援＋审校），429 把 max_retries=2 的预算烧完＝7 发；
        // 这条与上一条成对，钉住"只放确定性 4xx 走 fail-fast"。
        assert_eq!(seen.lock().unwrap().len(), 7);
    }

    /// 审校段被确定性 400 拒时**不得切批、不得逐批重烧**（11-14 案：切批×逐批重烧在 8 分钟里
    /// 打出 1539 发同形 400，还把整段审校的空转掩盖成"跑通了"）。
    #[test]
    fn alignment_4xx_aborts_without_splitting_the_batch() {
        let (base_url, seen) = llm_server_http(|body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
                return (
                    400,
                    r#"{"error":{"message":"No connected db."}}"#.to_owned(),
                );
            }
            let translations: Vec<Value> = prompt_items(prompt)
                .iter()
                .filter(|item| item["translate"] == Value::Bool(true))
                .map(|item| {
                    let index = item["index"].as_u64().unwrap();
                    json!({ "index": index, "text": format!("第{index}行。") })
                })
                .collect();
            (200, ollama_reply(json!({ "translations": translations })))
        });
        let mut cfg = config();
        cfg.base_url = base_url;
        cfg.timeout_seconds = 10;
        cfg.max_retries = 2;
        cfg.alignment_check = true;
        cfg.consistency_check = false;
        let error = translate(&cues(10), &cfg)
            .expect_err("审校段被整窗 400 拒时必须当场报错，不得继续发布");
        let message = error.to_string();
        assert!(message.contains("alignment aborted"), "{message}");
        let review_requests = seen
            .lock()
            .unwrap()
            .iter()
            .filter(|body| body["prompt"].as_str().unwrap().contains("final-review"))
            .count();
        assert_eq!(review_requests, 1, "确定性 400 不得切批、不得逐批重烧");
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

    // ----- 退化修正文（站长 2026-11-14 批复②）：两组负控钉住界分线 -----

    /// 界分组之一（放行面）：审校腿交回 `。` 这种**退化修正文**——非空、但一个目标语种字符
    /// 都没有——不再让整片 rc=1：重问一轮，仍退化则回退翻译腿初稿并在 quality_log 标 review 待核。
    #[test]
    fn degenerate_review_correction_retries_then_keeps_the_draft() {
        let degenerate_rounds = Arc::new(AtomicUsize::new(0));
        let degenerate_seen = Arc::clone(&degenerate_rounds);
        let (base_url, _seen) = llm_server(move |body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
                let reviews_cue_one = prompt_items(prompt).iter().any(|item| {
                    item["review"] == Value::Bool(true) && item["index"].as_u64() == Some(1)
                });
                if reviews_cue_one {
                    degenerate_seen.fetch_add(1, Ordering::SeqCst);
                    return ollama_reply(json!({ "corrections": [{ "index": 1, "text": "。" }] }));
                }
                return ollama_reply(json!({ "corrections": [] }));
            }
            let translations: Vec<Value> = prompt_items(prompt)
                .iter()
                .filter(|item| item["translate"] == Value::Bool(true))
                .map(|item| {
                    let index = item["index"].as_u64().unwrap();
                    if index == 1 {
                        json!({ "index": 1, "text": "报告明天之前一定做完。" })
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
        // 占比闸按全站基准口径开起来（`config()` 的测试默认是 0.0＝闸关），
        // 退化修正文正是被这一条逮住的形态。
        cfg.min_target_script_ratio = 0.15;
        // 源文必须是真的可译句（`Line 1` 会被专名豁免面放过，逮不到占比闸）。
        let mut batch = cues(10);
        batch[0].text = "We must finish the report tomorrow.".to_owned();
        let outcome = translate(&batch, &cfg).expect(
            "a degenerate correction must not abort the video (station 2026-11-14, item 2)",
        );
        // 退化修正文既没顶掉初稿，也没炸片。
        assert_eq!(
            outcome.cues[0].text,
            "报告明天之前一定做完。\nWe must finish the report tomorrow."
        );
        // 只给**一轮**重问：同一批最多再问一次。
        assert_eq!(degenerate_rounds.load(Ordering::SeqCst), 2);
        let record = outcome
            .quality_log
            .iter()
            .find(|record| record.cue_index == 1)
            .expect("the degenerate correction must leave a review trail");
        assert_eq!(record.reviewed_translation, "报告明天之前一定做完。");
        assert!(
            record
                .reasons
                .iter()
                .any(|reason| reason == "review_degenerate_correction_unresolved")
        );
    }

    /// 界分组之二（判红面）：同一条 `。` 回包，若**翻译腿初稿本身就没翻**（零目标语种字符），
    /// 退化面不得给真漏翻洗白 —— 照旧当场判红。占比闸 0.150 一字未动。
    #[test]
    fn degenerate_review_correction_still_bails_when_the_draft_is_untranslated() {
        let (base_url, _seen) = llm_server(|body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
                let reviews_cue_one = prompt_items(prompt).iter().any(|item| {
                    item["review"] == Value::Bool(true) && item["index"].as_u64() == Some(1)
                });
                if reviews_cue_one {
                    return ollama_reply(json!({ "corrections": [{ "index": 1, "text": "。" }] }));
                }
                return ollama_reply(json!({ "corrections": [] }));
            }
            let translations: Vec<Value> = prompt_items(prompt)
                .iter()
                .filter(|item| item["translate"] == Value::Bool(true))
                .map(|item| {
                    let index = item["index"].as_u64().unwrap();
                    if index == 1 {
                        json!({ "index": 1, "text": "。" })
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
        cfg.min_target_script_ratio = 0.15;
        let mut batch = cues(10);
        batch[0].text = "We must finish the report tomorrow.".to_owned();
        let error = translate(&batch, &cfg)
            .expect_err("a degenerate correction over an untranslated draft must stay red");
        let message = error.to_string();
        assert!(
            message.contains("degenerate final correction for cue 1"),
            "{message}"
        );
        assert!(message.contains("left the cue untranslated"), "{message}");
    }

    /// 双腿同退化的第三条路（站长 2026-11-14 批②）：审校回 `。`、翻译腿初稿也是 `。`
    /// ⇒ 先做**一次定向重问**（单 cue＋禁合并约束）；重问拿到真译文就收，整片 rc=0。
    /// 同时钉两条形状：重问那一发**只问这一枚**（禁合并＝不许把邻句一起问），
    /// 而主腿那一发**不带约束串**（cache_key 输入面一字不动）。
    #[test]
    fn degenerate_review_correction_reasks_the_single_cue_without_merging() {
        let reasks = Arc::new(AtomicUsize::new(0));
        let reasks_seen = Arc::clone(&reasks);
        let (base_url, seen) = llm_server(move |body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
                let reviews_cue_one = prompt_items(prompt).iter().any(|item| {
                    item["review"] == Value::Bool(true) && item["index"].as_u64() == Some(1)
                });
                if reviews_cue_one {
                    return ollama_reply(json!({ "corrections": [{ "index": 1, "text": "。" }] }));
                }
                return ollama_reply(json!({ "corrections": [] }));
            }
            if prompt.contains(TARGETED_REASK_CONSTRAINT.trim_start()) {
                reasks_seen.fetch_add(1, Ordering::SeqCst);
                return ollama_reply(json!({
                    "translations": [{ "index": 1, "text": "明天媒体上会披露一些关于我的事。" }]
                }));
            }
            let translations: Vec<Value> = prompt_items(prompt)
                .iter()
                .filter(|item| item["translate"] == Value::Bool(true))
                .map(|item| {
                    let index = item["index"].as_u64().unwrap();
                    if index == 1 {
                        // 翻译腿初稿同形退化（E04 c628 案：从句续行被并进前一 cue，自己只剩孤句号）
                        json!({ "index": 1, "text": "。" })
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
        cfg.min_target_script_ratio = 0.15;
        let mut batch = cues(10);
        batch[0].text = "We must finish the report tomorrow.".to_owned();
        let outcome = translate(&batch, &cfg).expect("定向重问救回来的那一枚不得让整片 rc=1");
        assert_eq!(
            reasks.load(Ordering::SeqCst),
            1,
            "双腿退化只许问一发定向重问"
        );
        assert_eq!(
            outcome.cues[0].text,
            "明天媒体上会披露一些关于我的事。\nWe must finish the report tomorrow."
        );
        let record = outcome
            .quality_log
            .iter()
            .find(|record| record.cue_index == 1)
            .expect("重问救回来也要留 review 痕迹");
        assert_eq!(
            record.reviewed_translation,
            "明天媒体上会披露一些关于我的事。"
        );
        assert!(
            record
                .reasons
                .iter()
                .any(|reason| reason == "review_degenerate_correction_retranslated"),
            "{:?}",
            record.reasons
        );
        assert!(
            !record
                .reasons
                .iter()
                .any(|reason| reason.contains("unresolved")),
            "重问成功的这一枚不算回退初稿、也不算 unresolved：{:?}",
            record.reasons
        );

        let bodies = seen.lock().unwrap();
        let reask_prompts: Vec<&str> = bodies
            .iter()
            .filter(|body| {
                body["prompt"]
                    .as_str()
                    .is_some_and(|prompt| prompt.contains(TARGETED_REASK_CONSTRAINT.trim_start()))
            })
            .map(|body| body["prompt"].as_str().unwrap())
            .collect();
        assert_eq!(reask_prompts.len(), 1, "带约束的请求只准出现在重问窗");
        let requested: Vec<u64> = prompt_items(reask_prompts[0])
            .iter()
            .filter(|item| item["translate"] == Value::Bool(true))
            .map(|item| item["index"].as_u64().unwrap())
            .collect();
        assert_eq!(
            requested,
            vec![1],
            "定向重问是单 cue 批，禁合并＝不许捎上邻句"
        );
        let main_legs = bodies
            .iter()
            .filter(|body| {
                let prompt = body["prompt"].as_str().unwrap();
                !prompt.contains("final-review")
                    && !prompt.contains(TARGETED_REASK_CONSTRAINT.trim_start())
            })
            .count();
        assert!(main_legs >= 1, "主腿请求必须还在（未被重问窗顶掉）");
    }

    /// 生死线另一侧：定向重问**仍**只拿回 `。` ⇒ 照旧当场判红，不许借"重问过"洗白真漏翻。
    /// 错误串保留老文案（`degenerate final correction` ＋ `left the cue untranslated`），
    /// 另加一段重问读数，方便日后按枚取证。
    #[test]
    fn degenerate_review_correction_bails_when_the_targeted_reask_is_also_degenerate() {
        let reasks = Arc::new(AtomicUsize::new(0));
        let reasks_seen = Arc::clone(&reasks);
        let (base_url, _seen) = llm_server(move |body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
                let reviews_cue_one = prompt_items(prompt).iter().any(|item| {
                    item["review"] == Value::Bool(true) && item["index"].as_u64() == Some(1)
                });
                if reviews_cue_one {
                    return ollama_reply(json!({ "corrections": [{ "index": 1, "text": "。" }] }));
                }
                return ollama_reply(json!({ "corrections": [] }));
            }
            if prompt.contains(TARGETED_REASK_CONSTRAINT.trim_start()) {
                reasks_seen.fetch_add(1, Ordering::SeqCst);
            }
            let translations: Vec<Value> = prompt_items(prompt)
                .iter()
                .filter(|item| item["translate"] == Value::Bool(true))
                .map(|item| {
                    let index = item["index"].as_u64().unwrap();
                    if index == 1 {
                        json!({ "index": 1, "text": "。" })
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
        cfg.min_target_script_ratio = 0.15;
        let mut batch = cues(10);
        batch[0].text = "We must finish the report tomorrow.".to_owned();
        let error = translate(&batch, &cfg).expect_err("重问仍退化＝真漏翻，照旧判红");
        let message = error.to_string();
        assert!(
            message.contains("degenerate final correction for cue 1"),
            "{message}"
        );
        assert!(message.contains("left the cue untranslated"), "{message}");
        assert!(
            message.contains("targeted re-ask left cue 1 untranslated"),
            "{message}"
        );
        assert_eq!(reasks.load(Ordering::SeqCst), 1);
    }

    /// 红线（站长 2026-11-14 批②钉死）：禁合并约束串只准进重问窗，
    /// **严禁进主腿 `[translation]` 的 prompt** —— 那是 cache_key 的输入面，
    /// 动一下就是全片重译灾难（老 cache 全体 miss）。
    #[test]
    fn targeted_reask_constraint_never_reaches_the_main_leg_prompt() {
        let batch = cues(6);
        let cfg = config();
        let constraint = TARGETED_REASK_CONSTRAINT.trim_start();
        assert!(!constraint.is_empty());
        for range in [0..6, 2..3, 5..6] {
            let prompt = build_prompt(&batch, range, &cfg).unwrap();
            assert!(
                !prompt.contains(constraint),
                "主腿 prompt 被重问约束污染了（cache_key 会全体漂移）：{prompt}"
            );
        }
        // 约束是**附加**的独立指令串：主腿模板里找不到它的一个字，
        // 也就是说把主腿 prompt 原样拿来也不会带上重问规则（反向确认没被写进模板）。
        let main_prompt = build_prompt(&batch, 0..6, &cfg).unwrap();
        assert!(constraint.len() > 40);
        assert!(!main_prompt.contains(&constraint[..40]));
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

    fn cached_config(dir: &std::path::Path) -> TranslationConfig {
        toml::from_str(&format!(
            r#"
provider = "ollama"
base_url = "http://127.0.0.1:11434"
model = "translategemma:4b"
source_language = "English"
source_language_code = "en"
target_language = "Simplified Chinese"
target_language_code = "zh-CN"
cache_dir = "{}"
"#,
            dir.display()
        ))
        .unwrap()
    }

    fn accepted(response: &str) -> bool {
        parse_aligned(response, &cues(1)).is_ok()
    }

    const GOOD: &str = r#"{"translations":[{"index":1,"text":"你好"}]}"#;

    #[test]
    fn a_stored_response_is_replayed_without_calling_the_model() {
        let root = tempfile::tempdir().unwrap();
        let cfg = cached_config(root.path());
        let cache = ResponseCache::new(&cfg);
        let key = cache.key(&cfg, &cfg.model, "PROMPT").unwrap();
        let calls = std::cell::Cell::new(0u32);
        let live = || {
            calls.set(calls.get() + 1);
            Ok(GOOD.to_owned())
        };
        for _ in 0..3 {
            assert_eq!(
                cached_response(&cache, Some(&key), &accepted, &live).unwrap(),
                GOOD
            );
        }
        assert_eq!(calls.get(), 1, "a hit must not reach the model");
        assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 1);
    }

    #[test]
    fn a_different_endpoint_model_or_prompt_is_never_a_hit() {
        let root = tempfile::tempdir().unwrap();
        let cfg = cached_config(root.path());
        let cache = ResponseCache::new(&cfg);
        let accept = |response: &str| response.starts_with('{');
        let calls = std::cell::Cell::new(0u32);
        let live = || {
            calls.set(calls.get() + 1);
            Ok("{\"corrections\":[]}".to_owned())
        };
        let stored = cache.key(&cfg, &cfg.model, "PROMPT").unwrap();
        cached_response(&cache, Some(&stored), &accept, &live).unwrap();
        cached_response(&cache, Some(&stored), &accept, &live).unwrap();
        assert_eq!(
            live_count(&calls),
            1,
            "identical request replays from cache"
        );
        // Each part of the key alone must be able to force a fresh request.
        let mut other_url = cfg.clone();
        other_url.base_url = "http://127.0.0.1:8888/v1".into();
        let key = cache.key(&other_url, &cfg.model, "PROMPT");
        cached_response(&cache, key.as_deref(), &accept, &live).unwrap();
        assert_eq!(
            live_count(&calls),
            2,
            "repointing the endpoint replays nothing"
        );

        let key = cache.key(&cfg, "qwen3:8b", "PROMPT");
        cached_response(&cache, key.as_deref(), &accept, &live).unwrap();
        assert_eq!(live_count(&calls), 3, "another model replays nothing");

        let key = cache.key(&cfg, &cfg.model, "ANOTHER PROMPT");
        cached_response(&cache, key.as_deref(), &accept, &live).unwrap();
        assert_eq!(live_count(&calls), 4, "another prompt replays nothing");

        let mut other_provider = cfg.clone();
        other_provider.provider = crate::config::LlmProvider::OpenaiCompatible;
        let key = cache.key(&other_provider, &cfg.model, "PROMPT");
        cached_response(&cache, key.as_deref(), &accept, &live).unwrap();
        assert_eq!(live_count(&calls), 5, "another provider replays nothing");
    }

    #[test]
    fn chat_completions_body_pins_thinking_off_only_when_disable_thinking_is_set() {
        // The empty-content death family (2026-11-11): litellm defaults
        // thinking on, the chain-of-thought burns max_tokens, content comes
        // back empty. The contract is exactly one key, and only when asked.
        let off = chat_completions_body("m", "PROMPT", 4096, false);
        assert!(
            off.get("chat_template_kwargs").is_none(),
            "default config must keep requests byte-identical to before the knob existed"
        );
        let on = chat_completions_body("m", "PROMPT", 4096, true);
        assert_eq!(
            on["chat_template_kwargs"],
            serde_json::json!({"thinking": false}),
            "the probe-verified vLLM/SGLang switch must be sent verbatim"
        );
        // Everything else the endpoint needs stays untouched by the switch.
        for key in [
            "model",
            "messages",
            "temperature",
            "max_tokens",
            "response_format",
        ] {
            assert_eq!(on[key], off[key], "{key} must not drift with the switch");
        }
    }

    fn live_count(calls: &std::cell::Cell<u32>) -> u32 {
        calls.get()
    }

    #[test]
    fn a_cached_payload_that_no_longer_parses_is_evicted_not_trusted() {
        let root = tempfile::tempdir().unwrap();
        let cfg = cached_config(root.path());
        let cache = ResponseCache::new(&cfg);
        let key = cache.key(&cfg, &cfg.model, "PROMPT").unwrap();
        // Poison the entry: something that is not a translation envelope is
        // sitting where a good answer used to be (truncated write, hand edit).
        std::fs::write(cache.path_for(&key).unwrap(), "not json at all").unwrap();
        let calls = std::cell::Cell::new(0u32);
        let live = || {
            calls.set(calls.get() + 1);
            Ok(GOOD.to_owned())
        };
        let replayed = cached_response(&cache, Some(&key), &accepted, &live).unwrap();
        assert_eq!(live_count(&calls), 1, "a poisoned entry is not trusted");
        assert_eq!(replayed, GOOD);
        // It has been replaced by the accepted answer, so the next run hits.
        cached_response(&cache, Some(&key), &accepted, &live).unwrap();
        assert_eq!(live_count(&calls), 1, "the repaired entry replays");
    }

    #[test]
    fn a_response_that_never_parses_is_never_cached() {
        let root = tempfile::tempdir().unwrap();
        let cfg = cached_config(root.path());
        let cache = ResponseCache::new(&cfg);
        let key = cache.key(&cfg, &cfg.model, "PROMPT").unwrap();
        let calls = std::cell::Cell::new(0u32);
        let live = || {
            calls.set(calls.get() + 1);
            Ok("garbage".to_owned())
        };
        // The caller still receives the raw text to report on, but nothing is
        // stored, so a bad answer can never mask the model on the next try.
        assert_eq!(
            cached_response(&cache, Some(&key), &accepted, &live).unwrap(),
            "garbage"
        );
        assert!(cache.get(&key).is_none());
        cached_response(&cache, Some(&key), &accepted, &live).unwrap();
        assert_eq!(live_count(&calls), 2);
    }

    #[test]
    fn without_cache_dir_every_request_reaches_the_model() {
        let cfg = config();
        let cache = ResponseCache::new(&cfg);
        assert!(cache.disabled());
        assert!(cache.key(&cfg, &cfg.model, "PROMPT").is_none());
        let calls = std::cell::Cell::new(0u32);
        let live = || {
            calls.set(calls.get() + 1);
            Ok(GOOD.to_owned())
        };
        for _ in 0..2 {
            cached_response(&cache, None, &accepted, &live).unwrap();
        }
        assert_eq!(live_count(&calls), 2, "the default stays exactly as before");
    }

    // ----- audit cache gate: no frozen empty answers (2026-11-10 item-4) -----

    #[test]
    fn cache_gate_rejects_empty_corrections_shells() {
        // The item-4 cue-429 poison: a structurally valid zero-item audit
        // envelope passes parse and validate_corrections, yet it is a
        // failed round whenever the batch holds a mandatory cue — so the
        // station order treats every empty shell as a failed response and
        // keeps it out of the cache, mandatory batch or not.
        let expected = BTreeSet::from([1, 2]);
        let mandatory = BTreeSet::from([1]);
        for shell in [r#"{"corrections":[]}"#, "[]", "{}"] {
            assert!(
                !audit_response_is_cachable(shell, &expected, &mandatory, 2, "Chinese"),
                "{shell} must never be cached"
            );
            assert!(
                !audit_response_is_cachable(shell, &expected, &BTreeSet::new(), 2, "Chinese"),
                "{shell} must never be cached without mandatory cues either"
            );
        }
        // Empty-text items keep failing validate_corrections on the way.
        assert!(!audit_response_is_cachable(
            r#"{"corrections":[{"index":1,"text":"  "}]}"#,
            &expected,
            &mandatory,
            2,
            "Chinese"
        ));
    }

    #[test]
    fn cache_gate_requires_full_mandatory_coverage() {
        let expected = BTreeSet::from([1, 2]);
        let mandatory = BTreeSet::from([1]);
        // The success shape: covers the mandatory index with a real text.
        assert!(audit_response_is_cachable(
            r#"{"corrections":[{"index":1,"text":"甲"}]}"#,
            &expected,
            &mandatory,
            2,
            "Chinese"
        ));
        // Omits the mandatory index: `audit_alignment` would re-split this
        // and eventually bail, so freezing it is exactly the deterministic
        // death the gate exists to prevent.
        assert!(!audit_response_is_cachable(
            r#"{"corrections":[{"index":2,"text":"乙"}]}"#,
            &expected,
            &mandatory,
            2,
            "Chinese"
        ));
        // Without mandatory cues, any strict-valid corrections envelope is
        // the answer the caller would have accepted, cache included.
        assert!(audit_response_is_cachable(
            r#"{"corrections":[{"index":2,"text":"乙"}]}"#,
            &expected,
            &BTreeSet::new(),
            2,
            "Chinese"
        ));
        // The strict checks keep their veto as well.
        assert!(!audit_response_is_cachable(
            r#"{"corrections":[{"index":7,"text":"庚"}]}"#,
            &expected,
            &mandatory,
            2,
            "Chinese"
        ));
        assert!(!audit_response_is_cachable(
            r#"{"corrections":[{"index":1,"text":"甲"},{"index":2,"text":"乙"}]}"#,
            &expected,
            &mandatory,
            1,
            "Chinese"
        ));
    }

    /// The cue-429 review leg answered every round with `{"corrections":[]}`.
    /// Used to be cached (shape-valid) and replayed forever: one random
    /// empty answer frozen into a deterministic bail across all burns.
    #[test]
    fn an_empty_corrections_shell_never_freezes_a_mandatory_death() {
        let root = tempfile::tempdir().unwrap();
        let (base_url, seen) = llm_server(|body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
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
        let mut cfg = cached_config(root.path());
        cfg.base_url = base_url;
        cfg.timeout_seconds = 10;
        cfg.max_retries = 1;
        let review_requests = || -> usize {
            seen.lock()
                .unwrap()
                .iter()
                .filter(|body| body["prompt"].as_str().unwrap().contains("final-review"))
                .count()
        };
        let error = translate(&cues(10), &cfg).unwrap_err().to_string();
        assert!(error.contains("omitted mandatory correction"), "{error}");
        let first = review_requests();
        assert!(first > 0, "the review leg must have asked the model");
        // Every audit round this run answered was a shell, so the cache may
        // hold translation responses only — not one audit envelope on disk.
        for entry in std::fs::read_dir(root.path()).unwrap() {
            let path = entry.unwrap().path();
            let text = std::fs::read_to_string(&path).unwrap();
            let parsed: Value = serde_json::from_str(&text).unwrap_or_else(|error| {
                panic!("cache entry {} is not JSON: {error}", path.display())
            });
            assert!(
                parsed.get("corrections").is_none(),
                "audit envelope frozen into the cache: {text}"
            );
        }
        // The next burn re-asks for real. Before the gate fix this second
        // run replayed the whole review leg from disk, reached the model
        // zero times, and died at the identical byte.
        let error = translate(&cues(10), &cfg).unwrap_err().to_string();
        assert!(error.contains("omitted mandatory correction"), "{error}");
        assert!(
            review_requests() > first,
            "the review leg replayed its death from the cache instead of re-asking"
        );
    }

    /// The gate must still let genuine successes in — that is what the
    /// cache was built for — while empty shells keep re-rolling live.
    #[test]
    fn a_covered_mandatory_audit_answer_replays_from_cache() {
        let root = tempfile::tempdir().unwrap();
        let (base_url, seen) = llm_server(|body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
                if prompt.contains("\"must_correct\":true") {
                    return ollama_reply(json!({
                        "corrections": [{ "index": 1, "text": "第一行修正。" }]
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
        let mut cfg = cached_config(root.path());
        cfg.base_url = base_url;
        cfg.timeout_seconds = 10;
        cfg.max_retries = 1;
        let outcome = translate(&cues(10), &cfg).unwrap();
        assert_eq!(outcome.cues[0].text, "第一行修正。\nLine 1");
        let review_rounds = |bodies: &[Value], mandatory_only: bool| -> usize {
            bodies
                .iter()
                .filter(|body| {
                    let prompt = body["prompt"].as_str().unwrap();
                    prompt.contains("final-review")
                        && (!mandatory_only || prompt.contains("\"must_correct\":true"))
                })
                .count()
        };
        let first_run = seen.lock().unwrap().clone();
        assert!(review_rounds(&first_run, true) >= 1);
        // Exactly one audit envelope on disk: the covered mandatory answer.
        let audit_entries: Vec<String> = std::fs::read_dir(root.path())
            .unwrap()
            .map(|entry| std::fs::read_to_string(entry.unwrap().path()).unwrap())
            .filter(|text| {
                serde_json::from_str::<Value>(text)
                    .is_ok_and(|value| value.get("corrections").is_some())
            })
            .collect();
        assert_eq!(
            audit_entries,
            vec![r#"{"corrections":[{"index":1,"text":"第一行修正。"}]}"#.to_owned()]
        );
        // Re-burn on the same cache: the mandatory round replays without
        // reaching the model, while the empty shells of the mandatory-free
        // batches are asked again (failed responses are never frozen).
        let outcome = translate(&cues(10), &cfg).unwrap();
        assert_eq!(outcome.cues[0].text, "第一行修正。\nLine 1");
        let second_run = {
            let all = seen.lock().unwrap();
            all[first_run.len()..].to_vec()
        };
        assert_eq!(
            review_rounds(&second_run, true),
            0,
            "the covered mandatory corrections envelope must replay from the cache"
        );
        assert!(
            review_rounds(&second_run, false) > 0,
            "empty shells must keep re-rolling live, never replayed as truth"
        );
    }

    // ----- stubborn-cue fallback route (2026-11-10 engine-swap landing order) -----

    /// Station dossier death case, item-5 cue 527: the primary engine answers
    /// this one only with a window-consuming reasoning loop (direct probes
    /// E5/E6, 4096 and 16384 both empty), while translategemma:4b answers it
    /// correctly. The profile must route it to the fallback engine.
    const DEATH_CASE_527: &str = "- <i>Dragon?</i>\n- This is unacceptable!";

    #[test]
    fn stubborn_profile_pins_the_item5_cue527_death_case() {
        assert!(matches_stubborn_profile(DEATH_CASE_527));
    }

    #[test]
    fn stubborn_profile_rejects_the_two_primary_rescued_cues() {
        // item-5 cues 419 and 429 translated correctly on the primary engine
        // (station landing order point 1: no regression), so they must stay.
        assert!(!matches_stubborn_profile("<i>Ping.</i>"));
        assert!(!matches_stubborn_profile(
            "the 335th Regiment of the 38th's 3rd Company."
        ));
        // every profile clause must hold together:
        assert!(!matches_stubborn_profile("- Alpha line\n- Beta line")); // no italic
        assert!(!matches_stubborn_profile("<i>Alpha</i>")); // italic, single line
        assert!(!matches_stubborn_profile(
            "<i>Alpha</i>\nsecond speaker has no dash"
        )); // one speaker only
        let long = format!("- <i>{}</i>\n- second speaker rambles on", "x".repeat(200));
        assert!(!matches_stubborn_profile(&long)); // not a short line
        assert!(!matches_stubborn_profile(
            "- <i>unclosed italic\n- second line"
        )); // unpaired tag
    }

    #[test]
    fn want_set_prompt_is_byte_identical_when_it_equals_the_core() {
        // primary-engine batch prompts must stay byte-identical so existing
        // response caches of the 30 bound videos never go stale (landing
        // order point 4: old tomls keep the old behaviour, zero drift).
        let values = cues(8);
        let cfg = config();
        let plain = build_prompt(&values, 2..6, &cfg).unwrap();
        let want: BTreeSet<usize> = (2..6).collect();
        assert_eq!(
            plain,
            build_prompt_wanting(&values, 2..6, &cfg, &want).unwrap()
        );
    }

    #[test]
    fn want_set_keeps_a_dropped_cue_visible_as_read_only_context() {
        let mut values = cues(4);
        values[1].text = DEATH_CASE_527.to_owned();
        let cfg = config();
        let want: BTreeSet<usize> = [0usize, 2, 3].into_iter().collect();
        let prompt = build_prompt_wanting(&values, 0..4, &cfg, &want).unwrap();
        let items = prompt_items(&prompt);
        let dropped = items.iter().find(|item| item["index"] == 2).unwrap();
        assert_eq!(dropped["translate"], false);
        assert_eq!(dropped["text"], DEATH_CASE_527);
        for index in [1, 3, 4] {
            assert!(
                items
                    .iter()
                    .any(|item| item["index"] == index && item["translate"] == true),
                "index {index} must stay in the want set"
            );
        }
    }

    #[test]
    fn stubborn_cue_is_answered_by_the_fallback_engine_and_never_by_the_primary() {
        // In-process pin of landing-order point 2 (the smoke test repeats it
        // against the real services): the profile cue goes to the fallback
        // engine, everything else stays on the primary, and each answer is
        // cached under its own engine-specific key.
        let (primary_url, primary_seen) = llm_server(|body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
                return ollama_reply(json!({ "corrections": [] }));
            }
            let translations: Vec<Value> = prompt_items(prompt)
                .iter()
                .filter(|item| item["translate"] == true)
                .map(|item| json!({ "index": item["index"], "text": "正常行。" }))
                .collect();
            ollama_reply(json!({ "translations": translations }))
        });
        let (fallback_url, fallback_seen) = llm_server(|body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
                return ollama_reply(json!({ "corrections": [] }));
            }
            let translations: Vec<Value> = prompt_items(prompt)
                .iter()
                .filter(|item| item["translate"] == true)
                .map(|item| json!({ "index": item["index"], "text": "斜体说话行。" }))
                .collect();
            ollama_reply(json!({ "translations": translations }))
        });
        let cache_root = tempfile::tempdir().unwrap();
        let mut values = cues(3);
        values[1].text = DEATH_CASE_527.to_owned();
        let mut cfg: TranslationConfig = toml::from_str(&format!(
            r#"
provider = "ollama"
base_url = "{primary_url}"
model = "translategemma:4b"
source_language = "English"
source_language_code = "en"
target_language = "Simplified Chinese"
target_language_code = "zh-CN"
timeout_seconds = 10
max_retries = 0
batch_size = 3
consistency_check = false
alignment_check = false
cache_dir = "{}"

[fallback]
provider = "ollama"
base_url = "{fallback_url}"
model = "translategemma:4b"
timeout_seconds = 10
max_retries = 0
"#,
            cache_root.path().display()
        ))
        .unwrap();
        cfg.fallback.as_mut().unwrap().base_url = fallback_url;
        let outcome = translate(&values, &cfg).unwrap();
        // cue 2 came back from the fallback engine …
        assert!(outcome.cues[1].text.starts_with("斜体说话行。"));
        // … cues 1 and 3 from the primary engine.
        assert!(outcome.cues[0].text.starts_with("正常行。"));
        assert!(outcome.cues[2].text.starts_with("正常行。"));
        // the primary saw exactly one batch asking only the two healthy cues;
        // the death case survived only as read-only context.
        let primary = primary_seen.lock().unwrap();
        assert_eq!(primary.len(), 1, "primary must serve exactly one batch");
        let asked: Vec<u32> = prompt_items(primary[0]["prompt"].as_str().unwrap())
            .iter()
            .filter(|item| item["translate"] == true)
            .map(|item| item["index"].as_u64().unwrap() as u32)
            .collect();
        assert_eq!(asked, vec![1, 3]);
        // the fallback engine was asked exactly once, for exactly the death case.
        let fallback = fallback_seen.lock().unwrap();
        assert_eq!(
            fallback.len(),
            1,
            "fallback engine must serve exactly the stubborn cue"
        );
        let asked: Vec<u32> = prompt_items(fallback[0]["prompt"].as_str().unwrap())
            .iter()
            .filter(|item| item["translate"] == true)
            .map(|item| item["index"].as_u64().unwrap() as u32)
            .collect();
        assert_eq!(asked, vec![2]);
        // each engine wrote its own cache entry under its own key: two files,
        // never one overwriting the other (landing order point 2).
        let entries: Vec<_> = std::fs::read_dir(cache_root.path())
            .unwrap()
            .filter_map(Result::ok)
            .filter(|entry| entry.path().extension().is_some_and(|ext| ext == "json"))
            .collect();
        assert_eq!(
            entries.len(),
            2,
            "both engines must leave one distinct cache entry each"
        );
    }

    #[test]
    fn absent_fallback_section_keeps_every_cue_on_the_primary_engine() {
        // Old tomls (landing order point 4): without `[translation.fallback]`
        // even a profile-matched death case goes through the primary route
        // with the pre-feature request count, so bound videos keep the exact
        // behaviour their cache_key was computed under.
        let (primary_url, primary_seen) = llm_server(|body| {
            let prompt = body["prompt"].as_str().unwrap();
            if prompt.contains("final-review") {
                return ollama_reply(json!({ "corrections": [] }));
            }
            let translations: Vec<Value> = prompt_items(prompt)
                .iter()
                .filter(|item| item["translate"] == true)
                .map(|item| json!({ "index": item["index"], "text": "正常行。" }))
                .collect();
            ollama_reply(json!({ "translations": translations }))
        });
        let mut values = cues(2);
        values[1].text = DEATH_CASE_527.to_owned();
        let mut cfg = config();
        cfg.base_url = primary_url;
        cfg.timeout_seconds = 10;
        cfg.max_retries = 0;
        cfg.batch_size = 2;
        cfg.consistency_check = false;
        cfg.alignment_check = false;
        let outcome = translate(&values, &cfg).unwrap();
        assert!(outcome.cues[1].text.starts_with("正常行。"));
        let primary = primary_seen.lock().unwrap();
        assert_eq!(primary.len(), 1);
        assert_eq!(primary[0]["model"], "translategemma:4b");
    }
}
