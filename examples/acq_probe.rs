//! 只读键面探针（代码运维 · 2026-11-14 Zero.Day identity 对口径二次案发后续）
//!
//! `acquisition_key` = sha256(serde_json{schema, video_identity, translation.source_language,
//! subtitles.ffmpeg / ffprobe / external_srt_validation / asr / pgs_ocr})，即「跑批 toml 的
//! 属性 + 视频身份」的哈希。它是 `process_video` 判 cached / cache_miss 的两把钥匙之一
//! （另一把是 cache_key），绑错 = 重跑覆盖成品字幕。
//! 私有时期只能靠工具面复刻件出值，而复刻件重实现 serde 已实证字段面漂移（团队口径 babf），
//! 故把出值权收回 DS90 本体：键面一律由本体现算，工具面只作旁证（站长 2026-11-14 令②）。
//!
//! 三元组须取自库面真身（FTP MLSD 的 path / size / modify，modify 按 UTC 解读）。
//! 用法：
//!   cargo run --release --example acq_probe -- <config.toml> <video_path> <size> <mtime_epoch> [source_sha256...]

use std::time::{Duration, UNIX_EPOCH};

use anyhow::Result;
use subtrans::artifact::video_identity;
use subtrans::config::Config;
use subtrans::storage::FileEntry;
use subtrans::subtitles::{acquisition_key, cache_key};

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let config_path = args
        .next()
        .expect("usage: <config.toml> <video_path> <size> <mtime_epoch> [source_sha256...]");
    let path = args.next().expect("missing <video_path>");
    let size: u64 = args.next().expect("missing <size>").parse()?;
    let mtime: u64 = args.next().expect("missing <mtime_epoch>").parse()?;

    let cfg = Config::load(&config_path)?;
    let video = FileEntry {
        path,
        size,
        is_dir: false,
        modified: Some(UNIX_EPOCH + Duration::from_secs(mtime)),
    };

    println!("config = {config_path}");
    println!(
        "video path={} size={} mtime_epoch={}",
        video.path, video.size, mtime
    );
    println!("video_identity = {}", video_identity(&video));
    println!("acquisition_key = {}", acquisition_key(&video, &cfg)?);
    for source_sha256 in args {
        println!(
            "cache_key({source_sha256}) = {}",
            cache_key(&source_sha256, &cfg.translation)?
        );
    }
    Ok(())
}
