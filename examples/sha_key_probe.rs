//! 只读探针（代码运维 · 2026-11-17 cache_key 定源/字段等价核对）
//! 用 DS90 **生产代码本体** `subtitles::cache_key` 现算 f(source_sha256 × [translation])。
//! 不联网、不读库面：纯函数对拍，供绑值复核与历史 toml 定源。
//!
//! 用法: cargo run --example sha_key_probe -- <shas.txt> <tomls.txt>
//!   shas.txt  每行一个 source_sha256
//!   tomls.txt 每行一个 config toml 路径
//! 输出: 先每档 toml 一行 `TOML\t<path>\tprompt_version=<v>\ttranslation=<canonical json>`，
//!       再每对 `KEY\t<sha>\t<toml>\t<cache_key>`。

use subtrans::config::Config;
use subtrans::subtitles::cache_key;

fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let shas_file = args.next().expect("usage: <shas.txt> <tomls.txt>");
    let tomls_file = args.next().expect("usage: <shas.txt> <tomls.txt>");
    let shas: Vec<String> = std::fs::read_to_string(&shas_file)?
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .map(str::to_string)
        .collect();
    let tomls: Vec<String> = std::fs::read_to_string(&tomls_file)?
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .map(str::to_string)
        .collect();
    let mut cfgs = Vec::with_capacity(tomls.len());
    for path in &tomls {
        let cfg = match Config::load(path) {
            Ok(cfg) => cfg,
            Err(error) => {
                println!("TOML_ERR\t{}\t{}", path, error);
                continue;
            }
        };
        println!(
            "TOML\t{}\tprompt_version=n/a\ttranslation={}",
            path,
            serde_json::to_string(&cfg.translation)?
        );
        cfgs.push((path.clone(), cfg.translation));
    }
    for sha in &shas {
        for (path, translation) in &cfgs {
            println!("KEY\t{}\t{}\t{}", sha, path, cache_key(sha, translation)?);
        }
    }
    Ok(())
}
