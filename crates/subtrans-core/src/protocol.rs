use std::borrow::Cow;
use std::collections::{BTreeMap, BTreeSet};

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Deserializer, de};
use serde_json::Value;

use crate::srt::{Cue, single_line};

#[derive(Debug, Deserialize)]
struct TranslationEnvelope {
    #[serde(alias = "items", alias = "results")]
    translations: Vec<TranslatedLine>,
}

#[derive(Debug, Deserialize)]
pub struct ConsistencyEnvelope {
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

pub fn parse_valid_indices(
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

pub fn parse_consistency_envelope(response: &str) -> Result<ConsistencyEnvelope> {
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

pub fn validate_corrections(
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

fn normalize_known_json_keys(response: &str) -> Cow<'_, str> {
    if response.contains("\"text:\":") {
        Cow::Owned(response.replace("\"text:\":", "\"text\":"))
    } else {
        Cow::Borrowed(response)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
