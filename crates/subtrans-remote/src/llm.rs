use std::io::Read;
use std::time::Duration;

use anyhow::{Context, Result, bail};
use reqwest::blocking::Client;
use serde_json::{Value, json};
use subtrans_core::remote::{LlmApi, LlmClient, LlmCompletion, LlmProbe};

pub struct HttpLlm {
    client: Client,
}

impl HttpLlm {
    pub fn new(timeout_seconds: u64) -> Result<Self> {
        let client = Client::builder()
            .timeout(Duration::from_secs(timeout_seconds))
            .build()
            .context("failed to initialize the translation HTTP client")?;
        Ok(Self { client })
    }
}

impl LlmClient for HttpLlm {
    fn complete(&self, request: &LlmCompletion<'_>) -> Result<String> {
        let (url, body, response_path): (String, Value, &[&str]) = match request.api {
            LlmApi::Ollama => (
                endpoint(request.base_url, "api/generate"),
                json!({
                    "model": request.model,
                    "prompt": request.prompt,
                    "stream": false,
                    "format": "json",
                    "think": false,
                    "keep_alive": "10m",
                    "options": {
                        "temperature": 0.0,
                        "num_predict": request.max_output_tokens
                    }
                }),
                &["response"],
            ),
            LlmApi::OpenaiCompatible => (
                endpoint(request.base_url, "chat/completions"),
                json!({
                    "model": request.model,
                    "messages": [{"role": "user", "content": request.prompt}],
                    "temperature": 0.0,
                    "max_tokens": request.max_output_tokens,
                    "response_format": {"type": "json_object"}
                }),
                &["choices", "0", "message", "content"],
            ),
        };
        let mut http = self.client.post(url).json(&body);
        if let Some(key) = request.api_key {
            http = http.bearer_auth(key);
        }
        let response = http
            .send()
            .with_context(|| {
                format!(
                    "translation model request failed for model {:?} at {}. Start/verify the configured service and model, check network/API-key settings, then run `subtrans doctor --config <CONFIG>`",
                    request.model, request.base_url
                )
            })?
            .error_for_status()
            .with_context(|| {
                format!(
                    "translation service rejected model {:?}. Verify the model is installed/enabled (for Ollama: `ollama pull {}` and `ollama list`), then run `subtrans doctor --config <CONFIG>`",
                    request.model, request.model
                )
            })?;
        let mut bytes = Vec::new();
        response
            .take(request.max_response_bytes as u64 + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() > request.max_response_bytes {
            bail!("translation service response exceeds configured size limit");
        }
        let response: Value =
            serde_json::from_slice(&bytes).context("translation service returned invalid JSON")?;
        value_at(&response, response_path)
            .and_then(Value::as_str)
            .map(str::to_owned)
            .context("translation service response is missing generated content")
    }

    fn probe(&self, request: &LlmProbe<'_>) -> Result<String> {
        let url = match request.api {
            LlmApi::Ollama => endpoint(request.base_url, "api/tags"),
            LlmApi::OpenaiCompatible => endpoint(request.base_url, "models"),
        };
        let mut http = self.client.get(url);
        if let Some(key) = request.api_key {
            http = http.bearer_auth(key);
        }
        http.send()
            .with_context(|| {
                format!(
                    "translation service is unreachable. {}",
                    request.service_guidance
                )
            })?
            .error_for_status()
            .with_context(|| {
                format!(
                    "translation service health check failed. {}",
                    request.service_guidance
                )
            })?
            .text()
            .context("translation service health response could not be read")
    }
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
