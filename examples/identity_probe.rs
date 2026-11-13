//! 只读探针（代码运维 · 2026-11-13 mtime 口径对账第四证）
//! 用 DS90 **生产代码本体**（storage::open_storage -> FTP MLSD -> artifact::video_identity
//! -> artifact::read_ready_artifact）判定 sidecar 是否 ready。不 RETR 正片。
//! 用法: cargo run --example identity_probe -- <config.toml> <video_rel_path>...

use std::time::UNIX_EPOCH;
use subtrans::artifact::{identity, read_ready_artifact, video_identity};
use subtrans::config::{Config, StorageConfig};
use subtrans::storage::open_storage;

fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let config_path = args
        .next()
        .expect("usage: <config.toml> <video_rel_path>...");
    let mut cfg = Config::load(&config_path)?;
    if let StorageConfig::Ftp { root, .. } = &mut cfg.source {
        *root = "/".to_string();
    }
    let storage = open_storage(&cfg.source)?;
    for video_path in args {
        println!("=== {} ===", video_path);
        let entry = match storage.metadata(&video_path)? {
            Some(entry) => entry,
            None => {
                println!("  MISSING");
                continue;
            }
        };
        let epoch = entry
            .modified
            .and_then(|m| m.duration_since(UNIX_EPOCH).ok())
            .map(|d| d.as_secs());
        println!("  path           = {}", entry.path);
        println!("  size           = {}", entry.size);
        println!("  mtime_epoch    = {:?}", epoch);
        println!("  identity_A     = {}", video_identity(&entry));
        println!(
            "  identity_B     = {}",
            identity(&entry.path, entry.size, epoch.map(|v| v - 28_800))
        );
        match read_ready_artifact(&*storage, &entry)? {
            Some(m) => println!(
                "  DS90_VERDICT   = READY status={} identity={} cache_key={} acq={}",
                m.status, m.video_identity_sha256, m.cache_key, m.acquisition_key
            ),
            None => println!("  DS90_VERDICT   = NOT_READY (reason on stderr)"),
        }
    }
    Ok(())
}
