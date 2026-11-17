//! 只读新建面探针（代码运维 · 2026-11-17 · 未管理 .ai 收编第二步 G8 先导验具）
//! 用 DS90 **生产代码本体**现算新建 manifest 的键面与哈希：
//!   video_identity（artifact::video_identity）/ source_sha256、output_sha256（storage::sha256）
//!   / cache_key（subtitles::cache_key 按跑批 toml）/ acquisition_key（subtitles::acquisition_key）
//! 并就地做增件闸门读数：派生产物名与 manifest 名是否已在盘面存在、底件/源轨/产物三元是否齐。
//! 不写盘、不 RETR 正片（只 RETR 两份字幕小件）。
//! 用法: cargo run --release --example manifest_new_probe -- <config.toml> <video_rel> <source_rel> [source_kind_ignored]

use anyhow::Result;
use subtrans::artifact::{
    SubtitleArtifact, artifact_paths, validate_manifest_for_publish, video_identity,
};
use subtrans::config::Config;
use subtrans::subtitles::{acquisition_key, cache_key, source_kind_for};

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let config_path = args
        .next()
        .expect("usage: <config.toml> <video_rel> <source_rel> <source_kind>");
    let video_path = args.next().expect("missing <video_rel>");
    let source_path = args.next().expect("missing <source_rel>");
    let kind_arg = args.next();

    let mut cfg = Config::load(&config_path)?;
    if let subtrans::config::StorageConfig::Ftp { root, .. } = &mut cfg.source {
        *root = "/".to_string();
    }
    let storage = subtrans::storage::open_storage(&cfg.source)?;

    println!("config = {config_path}");
    println!("video_rel = {video_path}");
    let video = match storage.metadata(&video_path)? {
        Some(entry) => entry,
        None => {
            println!("  RESULT         = NO_VIDEO");
            return Ok(());
        }
    };
    let paths = artifact_paths(&video.path)?;
    let identity = video_identity(&video);

    // 站长 13:3x 五裁③：source_kind 一律由引擎 rank 词表现给，工具面禁止手写内容来路值。
    let video_stem = video
        .path
        .rsplit('/')
        .next()
        .unwrap_or(video.path.as_str())
        .rsplit_once('.')
        .map_or(video.path.as_str(), |(stem, _)| stem);
    let engine_kind = source_kind_for(&source_path, video_stem);
    println!("  video_stem     = {video_stem}");
    println!("  source_kind_engine = {engine_kind:?}");
    if let Some(arg) = &kind_arg {
        println!("  source_kind_arg = {arg} (ignored, 仅审计对照)");
    }
    let source_kind = match engine_kind {
        Some(kind) => kind.to_string(),
        None => {
            println!("  RESULT         = NO_SOURCE_KIND source={source_path}");
            return Ok(());
        }
    };

    let source_sha256 = if storage.exists(&source_path)? {
        storage.sha256(&source_path)?
    } else {
        println!("  RESULT         = NO_SOURCE source={source_path}");
        return Ok(());
    };
    let output_sha256 = if storage.exists(&paths.output)? {
        storage.sha256(&paths.output)?
    } else {
        println!("  RESULT         = NO_OUTPUT output={}", paths.output);
        return Ok(());
    };

    let ck = cache_key(&source_sha256, &cfg.translation)?;
    let ak = acquisition_key(&video, &cfg)?;

    println!("  video_size     = {}", video.size);
    println!(
        "  video_mtime    = {:?}",
        video
            .modified
            .and_then(|m| m.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|d| d.as_secs())
    );
    println!("  video_identity = {identity}");
    println!("  source_path    = {source_path}");
    println!("  source_sha256  = {source_sha256}");
    println!("  output_path    = {}", paths.output);
    println!("  output_sha256  = {output_sha256}");
    println!("  manifest_path  = {}", paths.manifest);
    println!("  manifest_exists = {}", storage.exists(&paths.manifest)?);
    println!("  cache_key      = {ck}");
    println!("  acquisition_key = {ak}");
    println!("  source_kind    = {source_kind}");

    let manifest = SubtitleArtifact {
        schema: subtrans::artifact::ARTIFACT_SCHEMA,
        status: "ready".to_string(),
        video_path: video.path.clone(),
        video_identity_sha256: identity,
        source_sha256,
        output_sha256,
        cache_key: ck,
        acquisition_key: ak,
        source_kind,
        source_path: Some(source_path),
        source_evidence: None,
        translation_quality_log: vec![],
        created_unix_seconds: std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or_default(),
    };
    validate_manifest_for_publish(&manifest)?;
    println!("  VALIDATE       = ok");
    println!("---BEGIN-MANIFEST---");
    println!("{}", serde_json::to_string_pretty(&manifest)?);
    println!("---END-MANIFEST---");
    Ok(())
}
