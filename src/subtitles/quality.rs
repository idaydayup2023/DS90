use std::collections::{HashMap, HashSet};

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
        // 中文占比闸（11-13 站长令钉死的约束下修正；PR 描述有全量用例）：
        //   ① 全局阈值 `min_target_script_ratio` 一律不放宽，0.150 仍是 0.150；
        //   ② 只按**源文构成**判，无按片/按 cue 白名单、无硬编码 cue 号：
        //        · 源文剔掉专名形态的词后什么都不剩（品牌名清单／北约音标呼号／歌词碎片）
        //          ⇒ 这行本身就不要求产出中文；但译文若夹带**源文里没有的英文**，仍按未译拦；
        //        · 源文还剩可译内容 ⇒ 照旧判占比，只是把「源文里本就是专名形态」的 ASCII 串
        //          移出分母（Windows／Android／Axis Falcon 保留原文是正确译法，不该稀释中文比）。
        //   ③ 真缺陷行仍须被拦：该译未译的普通词、源文里没有的英文、以及**标点**都留在分母里，
        //      所以"整行只剩专名＋标点"这种漏译照样红；分母空而源文有可译内容也照样红。
        let nouns = proper_noun_tokens(&source);
        let codes = source_code_tokens(&source);
        let visible_all = target
            .chars()
            .filter(|ch| !ch.is_whitespace())
            .count()
            .max(1);
        let reason = format!(
            "target_chinese_script_ratio_{:.3}_below_{:.3}",
            target.chars().filter(|ch| is_cjk_han(*ch)).count() as f32 / visible_all as f32,
            min_target_script_ratio
        );
        if source_translatable_letters(&source) == 0 {
            if target_letters_beyond_proper_nouns(&target, &nouns) > 0 {
                reasons.push(reason);
            }
        } else {
            let (visible, cjk) = target_ratio_basis(&target, &nouns, &codes);
            if visible == 0 || (cjk as f32 / visible as f32) < min_target_script_ratio {
                reasons.push(reason);
            }
        }
    }
    reasons
}

/// 汉字面（与整片级占比闸同一套码位，别在这里扩面）。
fn is_cjk_han(ch: char) -> bool {
    matches!(ch as u32, 0x3400..=0x4DBF | 0x4E00..=0x9FFF)
}

/// 「退化修正文」形态（站长 2026-11-14 批复②）：审校腿交回来的东西**非空、但一个目标语种
/// 字符都没有** —— `。`／`！` 这类单标点、纯标点串、以及剥离后什么都不剩的残留。汉字面与
/// 占比闸共用 [`is_cjk_han`]，不扩面，也完全不碰 `min_target_script_ratio`（0.150 仍是 0.150）。
///
/// 零输出（空串／全空白）**不算退化**：那条走既有的 strict hard-fail 与 `unresolved_empty`
/// 面（`partition_corrections` → 一轮重试 → 降级）。两条线在 `audit_alignment` 里分开判，
/// 界分即此 PR 的生死线（见 `translation.rs` 的 degenerate 测试）。
pub(crate) fn target_text_is_degenerate(target: &str, target_language: &str) -> bool {
    let target = single_line(target);
    if target.is_empty() {
        return false;
    }
    if !target_language.to_ascii_lowercase().contains("chinese") {
        return false;
    }
    !target.chars().any(is_cjk_han)
}

/// 占比闸那一条 concern 的形态判定（`target_chinese_script_ratio_0.000_below_0.150`）。
/// 只用来把「占比这一条」与「其它判据（例如未译照抄源文 `source_text_repeated_unchanged`）」
/// 分开处置：concern 里混进任何非占比条目都照旧硬判红。判据本身一字未动。
pub(crate) fn is_target_script_ratio_concern(concern: &str) -> bool {
    concern.starts_with("target_chinese_script_ratio_")
}

/// 剥掉 `<...>` 与 `{...}` 标签（HTML/ASS 排版标记），使标签字符不参与词形与占比统计。
fn strip_tags(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut depth = 0usize;
    for ch in text.chars() {
        match ch {
            '<' | '{' => depth += 1,
            '>' | '}' => depth = depth.saturating_sub(1),
            _ if depth == 0 => out.push(ch),
            _ => {}
        }
    }
    out
}

/// 词形上的"不可译专名"：全大写缩写（`LD`／`FBI`）、首字母大写的名字（`Windows`／`Falcon`／
/// `November`，北约音标词全落在此形）、内含大写的商用名（`iPhone`）。
/// **小写开头的词永远不算专名** —— 那是谓语与普通名词的信号，必须译出中文。
/// 单字母不算（防 `A`／`B` 之类被当专名免检）。
fn is_proper_name_token(token: &str) -> bool {
    let letters: Vec<char> = token
        .chars()
        .filter(|ch| ch.is_ascii_alphabetic())
        .collect();
    if letters.len() < 2 || letters[0].is_ascii_lowercase() {
        return false;
    }
    letters.iter().all(|ch| ch.is_ascii_uppercase())
        || letters.iter().any(|ch| ch.is_ascii_lowercase())
        || letters.iter().skip(1).any(|ch| ch.is_ascii_uppercase())
}

