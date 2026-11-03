//! HTTP adapters for the core `LlmClient` and `MetadataSource` traits.

mod llm;
mod tmdb;

pub use llm::HttpLlm;
pub use tmdb::{HttpTmdb, TmdbSettings};
