use std::collections::BTreeMap;

use subtrans::config::{LlmProvider, TranslationConfig};
use subtrans::subtitles::{
    Cue, cache_key, format_srt, parse_aligned, parse_srt, render_translation, should_translate,
    validate_output,
};

fn cue(index: u32, text: &str) -> Cue {
    Cue {
        index,
        start_ms: u64::from(index) * 1_000,
        end_ms: u64::from(index) * 1_000 + 750,
        text: text.to_owned(),
    }
}

fn translation_config() -> TranslationConfig {
    TranslationConfig {
        provider: LlmProvider::Ollama,
        base_url: "http://127.0.0.1:11434".to_owned(),
        model: "model-a".to_owned(),
        api_key_env: None,
        source_language: "English".to_owned(),
        target_language: "Simplified Chinese".to_owned(),
        bilingual: true,
        batch_size: 20,
        timeout_seconds: 30,
        max_retries: 2,
        max_batch_chars: 8_000,
        max_response_bytes: 1024 * 1024,
        min_target_script_ratio: 0.15,
    }
}

#[test]
fn strict_srt_round_trip_preserves_timing_and_text() {
    let source = "\u{feff}1\r\n00:00:01,000 --> 00:00:02,500\r\nHello.\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nLine one\r\nLine two\r\n";
    let cues = parse_srt(source).unwrap();
    assert_eq!(cues.len(), 2);
    assert_eq!(cues[0].start_ms, 1_000);
    assert_eq!(cues[1].text, "Line one\nLine two");
    assert_eq!(parse_srt(&format_srt(&cues).unwrap()).unwrap(), cues);
}

#[test]
fn strict_srt_rejects_malformed_or_dropped_blocks() {
    let missing_text = "1\n00:00:01,000 --> 00:00:02,000\n\n";
    assert!(parse_srt(missing_text).is_err());
    let missing_index = "00:00:01,000 --> 00:00:02,000\nHello\n";
    assert!(parse_srt(missing_index).is_err());
    let index_gap =
        "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n3\n00:00:03,000 --> 00:00:04,000\nBye\n";
    let normalized = parse_srt(index_gap).unwrap();
    assert_eq!(
        normalized[1].index, 2,
        "non-contiguous source numbers are normalized safely"
    );
    let reversed = "1\n00:00:02,000 --> 00:00:01,000\nHello\n";
    assert!(parse_srt(reversed).is_err());
}

#[test]
fn quality_gate_rejects_source_echo_and_accepts_chinese_translation() {
    let source: Vec<_> = (1..=10)
        .map(|index| cue(index, &format!("English line {index}")))
        .collect();
    let echoed: Vec<_> = source
        .iter()
        .map(|cue| Cue {
            text: format!("{}\n{}", cue.text, cue.text),
            ..cue.clone()
        })
        .collect();
    assert!(
        subtrans::subtitles::validate_translation_quality(
            &source,
            &echoed,
            "Simplified Chinese",
            0.15,
        )
        .is_err()
    );

    let translated: Vec<_> = source
        .iter()
        .map(|cue| Cue {
            text: format!("这是译文{}\n{}", cue.index, cue.text),
            ..cue.clone()
        })
        .collect();
    subtrans::subtitles::validate_translation_quality(
        &source,
        &translated,
        "Simplified Chinese",
        0.15,
    )
    .unwrap();
}

#[test]
fn batch_response_requires_exact_alignment() {
    let expected = vec![cue(1, "Hello"), cue(2, "Goodbye")];
    let exact = r#"{"translations":[{"index":1,"text":"你好"},{"index":2,"text":"再见"}]}"#;
    assert_eq!(parse_aligned(exact, &expected).unwrap().len(), 2);
    let missing = r#"{"translations":[{"index":1,"text":"你好"}]}"#;
    assert!(parse_aligned(missing, &expected).is_err());
    let duplicate = r#"{"translations":[{"index":1,"text":"你好"},{"index":1,"text":"您好"}]}"#;
    assert!(parse_aligned(duplicate, &expected).is_err());
    let noise = "```json\n{\"translations\":[]}\n```";
    assert!(parse_aligned(noise, &expected).is_err());
}

#[test]
fn output_quality_rejects_missing_or_misaligned_cues() {
    let source = vec![cue(1, "Hello"), cue(2, "Goodbye")];
    let translations = BTreeMap::from([(1, "你好".to_owned()), (2, "再见".to_owned())]);
    let output = render_translation(&source, &translations, true).unwrap();
    validate_output(&source, &output, true).unwrap();
    assert_eq!(output[0].text, "你好\nHello");

    let mut altered = output.clone();
    altered[1].start_ms += 1;
    assert!(validate_output(&source, &altered, true).is_err());
    assert!(render_translation(&source, &BTreeMap::from([(1, "你好".to_owned())]), true).is_err());
}

#[test]
fn cache_key_covers_model_language_and_parameters_and_force_bypasses_cache() {
    let cfg = translation_config();
    let key = cache_key("source-hash", &cfg).unwrap();
    assert!(!should_translate(false, true, true));
    assert!(should_translate(true, true, true));
    assert!(should_translate(false, false, true));
    assert!(should_translate(false, true, false));

    let mut changed = translation_config();
    changed.model = "model-b".to_owned();
    assert_ne!(key, cache_key("source-hash", &changed).unwrap());
    changed = translation_config();
    changed.target_language = "Traditional Chinese".to_owned();
    assert_ne!(key, cache_key("source-hash", &changed).unwrap());
    changed = translation_config();
    changed.batch_size = 10;
    assert_ne!(key, cache_key("source-hash", &changed).unwrap());
    assert_ne!(key, cache_key("different-source", &cfg).unwrap());
}