/// 源文里"专名形态"词的集合（小写化，供译文侧对照）。
fn proper_noun_tokens(text: &str) -> HashSet<String> {
    strip_tags(text)
        .split(|ch: char| !ch.is_alphanumeric())
        .filter(|token| is_proper_name_token(token))
        .map(|token| token.to_ascii_lowercase())
        .collect()
}

/// 豁免资格只由「**在源文里就是专名形态**」这一条限定，不设长度下限 ——
/// 呼号／音标缩写本就是两三个字母（`LD`、`FBI`、`32`），卡下限会把它们当未译扣分。
/// 非字母 token（数字航路点）字母数为 0，天然不贡献分母。
fn is_source_proper_noun(token: &str, nouns: &HashSet<String>) -> bool {
    let letters: String = token
        .chars()
        .filter(|ch| ch.is_ascii_alphabetic())
        .collect();
    !letters.is_empty() && nouns.contains(&letters.to_ascii_lowercase())
}

/// 源文里"含数字的编码串"（航路点 `7-8-9-0-1-2-3`、机型 `F-16`、倒计时 `3-2-1`）。
/// 与专名同理：这类串的正确译法就是原样保留，不该进中文占比的分母。
/// **必须含数字、且与源文某 token 逐字相同**才豁免 —— 谓语与普通词永不含数字，
/// 所以这条放不走"整行没翻"（那种情形分母会被剔空，另有 `visible == 0` 的红线兜底）。
fn source_code_tokens(text: &str) -> HashSet<String> {
    strip_tags(text)
        .split(|ch: char| !(ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '/' | ':')))
        .filter(|token| token.chars().any(|ch| ch.is_ascii_digit()))
        .map(|token| token.to_ascii_lowercase())
        .collect()
}

fn is_source_code_token(token: &str, codes: &HashSet<String>) -> bool {
    token.chars().any(|ch| ch.is_ascii_digit()) && codes.contains(&token.to_ascii_lowercase())
}

/// token 边界：字母数字**与连接符**（`-_/ :`）算一段，使 `7-8-9-0-1-2-3`、`F-16`、`3.5`
/// 这类串不被拆成单字符灌进分母。**不含 `.`** —— 它同时是句尾标点，
/// 吞进来会让源文末尾 token 变成 `…-3.` 而与译文侧的 `…-3` 不相等（两侧口径必须对称）。
fn is_wordish(ch: char) -> bool {
    ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '/' | ':')
}

/// 源文剔除专名后**还剩下多少该译成中文的字母内容**（0 ⇒ 这行的原文本身就不要求中文）。
fn source_translatable_letters(source: &str) -> usize {
    strip_tags(source)
        .split(|ch: char| !ch.is_alphanumeric())
        .filter(|token| !token.is_empty() && !is_proper_name_token(token))
        .map(|token| token.chars().filter(|ch| ch.is_ascii_alphabetic()).count())
        .sum()
}

/// 占比闸的分母/分子：剥标签后逐段扫，**跳过"源文里本就是专名形态"的 ASCII 串**，
/// 其余非空白字符（含标点、数字、该译未译的普通词、源文里没有的英文）全部分母；汉字计数。
fn target_ratio_basis(
    target: &str,
    nouns: &HashSet<String>,
    codes: &HashSet<String>,
) -> (usize, usize) {
    let chars: Vec<char> = strip_tags(target).chars().collect();
    let (mut visible, mut cjk) = (0usize, 0usize);
    let mut i = 0usize;
    while i < chars.len() {
        if is_wordish(chars[i]) {
            let start = i;
            while i < chars.len() && is_wordish(chars[i]) {
                i += 1;
            }
            let token: String = chars[start..i].iter().collect();
            if is_source_proper_noun(&token, nouns) || is_source_code_token(&token, codes) {
                continue; // 源文里的专名／编码串原样保留是正确译法，不进分母
            }
            visible += token.chars().count();
        } else {
            if !chars[i].is_whitespace() {
                visible += 1;
                if is_cjk_han(chars[i]) {
                    cjk += 1;
                }
            }
            i += 1;
        }
    }
    (visible, cjk)
}

