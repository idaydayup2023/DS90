//! 只读键面探针（代码运维 · 2026-11-13 Zero.Day 对口径二次案发）
//! 直接调 DS90 **本体**的 cache_key()/artifact::identity()，把工具面复刻件从循环里拿掉：
//! 工具面与引擎面任何漂移当场可见（团队钉过的 babf 坑）。
//! 用法: cargo run --example key_probe -- <config.toml> <source_sha256>...

use subtrans::config::Config;
use subtrans::subtitles::cache_key;
use anyhow::Result;

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let config_path = args.next().expect("usage: <config.toml> <source_sha256>...");
    let cfg = Config::load(&config_path)?;
    println!("config = {}", config_path);
    println!("cache_key(schema={})", subtrans::artifact::ARTIFACT_SCHEMA);
    for source_sha256 in args {
        println!(
            "  {}  ->  {}",
            source_sha256,
            cache_key(&source_sha256, &cfg.translation)?
        );
    }
    Ok(())
}
