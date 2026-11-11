#!/usr/bin/env python3
"""A 分支主修（模型应答缓存）正反控自验器 · 代码运维 · 2026-11-09

站长批复口径（11-09 11:17）：键 = sha256(provider+base_url+model+prompt)，
`translation.cache_dir` 缺省 None 全关，命中回灌必须仍走 parse_valid_indices
复验、畸形不采信不缓存，含正反控自验器（照 24/24 那套形制）。本件即该自验器。

三组检查，逐条独立判定，末行输出 `checks=NN passed=NN verdict=GREEN|RED`：

  R 组  引擎测试逐条点名跑（--exact），红一条即整体红：
        正控＝命中免烧（含真 HTTP 路径的 e2e）、缺省关闭与基线逐字一致；
        负控＝provider/base_url/model/prompt 各自单独变化都必须 miss、
             畸形缓存条目不采信并被剔除、畸形应答绝不入缓存、
             缓存写不进去也不拖垮跑批、cache_dir 不进序列化（防 cache_key 漂移）。
  K 组  键算式跨语言交叉验：Python 独立复刻「长度前缀拼接 + sha256」，与引擎
        源码里钉死的向量逐字对拍。算式一旦被改动，引擎侧与这里同时红。
  S 组  源码不变量：skip_serializing 还在、命中路径还在复验、模型只有一条
        被闸住的出口、四个调用点全部带 accept 谓词（无旁路）。

用法：
    python3 tools/l2_resp_cache_selftest_20261109.py
    python3 tools/l2_resp_cache_selftest_20261109.py --cargo /path/to/cargo
    python3 tools/l2_resp_cache_selftest_20261109.py --skip-engine   # 只跑 K/S
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
KEY_DOMAIN = "ds90-resp-cache-v1"

# 与引擎钉死的向量成对出现（K 组），改动算式即两头红。
VECTORS = [
    (
        ("ollama", "http://127.0.0.1:11434", "translategemma:4b", "PROMPT-VECTOR-1"),
        "ffa862f185ca0a66e964d7cb3af9e5ebee79c84cc7c030b5e7932c3ce06f7634",
    ),
    (
        ("openai_compatible", "https://litellm.invalid/v1", "Qwen3.8-Flash-Next", "提示词"),
        "41ca4a55257fa41f7396c9ae2c7f8c4f957859133c254f23e000f9dc2fa23c6d",
    ),
]

# R 组：(编号, 说明, 期望, cargo 参数)
ENGINE_CHECKS = [
    (
        "R01",
        "正控：已存应答回放不再调模型（含 3 次只烧 1 次）",
        "subtitles::translation::tests::a_stored_response_is_replayed_without_calling_the_model",
        ["--lib"],
    ),
    (
        "R02",
        "负控：base_url/model/prompt/provider 任一变即 miss",
        "subtitles::translation::tests::a_different_endpoint_model_or_prompt_is_never_a_hit",
        ["--lib"],
    ),
    (
        "R03",
        "负控：缓存条目畸形→不采信+剔除+回填",
        "subtitles::translation::tests::a_cached_payload_that_no_longer_parses_is_evicted_not_trusted",
        ["--lib"],
    ),
    (
        "R04",
        "负控：畸形应答绝不入缓存（下一次仍走模型）",
        "subtitles::translation::tests::a_response_that_never_parses_is_never_cached",
        ["--lib"],
    ),
    (
        "R05",
        "正控：未配 cache_dir 时每次都走模型（与基线逐字一致）",
        "subtitles::translation::tests::without_cache_dir_every_request_reaches_the_model",
        ["--lib"],
    ),
    (
        "R06",
        "负控：四要素入键，逐字稳定且互不混淆",
        "subtitles::resp_cache::tests::key_covers_every_part_that_selects_the_answer",
        ["--lib"],
    ),
    (
        "R07",
        "负控：长度前缀挡住相邻字段位移拼接歧义",
        "subtitles::resp_cache::tests::key_parts_cannot_shift_across_the_boundary",
        ["--lib"],
    ),
    (
        "R08",
        "正控：条目落盘/读回/剔除闭环",
        "subtitles::resp_cache::tests::entries_round_trip_and_evict",
        ["--lib"],
    ),
    (
        "R09",
        "正控：关闭态不碰文件系统",
        "subtitles::resp_cache::tests::a_disabled_cache_never_touches_the_filesystem",
        ["--lib"],
    ),
    (
        "R10",
        "负控：缓存写失败只记日志，不拖垮跑批",
        "subtitles::resp_cache::tests::a_write_failure_is_reported_but_never_fatal",
        ["--lib"],
    ),
    (
        "R11",
        "负控：cache_dir 不进序列化＝cache_key 不漂移",
        "subtitles::resp_cache::tests::cache_dir_does_not_reach_the_serialized_configuration",
        ["--lib"],
    ),
    (
        "R12",
        "正控：键算式钉死向量（与 K 组对拍）",
        "subtitles::resp_cache::tests::key_matches_the_vector_the_selftest_recomputes",
        ["--lib"],
    ),
    (
        "R13",
        "正控 e2e：真 HTTP 路径重跑 force，全程零模型连接",
        "response_cache_replays_a_finished_translation_without_calling_the_model",
        ["--test", "rust_subtitle_pipeline"],
    ),
]


def python_key(provider: str, base_url: str, model: str, prompt: str) -> str:
    """长度前缀拼接后 sha256，逐字照 resp_cache::response_key 复刻。"""
    digest = hashlib.sha256()
    for part in (KEY_DOMAIN, provider, base_url, model, prompt):
        blob = part.encode("utf-8")
        digest.update(len(blob).to_bytes(8, "little"))
        digest.update(blob)
    return digest.hexdigest()


def find_cargo(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("CARGO"):
        return os.environ["CARGO"]
    found = shutil.which("cargo")
    if found:
        return found
    # 本机姿势：rustup 走不通网络，直接用已装工具链里的 cargo。
    for candidate in (
        ROOT.parent / ".rust" / "rustup" / "toolchains",
        ROOT.parent / ".rustup" / "toolchains",
    ):
        if candidate.is_dir():
            for toolchain in sorted(candidate.glob("*/bin/cargo"), reverse=True):
                return str(toolchain)
    raise SystemExit("找不到 cargo：--cargo <path> 指定，或设 CARGO 环境变量")


def cargo_env(cargo: str) -> dict[str, str]:
    env = dict(os.environ)
    for name, relative in (
        ("CARGO_HOME", Path(".rust") / "cargo"),
        ("RUSTUP_HOME", Path(".rust") / "rustup"),
    ):
        candidate = ROOT.parent / relative
        if candidate.is_dir():
            env.setdefault(name, str(candidate))
    env.setdefault("CARGO_TERM_COLOR", "never")
    return env


def run_engine(cargo: str, extra: list[str], test_name: str) -> tuple[bool, str]:
    command = [cargo, "test", *extra, "--", "--exact", test_name]
    proc = subprocess.run(
        command, cwd=ROOT, env=cargo_env(cargo), capture_output=True, text=True, timeout=1800
    )
    text = proc.stdout + proc.stderr
    passed = proc.returncode == 0 and "test result: ok. 1 passed" in text
    if not passed:
        tail = [line for line in text.splitlines() if line.strip()][-8:]
        return False, " / ".join(tail)[:400]
    return True, "1 passed"


def read(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cargo", help="cargo 可执行文件路径")
    parser.add_argument("--skip-engine", action="store_true", help="只跑 K/S 组")
    args = parser.parse_args()

    cargo = find_cargo(args.cargo)
    results: list[tuple[str, str, bool, str]] = []

    def record(check: str, what: str, ok: bool, detail: str = "") -> None:
        results.append((check, what, ok, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {check}  {what}" + (f"  <- {detail}" if detail and not ok else ""))

    if not args.skip_engine:
        for check, what, test_name, extra in ENGINE_CHECKS:
            try:
                ok, detail = run_engine(cargo, extra, test_name)
            except subprocess.TimeoutExpired:
                ok, detail = False, "超时 1800 s"
            record(check, what, ok, detail)

    # K 组：键算式跨语言交叉验。
    source = read("subtitles/resp_cache.rs")
    record("K1", f"键域常量仍为 {KEY_DOMAIN}", f'const KEY_DOMAIN: &str = "{KEY_DOMAIN}"' in source)
    for index, (parts, expected) in enumerate(VECTORS, start=2):
        mine = python_key(*parts)
        record(f"K{index}", f"Python 独立复算 == 钉死向量 {parts[2]!r}", mine == expected and expected in source,
               f"python={mine} source_has_vector={expected in source}")

    # S 组：源码不变量。
    config = read("config.rs")
    translation = read("subtitles/translation.rs")
    field = re.search(
        r"#\[serde\(default, skip_serializing\)\]\s*pub cache_dir: Option<PathBuf>", config
    )
    record("S1", "config.rs：cache_dir 带 default+skip_serializing（防 cache_key 漂移）", field is not None)
    record(
        "S2",
        "translation.rs：命中分支先过 accept 复验再返回",
        re.search(
            r"if let Some\(cached\) = cache\.get\(key\) \{\s*if accept\(&cached\)", translation
        )
        is not None,
    )
    record(
        "S3",
        "translation.rs：入缓存前同样必须过 accept（畸形不缓存）",
        re.search(r"if accept\(&response\) \{\s*cache\.put\(", translation) is not None,
    )
    record(
        "S4",
        "translation.rs：模型出口只有一条，且只被带闸的 request 调用",
        translation.count("fn request_model(") == 1
        and translation.count("request_model(client, cfg, api_key, model, prompt, max_output_tokens)") == 1,
    )
    call_sites = len(re.findall(r"\brequest\(\s*\n?\s*client,", translation))
    accepted = translation.count("&accepts")
    record("S5", f"translation.rs：全部模型调用点都带 accept 谓词（{call_sites} 处）", call_sites == 4 and accepted >= 4,
           f"call_sites={call_sites} accepted={accepted}")
    record(
        "S6",
        "translation.rs：命中统计只在启用时出日志（关闭态日志逐字不变）",
        "summary_line(ResponseCache::new(cfg).dir())" in translation
        and "if let Some(summary)" in translation,
    )

    passed = sum(1 for _, _, ok, _ in results if ok)
    print(f"\nchecks={len(results)} passed={passed} verdict={'GREEN' if passed == len(results) else 'RED'}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
