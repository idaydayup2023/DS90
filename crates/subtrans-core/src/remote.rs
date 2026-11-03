//! Boundaries for model and metadata calls.
//!
//! Implementations live in `subtrans-remote`. These traits do not accept
//! media paths and do not return destination directories.

use anyhow::Result;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LlmApi {
    Ollama,
    OpenaiCompatible,
}

/// One model completion. `prompt` already contains the cue batch. `base_url`
/// is the model service, not a storage path.
pub struct LlmCompletion<'a> {
    pub api: LlmApi,
    pub base_url: &'a str,
    pub model: &'a str,
    pub api_key: Option<&'a str>,
    pub prompt: &'a str,
    pub max_output_tokens: u32,
    pub max_response_bytes: usize,
}

/// Doctor's model-service health read. `service_guidance` is included in the
/// existing error text so a failed probe still names the recovery steps.
pub struct LlmProbe<'a> {
    pub api: LlmApi,
    pub base_url: &'a str,
    pub api_key: Option<&'a str>,
    pub service_guidance: &'a str,
}

pub trait LlmClient: Send + Sync {
    fn complete(&self, request: &LlmCompletion<'_>) -> Result<String>;
    fn probe(&self, request: &LlmProbe<'_>) -> Result<String>;
}

pub trait MetadataSource: Send + Sync {
    fn get_json(&self, endpoint: &str, parameters: &[(&str, &str)]) -> Result<Vec<u8>>;
    fn get_image(&self, path: &str) -> Result<Vec<u8>>;
}
