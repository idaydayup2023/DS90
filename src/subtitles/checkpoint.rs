use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::artifact::TranslationQualityRecord;

pub const CHECKPOINT_SCHEMA: u32 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SubtitleStage {
    Translate,
    Review,
    Both,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PendingCue {
    pub candidate: String,
    pub reasons: BTreeSet<String>,
    #[serde(default)]
    pub primary_error: Option<String>,
}

/// Resume record for one video. Stored in the state database, not beside the media.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SubtitleCheckpoint {
    pub schema: u32,
    pub video: String,
    pub source_sha256: String,
    pub cache_key: String,
    pub settled_indices: BTreeSet<u32>,
    pub reviewed_indices: BTreeSet<u32>,
    pub translations: BTreeMap<u32, String>,
    pub pending_review: BTreeMap<u32, PendingCue>,
    pub quality_log: Vec<TranslationQualityRecord>,
}

impl SubtitleCheckpoint {
    pub fn new(video: &str, source_sha256: String, cache_key: String) -> Self {
        Self {
            schema: CHECKPOINT_SCHEMA,
            video: video.to_owned(),
            source_sha256,
            cache_key,
            settled_indices: BTreeSet::new(),
            reviewed_indices: BTreeSet::new(),
            translations: BTreeMap::new(),
            pending_review: BTreeMap::new(),
            quality_log: Vec::new(),
        }
    }

    pub fn matches(&self, video: &str, source_sha256: &str, cache_key: &str) -> bool {
        self.schema == CHECKPOINT_SCHEMA
            && self.video == video
            && self.source_sha256 == source_sha256
            && self.cache_key == cache_key
    }

    pub fn settled(&self, index: u32) -> bool {
        self.settled_indices.contains(&index) && self.translations.contains_key(&index)
    }
}
