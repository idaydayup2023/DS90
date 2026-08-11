use std::path::Path;

use regex::Regex;
use serde::{Deserialize, Serialize};

pub const RULE_VERSION: &str = "migration-rules-v3.2";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MediaKind {
    Movie,
    Tv,
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Evidence {
    pub code: String,
    pub detail: String,
    pub confidence: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Classification {
    pub kind: MediaKind,
    pub title: Option<String>,
    pub year: Option<u16>,
    pub season: Option<u16>,
    pub episode: Option<u16>,
    pub is_4k: bool,
    pub confidence: f32,
    pub evidence: Vec<Evidence>,
    pub pending_reason: Option<String>,
}

impl Classification {
    pub fn is_pending(&self) -> bool {
        self.kind == MediaKind::Unknown || self.pending_reason.is_some()
    }
}

/// Classify a media path using deterministic, auditable filename rules only.
///
/// Encoding and quality labels are deliberately evaluated independently from
/// media kind. In particular, 4K/UHD/2160p/HEVC/HDR/DV can never turn a movie
/// into an episode or vice versa.
pub fn classify_path(path: &str) -> Classification {
    let normalized = path.replace('\\', "/");
    let filename = normalized.rsplit('/').next().unwrap_or(&normalized);
    let stem = Path::new(filename)
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or(filename);
    let is_4k = has_4k_marker(&normalized);
    let mut evidence = Vec::new();

    if let Some((season, episode, detail)) = multi_episode_marker(&normalized) {
        evidence.push(Evidence {
            code: "multi_episode_marker".to_owned(),
            detail,
            confidence: 0.95,
        });
        return pending_with_markers(
            is_4k,
            evidence,
            "multi-episode files require explicit review until destination naming is configured",
            Some(season),
            Some(episode),
        );
    }

    if let Some((season, episode, detail)) = paired_episode_marker(&normalized) {
        evidence.push(Evidence {
            code: "explicit_season_episode".to_owned(),
            detail,
            confidence: 0.99,
        });
        return Classification {
            kind: MediaKind::Tv,
            title: tv_title(&normalized),
            year: release_year(stem),
            season: Some(season),
            episode: Some(episode),
            is_4k,
            confidence: 0.99,
            evidence,
            pending_reason: None,
        };
    }

    let season = season_marker(&normalized);
    let episode = episode_marker(stem, season.is_some());
    if season.is_some() || episode.is_some() {
        if let Some((value, detail)) = &season {
            evidence.push(Evidence {
                code: "season_marker".to_owned(),
                detail: detail.clone(),
                confidence: 0.90,
            });
            if *value > 99 {
                return pending_with_markers(
                    is_4k,
                    evidence,
                    "season number is outside the supported range",
                    Some(*value),
                    episode.as_ref().map(|(value, _)| *value),
                );
            }
        }
        if let Some((value, detail)) = &episode {
            evidence.push(Evidence {
                code: "episode_marker".to_owned(),
                detail: detail.clone(),
                confidence: 0.90,
            });
            if *value == 0 {
                return pending_with_markers(
                    is_4k,
                    evidence,
                    "episode zero is invalid",
                    season.as_ref().map(|(value, _)| *value),
                    Some(*value),
                );
            }
        }
        if let (Some((season, _)), Some((episode, _))) = (season.as_ref(), episode.as_ref()) {
            return Classification {
                kind: MediaKind::Tv,
                title: tv_title(&normalized),
                year: release_year(stem),
                season: Some(*season),
                episode: Some(*episode),
                is_4k,
                confidence: 0.97,
                evidence,
                pending_reason: None,
            };
        }
        return pending_with_markers(
            is_4k,
            evidence,
            "probable TV item has incomplete season/episode evidence",
            season.map(|(value, _)| value),
            episode.map(|(value, _)| value),
        );
    }

    if let Some((year, source)) = movie_release_signature(stem) {
        evidence.push(Evidence {
            code: "movie_release_signature".to_owned(),
            detail: format!("release year {year} with source {source}"),
            confidence: 0.96,
        });
        return Classification {
            kind: MediaKind::Movie,
            title: movie_title(stem, year),
            year: Some(year),
            season: None,
            episode: None,
            is_4k,
            confidence: 0.96,
            evidence,
            pending_reason: None,
        };
    }

    if let Some(year) = release_year(stem) {
        evidence.push(Evidence {
            code: "release_year_only".to_owned(),
            detail: format!("release year {year} is not sufficient by itself"),
            confidence: 0.55,
        });
    }
    pending(is_4k, evidence, "no reliable movie or complete TV evidence")
}

fn pending(is_4k: bool, evidence: Vec<Evidence>, reason: &str) -> Classification {
    pending_with_markers(is_4k, evidence, reason, None, None)
}

fn pending_with_markers(
    is_4k: bool,
    evidence: Vec<Evidence>,
    reason: &str,
    season: Option<u16>,
    episode: Option<u16>,
) -> Classification {
    Classification {
        kind: MediaKind::Unknown,
        title: None,
        year: None,
        season,
        episode,
        is_4k,
        confidence: 0.0,
        evidence,
        pending_reason: Some(reason.to_owned()),
    }
}

fn paired_episode_marker(text: &str) -> Option<(u16, u16, String)> {
    let patterns = [
        r"(?i)(?:^|[^A-Z0-9])S(\d{1,2})[ ._-]*E(\d{1,3})(?:[^0-9]|$)",
        r"(?i)(?:^|[^0-9])(\d{1,2})x(\d{1,3})(?:[^0-9]|$)",
        r"(?i)(?:Season|Series)[ ._-]*(\d{1,2}).{0,80}?(?:Episode|Ep|E)[ ._-]*(\d{1,3})(?:[^0-9]|$)",
        r"第\s*(\d{1,2})\s*季.{0,80}?第?\s*(\d{1,3})\s*集",
    ];
    for pattern in patterns {
        let regex = Regex::new(pattern).expect("static episode pattern must compile");
        if let Some(captures) = regex.captures(text) {
            let season = captures.get(1)?.as_str().parse().ok()?;
            let episode = captures.get(2)?.as_str().parse().ok()?;
            if episode == 0 {
                continue;
            }
            let marker = captures
                .get(0)?
                .as_str()
                .trim_matches(|c: char| !c.is_alphanumeric());
            return Some((season, episode, format!("path marker {marker}")));
        }
    }
    None
}

fn multi_episode_marker(text: &str) -> Option<(u16, u16, String)> {
    let regex = Regex::new(
        r"(?i)(?:^|[^A-Z0-9])S(\d{1,2})[ ._-]*E(\d{1,3})(?:[ ._-]*E|[ ._]*-)[ ._-]*(\d{1,3})(?:[^0-9]|$)",
    )
    .expect("static multi-episode pattern must compile");
    let captures = regex.captures(text)?;
    let season = captures[1].parse().ok()?;
    let first = captures[2].parse().ok()?;
    let last: u16 = captures[3].parse().ok()?;
    (last > first).then(|| (season, first, format!("path marker {}", &captures[0])))
}

fn season_marker(text: &str) -> Option<(u16, String)> {
    let components: Vec<&str> = text.split('/').collect();
    let component_regex = Regex::new(r"(?i)^(?:Season|Series|S)[ ._-]*(\d{1,2})$")
        .expect("static season component pattern must compile");
    let embedded_regex =
        Regex::new(r"(?i)(?:^|[^A-Z0-9])(?:Season|Series)[ ._-]*(\d{1,2})(?:[^0-9]|$)")
            .expect("static season pattern must compile");
    let chinese_regex =
        Regex::new(r"第\s*(\d{1,2})\s*季").expect("static Chinese season pattern must compile");

    for component in components.iter().take(components.len().saturating_sub(1)) {
        if let Some(captures) = component_regex.captures(component.trim()) {
            return Some((
                captures[1].parse().ok()?,
                format!("season directory {component}"),
            ));
        }
        if let Some(captures) = chinese_regex.captures(component) {
            return Some((
                captures[1].parse().ok()?,
                format!("season directory {component}"),
            ));
        }
    }
    if let Some(captures) = embedded_regex.captures(text) {
        return Some((
            captures[1].parse().ok()?,
            format!("season marker {}", &captures[0]),
        ));
    }
    chinese_regex.captures(text).and_then(|captures| {
        Some((
            captures[1].parse().ok()?,
            format!("season marker {}", &captures[0]),
        ))
    })
}

fn episode_marker(stem: &str, constrained_by_season: bool) -> Option<(u16, String)> {
    let regex = Regex::new(r"(?i)(?:^|[^A-Z0-9])(?:Episode|Ep|E)[ ._-]*(\d{1,3})(?:[^0-9]|$)")
        .expect("static episode pattern must compile");
    if let Some(captures) = regex.captures(stem) {
        return Some((
            captures[1].parse().ok()?,
            format!("episode marker {}", &captures[0]),
        ));
    }
    let chinese =
        Regex::new(r"第?\s*(\d{1,3})\s*集").expect("static Chinese episode pattern must compile");
    if let Some(captures) = chinese.captures(stem) {
        return Some((
            captures[1].parse().ok()?,
            format!("episode marker {}", &captures[0]),
        ));
    }
    if constrained_by_season {
        let bare = Regex::new(r"^\s*0*(\d{1,3})\s*$").expect("static numeric pattern must compile");
        if let Some(captures) = bare.captures(stem) {
            return Some((
                captures[1].parse().ok()?,
                format!("numeric episode filename {stem}"),
            ));
        }
    }
    None
}

fn movie_release_signature(stem: &str) -> Option<(u16, String)> {
    if Regex::new(r"(?:^|[^0-9])(?:19|20)\d{2}[ ._-](?:0?[1-9]|1[0-2])[ ._-](?:0?[1-9]|[12]\d|3[01])(?:[^0-9]|$)")
        .expect("static date episode pattern must compile")
        .is_match(stem)
    {
        return None;
    }
    let year = release_year(stem)?;
    let source = Regex::new(
        r"(?i)(?:^|[^A-Z0-9])(WEB[ ._-]*DL|WEBRIP|BLU[ ._-]*RAY|BDRIP|BRRIP|REMUX)(?:[^A-Z0-9]|$)",
    )
    .expect("static source pattern must compile")
    .captures(stem)?
    .get(1)?
    .as_str()
    .to_owned();
    Some((year, source))
}

fn release_year(stem: &str) -> Option<u16> {
    Regex::new(r"(?:^|[^0-9])((?:19|20)\d{2})(?:[^0-9]|$)")
        .expect("static year pattern must compile")
        .captures_iter(stem)
        .last()
        .and_then(|captures| captures.get(1)?.as_str().parse().ok())
}

fn has_4k_marker(text: &str) -> bool {
    Regex::new(r"(?i)(?:^|[^A-Z0-9])(?:4K|UHD|2160P)(?:[^A-Z0-9]|$)")
        .expect("static quality pattern must compile")
        .is_match(text)
}

fn movie_title(stem: &str, year: u16) -> Option<String> {
    let index = stem.find(&year.to_string()).unwrap_or(stem.len());
    clean_title(&stem[..index])
}

fn tv_title(path: &str) -> Option<String> {
    let components: Vec<&str> = path.split('/').collect();
    let season_component = Regex::new(r"(?i)^(?:Season|Series|S)[ ._-]*\d{1,2}$")
        .expect("static season directory pattern must compile");
    let chinese_season =
        Regex::new(r"第\s*\d{1,2}\s*季").expect("static Chinese season pattern must compile");
    for (index, component) in components.iter().enumerate().rev().skip(1) {
        if (season_component.is_match(component) || chinese_season.is_match(component)) && index > 0
        {
            return clean_title(components[index - 1]);
        }
    }

    let stem = Path::new(components.last().copied().unwrap_or(path))
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or(path);
    let marker = Regex::new(
        r"(?i)(?:[ ._-]+S\d{1,2}[ ._-]*E\d{1,3}|[ ._-]+\d{1,2}x\d{1,3}|[ ._-]+(?:Season|Series)[ ._-]*\d{1,2}|[ ._-]+第\s*\d{1,2}\s*季)",
    )
    .expect("static TV title marker must compile");
    let end = marker
        .find(stem)
        .map(|value| value.start())
        .unwrap_or(stem.len());
    clean_title(&stem[..end])
}

fn clean_title(raw: &str) -> Option<String> {
    let separators = Regex::new(r"[._]+|\s+-\s+").expect("static title separator must compile");
    let spaces = Regex::new(r"\s+").expect("static whitespace pattern must compile");
    let text = separators.replace_all(raw, " ");
    let text = spaces.replace_all(
        text.trim_matches(|c: char| c.is_whitespace() || c == '-' || c == '_'),
        " ",
    );
    let trailing_quality =
        Regex::new(r"(?i)(?:\s+(?:4K|UHD|2160P|1080P|HEVC|H265|HDR(?:10\+?)?|DV))+$")
            .expect("static trailing quality pattern must compile");
    let text = trailing_quality.replace(&text, "");
    (!text.is_empty()).then(|| text.into_owned())
}