/// 译文里"不属于源文专名"的字母内容：这些是该译却没译的部分，留在分母里扣分。
/// 只豁免长度 ≥3 且**在源文里就是专名形态**的 ASCII 串；单双字母与源文没有的英文一律不豁免。
fn target_letters_beyond_proper_nouns(target: &str, nouns: &HashSet<String>) -> usize {
    strip_tags(target)
        .split(|ch: char| !ch.is_alphanumeric())
        .filter(|token| !token.is_empty())
        .filter(|token| !is_source_proper_noun(token, nouns))
        .map(|token| token.chars().filter(|ch| ch.is_ascii_alphabetic()).count())
        .sum()
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
    use super::{
        is_cjk_han, is_target_script_ratio_concern, target_text_is_degenerate, translation_concerns,
    };

    /// 退化修正文的判据面（站长 2026-11-14 批复②的界分线之一）：非空、零汉字 ⇒ 退化；
    /// 零输出（空串／全空白）**不算**退化，它走既有的 strict hard-fail／`unresolved_empty` 面；
    /// 沾一个汉字就不算退化；目标语非中文一律不判退化。
    #[test]
    fn degenerate_target_text_covers_punctuation_only_corrections_only() {
        for punctuation in ["。", "！", "……", "？！", ".-_", "」】"] {
            assert!(
                target_text_is_degenerate(punctuation, "Simplified Chinese"),
                "{punctuation} 必须是退化修正文"
            );
        }
        assert!(!target_text_is_degenerate("", "Simplified Chinese"));
        assert!(!target_text_is_degenerate("   ", "Simplified Chinese"));
        assert!(!target_text_is_degenerate(
            "轴心猎鹰。",
            "Simplified Chinese"
        ));
        assert!(!target_text_is_degenerate("。好", "Simplified Chinese"));
        assert!(!target_text_is_degenerate("Hello there.", "English"));
    }

    /// 占比条的形态判定只认占比闸自己那条 concern，别的判据（未译照抄源文）不许混进退化面。
    #[test]
    fn ratio_concern_predicate_matches_only_the_script_ratio() {
        assert!(is_target_script_ratio_concern(
            "target_chinese_script_ratio_0.000_below_0.150"
        ));
        assert!(!is_target_script_ratio_concern(
            "source_text_repeated_unchanged"
        ));
        assert!(!is_target_script_ratio_concern("empty_translation"));
        // 判据名与阈值面一字未动：真打失照样打得出同一条。
        assert!(
            translation_concerns("in the press tomorrow.", "。", "Chinese", 0.15)
                .iter()
                .any(|concern| is_target_script_ratio_concern(concern))
        );
    }

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

    /// 零模型占比闸的比值口径（与 `target_ratio_basis` 同面，供用例自证"旧口径确实会打回"）。
    fn legacy_ratio(target: &str) -> f32 {
        let visible = target
            .chars()
            .filter(|ch| !ch.is_whitespace())
            .count()
            .max(1);
        let cjk = target.chars().filter(|ch| is_cjk_han(*ch)).count();
        cjk as f32 / visible as f32
    }

    fn has_ratio(concerns: &[String]) -> bool {
        concerns
            .iter()
            .any(|reason| reason.starts_with("target_chinese_script_ratio_"))
    }

    /// 正向用例：Zero.Day 三发同形打失（原文逐字取 `种子` 材料卷
    /// `logs/闸门材料_zeroday_中文占比闸误伤_2026-11-13.md`，E02 c92／E03 c587／E04 c365；
    /// c366/c367 为作者旁证的同型呼号行），修正文按"专名保留原文"的正确译法构造。
    /// 每条都先断言**旧口径必然打回**（ratio < 0.150），再断言新口径放行 —— 否则用例是空的。
    #[test]
    fn proper_noun_heavy_lines_are_not_flagged_but_were_before_the_fix() {
        let cases = [
            // E02 cue 92（旧报 0.111）：品牌名清单行，专名保留原文 + 中文骨架
            (
                "Devices operating on Windows, Android,",
                "Devices 运行于 Windows、Android",
            ),
            // E03 cue 587（旧报 0.100）：歌词渐弱残句
            ("<i>Who...</i>", "<i>Who…</i>"),
            // E04 cue 365（旧报 0.148）：北约音标呼号，专名保留原文是唯一正确译法
            (
                "Axis Falcon, LD, Alpha India November.",
                "Axis Falcon，LD，Alpha India November。",
            ),
            // E04 cue 367 同型呼号（带中文骨架；**整行逐字照抄**会撞另一道
            // `source_text_repeated_unchanged` 闸，见下方 verbatim_* 用例，本次未动那道闸）
            ("Yankee Bravo 32 Lima", "Yankee Bravo 32 Lima，收到"),
            // E04 cue 366 同型（含数字航路点）
            ("En route to 7-8-9-0-1-2-3.", "前往 7-8-9-0-1-2-3。"),
            // 专名密集长清单行（最狠的一条：旧口径 0.103 必打回）
            (
                "Devices operating on Windows, Android, MacOS, iOS, and Chromebook.",
                "Windows、Android、MacOS、iOS 与 Chromebook 都运行",
            ),
        ];
        for (source, target) in cases {
            assert!(
                legacy_ratio(target) < 0.15,
                "用例失效：{target:?} 在旧口径下 ratio={:.3} 本就不会被打回",
                legacy_ratio(target)
            );
            assert!(
                translation_concerns(source, target, "Chinese", 0.15).is_empty(),
                "专名密集合法行被误伤：{source:?} -> {target:?} {:?}",
                translation_concerns(source, target, "Chinese", 0.15)
            );
        }
    }

    /// 负控：真缺陷行**必须仍被拦**（站长约束二 —— 负控不过不许合）。
    /// 逐条先断言旧口径也拦（保证是同一道闸在拦），再断言新口径仍拦。
    #[test]
    fn real_defects_are_still_flagged_after_the_exemption() {
        let cases = [
            // 整段没翻：照抄英文
            (
                "The station is losing signal.",
                "The station is losing signal.",
            ),
            // 漏译谓语，整行只剩专名 + 中文标点（标点仍留分母 ⇒ 拦得住）
            (
                "Devices operating on Windows, Android,",
                "Windows、Android，",
            ),
            // 同上且无标点（分母为空，而源文有可译内容 ⇒ 拦得住）
            ("Devices operating on Windows, Android,", "Windows Android"),
            // 只翻一半：该译的普通词原样留着
            (
                "Devices operating on Windows, Android,",
                "Devices operating on Windows 和 Android",
            ),
            // 纯呼号行却夹带源文里没有的英文（源文无可译内容也不许夹生英文）
            (
                "Axis Falcon, LD, Alpha India November.",
                "Axis Falcon, LD, Alpha India November, requesting vector",
            ),
            // 呼号段漏译成整句英文
            ("Yankee Bravo 32 Lima", "Yankee Bravo Thirty Two Lima"),
            // 航路点整串照抄、谓语没译（编码串豁免**不该**放走这种）
            ("En route to 7-8-9-0-1-2-3.", "7-8-9-0-1-2-3。"),
            ("En route to 7-8-9-0-1-2-3.", "7-8-9-0-1-2-3"),
        ];
        for (source, target) in cases {
            assert!(
                legacy_ratio(target) < 0.15,
                "用例失效：{target:?} 旧口径下就不该由占比闸拦"
            );
            let concerns = translation_concerns(source, target, "Chinese", 0.15);
            assert!(
                has_ratio(&concerns),
                "真缺陷行被放过了：{source:?} -> {target:?} {concerns:?}"
            );
        }
    }

    /// 已知边界（**本次未动，已如实报站长**）：专名密集行若**整行逐字照抄**原文，
    /// 拦它的是既有的 `source_text_repeated_unchanged` 闸，不是中文占比闸 —— 同一类误伤的
    /// 另一面。本 PR 只按站长的案子动中文占比闸，那道闸的行为在此钉成断言，防止无意识改动。
    #[test]
    fn verbatim_copy_of_noun_only_line_is_caught_by_the_unchanged_gate() {
        let concerns = translation_concerns(
            "Yankee Bravo 32 Lima",
            "Yankee Bravo 32 Lima",
            "Chinese",
            0.15,
        );
        assert!(
            concerns
                .iter()
                .any(|reason| reason == "source_text_repeated_unchanged")
        );
        // 带中文骨架即放行（呼号原样保留 + 「收到」是正确译法）
        assert!(
            translation_concerns(
                "Yankee Bravo 32 Lima",
                "Yankee Bravo 32 Lima，收到",
                "Chinese",
                0.15
            )
            .is_empty()
        );
    }

    /// 豁免判据不得含任何按片/按 cue 的白名单：同一形态换个牌子也必须放行，
    /// 换成本片里没有的专名也必须同样处理（站长约束三的可自证形式）。
    #[test]
    fn exemption_is_shape_based_not_title_based() {
        assert!(
            translation_concerns(
                "Powered by Huawei, Xiaomi, Samsung.",
                "Huawei、Xiaomi、Samsung 驱动",
                "Chinese",
                0.15
            )
            .is_empty()
        );
        assert!(
            translation_concerns(
                "Bravo Charlie 45 Delta.",
                "Bravo Charlie 45 Delta。",
                "Chinese",
                0.15
            )
            .is_empty()
        );
        // 同形态但没有专名可豁免（普通词一个都没译）⇒ 照样拦
        assert!(has_ratio(&translation_concerns(
            "The router rebooted twice.",
            "The router rebooted twice.",
            "Chinese",
            0.15
        )));
    }
}
