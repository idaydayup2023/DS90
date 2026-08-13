pub mod artifact;
pub mod config;
pub mod metadata;
pub mod migration;
pub mod state;
pub mod storage;
pub mod subtitles;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
