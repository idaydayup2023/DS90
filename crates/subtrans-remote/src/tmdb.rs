use std::io::Read;
use std::thread;
use std::time::Duration;

use anyhow::{Context, Result, bail};
use reqwest::StatusCode;
use reqwest::blocking::Client;
use subtrans_core::remote::MetadataSource;

pub struct TmdbSettings {
    pub base_url: String,
    pub image_base_url: String,
    pub token: String,
    pub api_token_env: String,
    pub timeout_seconds: u64,
    pub max_retries: u32,
    pub max_response_bytes: usize,
    pub max_image_bytes: usize,
}

pub struct HttpTmdb {
    client: Client,
    settings: TmdbSettings,
}

impl HttpTmdb {
    pub fn connect(settings: TmdbSettings) -> Result<Self> {
        let client = Client::builder()
            .timeout(Duration::from_secs(settings.timeout_seconds))
            .user_agent(concat!("subtrans/", env!("CARGO_PKG_VERSION")))
            .build()
            .context("failed to create TMDB HTTP client")?;
        Ok(Self { client, settings })
    }

    fn request_url(
        &self,
        url: &str,
        parameters: &[(&str, &str)],
        authenticated: bool,
    ) -> Result<Vec<u8>> {
        let maximum = if authenticated {
            self.settings.max_response_bytes
        } else {
            self.settings.max_image_bytes
        };
        let mut last = None;
        for attempt in 0..=self.settings.max_retries {
            let request = self.client.get(url).query(parameters);
            let request = if authenticated {
                request.bearer_auth(&self.settings.token)
            } else {
                request
            };
            match request.send() {
                Ok(response) if response.status().is_success() => {
                    return bounded_bytes(response, maximum);
                }
                Ok(response)
                    if response.status() == StatusCode::TOO_MANY_REQUESTS
                        || response.status().is_server_error() =>
                {
                    last = Some(anyhow::anyhow!("TMDB returned HTTP {}", response.status()));
                }
                Ok(response)
                    if matches!(
                        response.status(),
                        StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN
                    ) =>
                {
                    bail!(
                        "TMDB rejected the API Read Access Token from environment variable {} with HTTP {}; verify the token and rerun `subtrans doctor`",
                        self.settings.api_token_env,
                        response.status()
                    )
                }
                Ok(response) => bail!("TMDB returned HTTP {} for {url}", response.status()),
                Err(error) => last = Some(error.into()),
            }
            if attempt < self.settings.max_retries {
                thread::sleep(Duration::from_millis(250 * u64::from(attempt + 1)));
            }
        }
        Err(last.unwrap_or_else(|| anyhow::anyhow!("TMDB request failed")))
            .with_context(|| format!("TMDB request failed after retries: {url}"))
    }
}

impl MetadataSource for HttpTmdb {
    fn get_json(&self, endpoint: &str, parameters: &[(&str, &str)]) -> Result<Vec<u8>> {
        let url = format!(
            "{}/{}",
            self.settings.base_url.trim_end_matches('/'),
            endpoint.trim_start_matches('/')
        );
        self.request_url(&url, parameters, true)
    }

    fn get_image(&self, path: &str) -> Result<Vec<u8>> {
        let url = format!(
            "{}/{}",
            self.settings.image_base_url.trim_end_matches('/'),
            path.trim_start_matches('/')
        );
        self.request_url(&url, &[], false)
    }
}

fn bounded_bytes(mut response: reqwest::blocking::Response, maximum: usize) -> Result<Vec<u8>> {
    if response
        .content_length()
        .is_some_and(|length| length > maximum as u64)
    {
        bail!("TMDB response exceeds configured size limit of {maximum} bytes");
    }
    let mut bytes = Vec::new();
    response
        .by_ref()
        .take(maximum as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        bail!("TMDB response exceeds configured size limit of {maximum} bytes");
    }
    Ok(bytes)
}
