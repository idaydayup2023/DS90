use anyhow::{Context, Result, bail};
use regex::Regex;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Cue {
    pub index: u32,
    pub start_ms: u64,
    pub end_ms: u64,
    pub text: String,
}

/// Parse SRT without silently discarding malformed blocks.
pub fn parse(input: &str) -> Result<Vec<Cue>> {
    let normalized = input
        .strip_prefix('\u{feff}')
        .unwrap_or(input)
        .replace("\r\n", "\n")
        .replace('\r', "\n");
    let normalized = normalized.trim_end_matches('\n');
    if normalized.trim().is_empty() {
        bail!("SRT is empty");
    }

    let separator = Regex::new(r"\n[ \t]*\n+").expect("static block separator regex");
    let timestamp = Regex::new(
        r"^(\d{1,}):(\d{2}):(\d{2})[,.](\d{3})[ \t]+-->[ \t]+(\d{1,}):(\d{2}):(\d{2})[,.](\d{3})(?:[ \t]+.*)?$",
    )
    .expect("static timestamp regex");
    let mut cues = Vec::new();

    for (block_number, block) in separator.split(normalized).enumerate() {
        let lines: Vec<&str> = block.lines().collect();
        if lines.len() < 3 {
            bail!("SRT block {} has no text", block_number + 1);
        }
        let index: u32 = lines[0]
            .trim()
            .parse()
            .with_context(|| format!("SRT block {} has an invalid index", block_number + 1))?;
        if index == 0 {
            bail!("SRT block {} has index zero", block_number + 1);
        }

        let captures = timestamp
            .captures(lines[1].trim())
            .with_context(|| format!("SRT cue {index} has an invalid timestamp"))?;
        let start_ms = parse_timestamp(&captures, 1)
            .with_context(|| format!("SRT cue {index} has an invalid start timestamp"))?;
        let end_ms = parse_timestamp(&captures, 5)
            .with_context(|| format!("SRT cue {index} has an invalid end timestamp"))?;
        if end_ms <= start_ms {
            bail!("SRT cue {index} ends before or at its start");
        }
        let text = lines[2..].join("\n").trim().to_owned();
        if text.is_empty() {
            bail!("SRT cue {index} has empty text");
        }
        cues.push(Cue {
            index: (block_number + 1) as u32,
            start_ms,
            end_ms,
            text,
        });
    }

    Ok(cues)
}

pub fn format(cues: &[Cue]) -> Result<String> {
    if cues.is_empty() {
        bail!("cannot format an empty SRT");
    }
    let mut result = String::new();
    for (offset, cue) in cues.iter().enumerate() {
        if cue.end_ms <= cue.start_ms {
            bail!("SRT cue {} ends before or at its start", cue.index);
        }
        if cue.text.trim().is_empty() {
            bail!("SRT cue {} has empty text", cue.index);
        }
        let index = offset + 1;
        result.push_str(&format!(
            "{index}\n{} --> {}\n{}\n\n",
            format_timestamp(cue.start_ms),
            format_timestamp(cue.end_ms),
            cue.text.trim()
        ));
    }
    Ok(result)
}

pub fn single_line(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn parse_timestamp(captures: &regex::Captures<'_>, start: usize) -> Result<u64> {
    let hour: u64 = captures[start].parse()?;
    let minute: u64 = captures[start + 1].parse()?;
    let second: u64 = captures[start + 2].parse()?;
    let millis: u64 = captures[start + 3].parse()?;
    if minute > 59 || second > 59 || millis > 999 {
        bail!("timestamp component out of range");
    }
    Ok((((hour * 60) + minute) * 60 + second) * 1_000 + millis)
}

fn format_timestamp(total_ms: u64) -> String {
    let millis = total_ms % 1_000;
    let total_seconds = total_ms / 1_000;
    let seconds = total_seconds % 60;
    let total_minutes = total_seconds / 60;
    let minutes = total_minutes % 60;
    let hours = total_minutes / 60;
    format!("{hours:02}:{minutes:02}:{seconds:02},{millis:03}")
}
