use std::collections::HashMap;

use anyhow::{Result, bail};

use super::srt::{Cue, single_line};

pub fn score_source(cues: &[Cue], expected_language: &str) -> Result<f32> {
    validate_source(cues)?;
    let text = cues
        .iter()
        .map(|cue| cue.text.as_str())
        .collect::<Vec<_>>()
        .join(" ");
    let visible = text.chars().filter(|ch| !ch.is_whitespace()).count().max(1);
    let latin = text.chars().filter(|ch| ch.is_ascii_alphabetic()).count();
    let language_bonus = if expected_language.to_ascii_lowercase().contains("english") {
        latin as f32 / visible as f32
    } else {
        0.5
    };
    let overlap = cues
        .windows(2)
        .filter(|pair| pair[1].start_ms < pair[0].end_ms)
        .count() as f32
        / cues.len().max(1) as f32;
    Ok((70.0 + 30.0 * language_bonus - 30.0 * overlap).clamp(0.0, 100.0))
}

pub fn validate_source(cues: &[Cue]) -> Result<()> {
    if cues.is_empty() {
        bail!("subtitle has no cues");
    }
    let mut counts: HashMap<String, usize> = HashMap::new();
    let mut watermark = 0usize;
    let mut replacement = 0usize;
    for cue in cues {
        let normalized = single_line(&cue.text).to_ascii_lowercase();
        *counts.entry(normalized.clone()).or_default() += 1;
        if normalized.contains("castingwords") || normalized.contains("opensubtitles.org") {
            watermark += 1;
        }
        replacement += cue.text.matches('\u{fffd}').count();
    }
    if replacement > 0 {
        bail!("subtitle contains replacement characters");
    }
    if cues.len() >= 10 {
        let most = counts.values().copied().max().unwrap_or(0);
        if most * 10 >= cues.len() * 7 {
            bail!("subtitle is dominated by repeated text");
        }
        if watermark * 5 >= cues.len() {
            bail!("subtitle is dominated by watermark text");
        }
    }
    let overlaps = cues
        .windows(2)
        .filter(|pair| pair[1].start_ms < pair[0].end_ms)
        .count();
    if cues.len() >= 10 && overlaps * 5 > cues.len() {
        bail!("subtitle has excessive timing overlap");
    }
    Ok(())
}

pub fn validate_translation_quality(
    source: &[Cue],
    output: &[Cue],
    target_language: &str,
    min_target_script_ratio: f32,
) -> Result<()> {
    let targets: Vec<String> = output
        .iter()
        .map(|output| output.text.lines().next().unwrap_or("").trim().to_owned())
        .collect();
    let same = source
        .iter()
        .zip(&targets)
        .filter(|(source, target)| {
            single_line(&source.text).eq_ignore_ascii_case(&single_line(target))
        })
        .count();
    if source.len() >= 5 && same * 2 >= source.len() {
        bail!("too many translations repeat the source text unchanged");
    }
    let mut counts = HashMap::new();
    for target in &targets {
        *counts.entry(target.to_ascii_lowercase()).or_insert(0usize) += 1;
    }
    let translated_count = targets.len();
    if translated_count >= 10
        && counts.values().copied().max().unwrap_or(0) * 10 >= translated_count * 7
    {
        bail!("translated subtitle is dominated by repeated output");
    }
    if target_language.to_ascii_lowercase().contains("chinese") {
        let joined = targets
            .iter()
            .map(String::as_str)
            .collect::<Vec<_>>()
            .join("");
        if joined.is_empty() {
            return Ok(());
        }
        let visible = joined
            .chars()
            .filter(|ch| !ch.is_whitespace())
            .count()
            .max(1);
        let cjk = joined
            .chars()
            .filter(|ch| matches!(*ch as u32, 0x3400..=0x4DBF | 0x4E00..=0x9FFF))
            .count();
        let ratio = cjk as f32 / visible as f32;
        if ratio < min_target_script_ratio {
            bail!(
                "target Chinese script ratio {:.3} is below required {:.3}",
                ratio,
                min_target_script_ratio
            );
        }
    }
    Ok(())
}

pub(crate) fn translation_concerns(
    source: &str,
    target: &str,
    target_language: &str,
    min_target_script_ratio: f32,
) -> Vec<String> {
    let source = single_line(source);
    let target = single_line(target);
    let mut reasons = Vec::new();
    if target.is_empty() {
        reasons.push("empty_translation".to_owned());
        return reasons;
    }

    let substantive_source = is_substantive_translatable_english(&source);
    if substantive_source && source.eq_ignore_ascii_case(&target) {
        reasons.push("source_text_repeated_unchanged".to_owned());
    }
    if target_language.to_ascii_lowercase().contains("chinese") && substantive_source {
        let visible = target
            .chars()
            .filter(|ch| !ch.is_whitespace())
            .count()
            .max(1);
        let cjk = target
            .chars()
            .filter(|ch| matches!(*ch as u32, 0x3400..=0x4DBF | 0x4E00..=0x9FFF))
            .count();
        let ratio = cjk as f32 / visible as f32;
        if ratio < min_target_script_ratio {
            reasons.push(format!(
                "target_chinese_script_ratio_{ratio:.3}_below_{min_target_script_ratio:.3}"
            ));
        }
    }
    reasons
}

fn is_substantive_translatable_english(text: &str) -> bool {
    if text.contains("://") || text.contains('@') || text.to_ascii_lowercase().contains("www.") {
        return false;
    }
    let letters: String = text.chars().filter(char::is_ascii_alphabetic).collect();
    if letters.is_empty() {
        return false;
    }
    let identifier_characters = text
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.' | '/'));
    let internal_uppercase = letters.chars().skip(1).any(|ch| ch.is_ascii_uppercase())
        && letters.chars().any(|ch| ch.is_ascii_lowercase());
    let compact_identifier = !text.chars().any(char::is_whitespace)
        && identifier_characters
        && ((letters.len() <= 10 && letters.chars().all(|ch| ch.is_ascii_uppercase()))
            || internal_uppercase
            || text.chars().any(|ch| ch.is_ascii_digit()));
    !compact_identifier
}

#[cfg(test)]
mod tests {
    use super::translation_concerns;

    #[test]
    fn concerns_detect_untranslated_english_but_allow_short_identifiers() {
        assert!(
            translation_concerns(
                "This is still English.",
                "This is still English.",
                "Chinese",
                0.15
            )
            .len()
                >= 2
        );
        assert!(translation_concerns("Hello", "你好", "Chinese", 0.15).is_empty());
        assert!(translation_concerns("FDE", "FDE", "Chinese", 0.15).is_empty());
        assert!(translation_concerns("OpenAI", "OpenAI", "Chinese", 0.15).is_empty());
        assert!(!translation_concerns("DUCK!", "DUCK!", "Chinese", 0.15).is_empty());
    }
}
