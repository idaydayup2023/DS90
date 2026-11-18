//! 诊断用（代码运维 · 2026-11-18）：对单个相对路径打印 `Storage::metadata()` 与底层各腿读数。
//!
//! 背景：2875 收编面放量里 58 枚判 `NO_VIDEO`，全部是**文件名含方括号**的底件
//! （`…AAC5.1-[YTS.MX].mp4`），而盘面 LIST/MLSD 实测该件在架。此例把「哪条腿断」定死。
//! 只读，零写。
//!
//! 用法: `cargo run --release --example meta_probe -- <config.toml> <relative/path>`

use anyhow::Result;
use subtrans::config::{Config, StorageConfig};
use subtrans::storage::open_storage;
use suppaftp::FtpStream;

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let Some(config_path) = args.next() else {
        eprintln!("usage: meta_probe <config.toml> <relative/path>");
        std::process::exit(2);
    };
    let Some(relative) = args.next() else {
        eprintln!("usage: meta_probe <config.toml> <relative/path>");
        std::process::exit(2);
    };

    let mut cfg = Config::load(&config_path)?;
    if let StorageConfig::Ftp { root, .. } = &mut cfg.source {
        *root = "/".to_string();
    }
    let storage = open_storage(&cfg.source)?;

    println!("relative = {relative}");
    match storage.metadata(&relative) {
        Ok(Some(e)) => println!(
            "  metadata() = SOME size={} is_dir={} modified={:?}",
            e.size, e.is_dir, e.modified
        ),
        Ok(None) => println!("  metadata() = NONE"),
        Err(e) => println!("  metadata() = ERR {e:#}"),
    }
    match storage.exists(&relative) {
        Ok(b) => println!("  exists()   = {b}"),
        Err(e) => println!("  exists()   = ERR {e:#}"),
    }

    let StorageConfig::Ftp {
        host,
        port,
        username_env,
        password_env,
        root,
        ..
    } = &cfg.source
    else {
        anyhow::bail!("本诊断例只针对 FTP 存储");
    };
    let user = std::env::var(username_env).unwrap_or_default();
    let pass = std::env::var(password_env).unwrap_or_default();
    let mut ftp = FtpStream::connect((host.as_str(), *port))?;
    ftp.login(&user, &pass)?;
    let remote = format!("{root}{relative}");
    println!("  pwd = {:?}", ftp.pwd());
    println!("  SIZE({remote}) = {:?}", ftp.size(&remote));
    match ftp.mlst(Some(&remote)) {
        Ok(line) => println!("  MLST ok, reply = {line:?}"),
        Err(e) => println!("  MLST err = {e:?}"),
    }
    let (parent, name) = relative.rsplit_once('/').unwrap_or(("", relative.as_str()));
    let parent_remote = format!("{root}{parent}");
    let previous = ftp.pwd().unwrap_or_else(|_| "/".to_string());
    let mut names = Vec::new();
    if ftp.cwd(&parent_remote).is_ok()
        && let Ok(lines) = ftp.mlsd(None)
    {
        names = lines
            .iter()
            .filter_map(|l| l.rsplit_once(' ').map(|(_, n)| n.to_string()))
            .collect();
    }
    let _ = ftp.cwd(&previous);
    println!("  父目录 {parent_remote} MLSD 条目 {} 条", names.len());
    println!(
        "  目标名在列举内 = {}  目标名 = {name:?}",
        names.iter().any(|n| n == name)
    );
    for n in names.iter().filter(|n| n.contains('[')).take(8) {
        println!("    bracket 条目: {n}");
    }
    let _ = ftp.quit();
    Ok(())
}
