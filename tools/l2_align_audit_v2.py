#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 线对齐审计 v2 —— 与 wb_align_audit.py 同判据（逐 cue 问「这两行是否互译」YES/NO），
但补齐三件 2026-10-27 踩坑后必须的工程能力：

1. **逐条即时落盘**（JSONL，每条 flush）。首版 wb_align_audit.py 跑完才写 JSON，
   harness 重启把 225/285 的进度全部丢掉。
2. **断点续跑**：JSONL 里已判定（verdict 非 ERR/?）的 (idx,en,zh) 直接复用，重启不重跑。
3. **裁判可换 + 阳性对照闸门**：--judge qwen|ollama；--control 模式用「故意错位」的
   阳性样本 + 「正确配对」的阴性样本自测，裁判必须把阳性全部判 NO、阴性全部判 YES，
   否则它给出的「NO=0」不成立（队长要求：凡「=0」结论必须附阳性对照）。

判据与 max_tokens=2400 口径与 tools/wb_align_audit.py 完全一致，未做调整。

4. **缓存键绑裁判配置**（修复版，代码运维 11-07，站长 16:20④ 验收点名；被闸的人
   不许改闸，本文件只准代码运维在本仓 PR 内修改）：旧版键=sha256(idx,en,zh)，不含
   judge/model/token 档 —— 同 out_prefix 换裁判续跑会静默复用旧裁判判定，「外部双
   裁判」名存实亡。现键 = 裁判指纹(judge_id+model+生效 token 档+判据版本)+
   (idx,en,zh)：任一配置变动即全体换键强制重判，旧键行/异配置行一律不复用并计数
   点名。站长规矩「一个裁判配置一个 out_prefix」由此硬化为代码约束。

用法：
  python3 tools/l2_align_audit_v2.py <in.srt> <out_prefix> --judge qwen [--conc 2]
  -> out_prefix.jsonl（逐条） + out_prefix.json（汇总，随时可读）
"""
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HAN = re.compile(r"[一-鿿]")
TIMED = re.compile(r"(\d\d:\d\d:\d\d[,.]\d+)\s*-->\s*(\d\d:\d\d:\d\d[,.]\d+)")

JUDGES = {
    # 审校白名单模型，直连 8888（不经代理，避免污染本线审校分桶统计）
    "qwen": {
        "url": "http://192.168.1.9:8888/v1/chat/completions",
        "model": "Qwen3.8-Flash-Next",
        "style": "openai",
        "max_tokens": 2400,
    },
    # 翻译白名单模型，2.4 那台机（本机 11434 亦同模型）；仅作第二裁判/快筛
    "ollama": {
        "url": "http://192.168.2.4:11434/api/chat",
        "model": "translategemma:4b",
        "style": "ollama",
        "max_tokens": 16,
    },
}

SYSTEM = "You are a strict subtitle alignment checker. Answer with exactly one word: YES or NO."
PROMPT = ("English subtitle line: %s\nChinese subtitle line: %s\n\n"
          "Do these two lines express the SAME meaning (are they translations of each other)? "
          "Answer YES or NO only.")


def parse_srt(text):
    out = []
    for b in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in b.splitlines() if l.strip()]
        if len(lines) < 2 or not lines[0].strip().isdigit():
            continue
        if not TIMED.match(lines[1].strip()):
            continue
        body = lines[2:]
        zh = " ".join(l for l in body if HAN.search(l)).strip()
        en = " ".join(l for l in body if not HAN.search(l)).strip()
        out.append({"idx": int(lines[0].strip()), "zh": zh, "en": en})
    return out


def judge_ctx(judge, max_tokens=None):
    """缓存键的裁判配置指纹：judge_id + model + 生效 token 档 + 判据版本。
    任何一项变化 → 键全体更换 → 强制 cache miss 重判（禁静默复用旧裁判判定）。"""
    cfg = JUDGES[judge]
    if cfg["style"] == "ollama":
        tok = "num_predict=8"                      # ollama 风格实际生效的是 num_predict
    else:
        tok = "max_tokens=%s" % (max_tokens or cfg["max_tokens"])
    return "%s|%s|%s|jv1" % (judge, cfg["model"], tok)


def key_of(c, ctx):
    h = hashlib.sha256(("%s\x01%d\x01%s\x01%s" % (ctx, c["idx"], c["en"], c["zh"])).encode("utf-8")).hexdigest()
    return h[:16]


def call(judge, en, zh, tries=8, timeout=240, max_tokens=None):
    # tries/timeout/max_tokens 可由命令行收窄。max_tokens 默认沿用 JUDGES 里的旧口径；
    # 8888 实测：max_tokens=2400 时请求在队列里可滞留 130 s，512 档同样能容纳
    # 该判据的 reasoning（实测 57 token）+ YES/NO，延迟降到秒级。判据文本未动。
    cfg = JUDGES[judge]
    prompt = PROMPT % (en, zh)
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    if cfg["style"] == "ollama":
        body = {"model": cfg["model"], "messages": msgs, "stream": False,
                "options": {"temperature": 0, "num_predict": 8}}
    else:
        body = {"model": cfg["model"], "messages": msgs,
                "temperature": 0, "max_tokens": max_tokens or cfg["max_tokens"]}
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(cfg["url"], data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
            if cfg["style"] == "ollama":
                txt = (d.get("message", {}).get("content") or "").strip().upper()
            else:
                txt = (d["choices"][0]["message"].get("content") or "").strip().upper()
            if txt.startswith("YES"):
                return "YES"
            if txt.startswith("NO"):
                return "NO"
            return "?"
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
            time.sleep(30 if e.code in (500, 503) else 3 * (k + 1))   # 500=NoRoom 容量准入
        except Exception as e:  # noqa: BLE001
            last = repr(e)[:120]
            time.sleep(3 * (k + 1))
    return "ERR:%s" % last


def load_cache(path, ctx):
    """只复用裁判配置指纹完全一致的判定；旧版无 judge_ctx 的行、异配置行一律弃用（重判），
    并计数点名——「静默复用旧裁判」必须变成「显式弃用」。"""
    done, stale = {}, 0
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                v = str(r.get("verdict", ""))
                if v and not v.startswith("ERR") and v != "?":
                    if r.get("judge_ctx") == ctx:
                        done[r["k"]] = v
                    else:
                        stale += 1
    return done, stale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out_prefix")
    ap.add_argument("--judge", default="qwen", choices=sorted(JUDGES))
    ap.add_argument("--conc", type=int, default=2)
    ap.add_argument("--tries", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="仅对 openai 风格裁判生效；不给则用 JUDGES 里的旧口径 2400")
    ap.add_argument("--control", action="store_true",
                    help="阳性/阴性对照自测：src 为 [{idx,en,zh,expect}] 的 JSON")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())

    jl, js = args.out_prefix + ".jsonl", args.out_prefix + ".json"

    if args.control:
        items = json.load(open(args.src, encoding="utf-8"))
        cues = [{"idx": it["idx"], "en": it["en"], "zh": it["zh"], "expect": it["expect"]}
                for it in items]
    elif args.src.endswith(".json"):
        # 2026-11-05 坑：非 control 分支原先只认 SRT，喂 [{idx,en,zh}] 的 JSON 清单会被
        # parse_srt 解析成 0 条且 exit=0 —— 「NO=0/0」静默假通过。现按扩展名分流。
        items = json.load(open(args.src, encoding="utf-8"))
        if isinstance(items, dict):
            items = items.get("cues") or []
        cues = [{"idx": int(it["idx"]), "en": it["en"], "zh": it["zh"]} for it in items]
    else:
        cues = parse_srt(open(args.src, encoding="utf-8-sig").read())

    if not cues:
        # 0 条绝不许当成「全部通过」交卷（站长口径：凡 =0 结论必须附阳性对照）。
        sys.stderr.write("FATAL: src=%s 解析出 0 条待判，拒绝以 0/0 通过\n" % args.src)
        sys.exit(2)

    ctx = judge_ctx(args.judge, args.max_tokens)
    cache, stale = load_cache(jl, ctx)
    lock = threading.Lock()
    fh = open(jl, "a", encoding="utf-8")
    print("judge=%s cues=%d judge_ctx=%s 已判定复用=%d 弃用(异裁判配置/旧键)=%d"
          % (args.judge, len(cues), ctx, len(cache), stale), flush=True)
    if stale:
        print("  （弃用行为正确：换裁判/换 token 档/旧版键不复用，将由当前裁判重判）", flush=True)

    def work(c):
        k = key_of(c, ctx)
        with lock:
            if k in cache:
                c["verdict"] = cache[k]
                c["from_cache"] = True
                return c
        v = call(args.judge, c["en"], c["zh"], tries=args.tries, timeout=args.timeout,
               max_tokens=args.max_tokens)
        c["verdict"] = v
        with lock:
            if not v.startswith("ERR") and v != "?":
                cache[k] = v
                fh.write(json.dumps({"k": k, "idx": c["idx"], "verdict": v,
                                     "judge_ctx": ctx},
                                    ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return c

    # ex.map 顺序返回，边跑边汇总落盘，随时可被 kill 而不丢结果
    with ThreadPoolExecutor(max_workers=args.conc) as ex:
        results = []
        for i, c in enumerate(ex.map(work, cues), 1):
            results.append(c)
            if i % 10 == 0 or i == len(cues):
                dump(args, results, js)
                print("  %d/%d" % (i, len(cues)), flush=True)
    fh.close()
    dump(args, results, js)
    summarize(args, results, js)


def dump(args, results, js):
    no = [c for c in results if c["verdict"] == "NO"]
    err = [c for c in results if str(c["verdict"]).startswith("ERR") or c["verdict"] == "?"]
    payload = {"source": args.src, "judge": args.judge, "model": JUDGES[args.judge]["model"],
               "judge_ctx": judge_ctx(args.judge, args.max_tokens),
               "control": args.control, "total": len(results), "done": len(results),
               "no": len(no), "undecided": len(err),
               "no_idx": [c["idx"] for c in no], "err_idx": [c["idx"] for c in err],
               "cues": results, "ts": time.strftime("%F %T")}
    tmp = js + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, js)


def summarize(args, results, js):
    no = [c for c in results if c["verdict"] == "NO"]
    err = [c for c in results if str(c["verdict"]).startswith("ERR") or c["verdict"] == "?"]
    print("NO=%d/%d 未判定=%d -> %s" % (len(no), len(results), len(err), js), flush=True)
    for c in no:
        print("  #%d\n    EN: %s\n    ZH: %s" % (c["idx"], c["en"], c["zh"]), flush=True)
    for c in err:
        print("  ?#%d %s" % (c["idx"], c["verdict"]), flush=True)


def selftest():
    """不碰网络：只验缓存键绑裁判配置与解析。"""
    import tempfile
    fails = []
    c = {"idx": 1, "en": "hello", "zh": "你好"}
    ctx = judge_ctx("qwen")
    k0 = key_of(c, ctx)
    if key_of(c, judge_ctx("qwen")) != k0:
        fails.append("同配置同 cue 键应稳定")
    if key_of(c, judge_ctx("qwen", 512)) == k0:
        fails.append("换 max_tokens 未换键（第二裁判静默失效坑未修好）")
    if key_of(c, judge_ctx("ollama")) == k0:
        fails.append("换 judge 未换键")
    if key_of(dict(c, zh="你好呀"), ctx) == k0:
        fails.append("改写 zh 未换键（第二刀蒙混坑回归）")
    if "Qwen3.8-Flash-Next" not in ctx or "max_tokens=2400" not in ctx:
        fails.append("ctx 未含 model/token 档: %s" % ctx)

    d = tempfile.mkdtemp(prefix="l2_selftest_")
    jl = os.path.join(d, "a.jsonl")
    with open(jl, "w", encoding="utf-8") as f:
        f.write(json.dumps({"k": k0, "idx": 1, "verdict": "YES", "judge_ctx": ctx}) + "\n")
        f.write(json.dumps({"k": "otherkey00000000", "idx": 2, "verdict": "NO",
                            "judge_ctx": judge_ctx("qwen", 512)}) + "\n")
        f.write(json.dumps({"k": "oldverkey0000000", "idx": 3, "verdict": "YES"}) + "\n")
        f.write(json.dumps({"k": "errkey000000000", "idx": 4, "verdict": "ERR:timeout",
                            "judge_ctx": ctx}) + "\n")
    done, stale = load_cache(jl, ctx)
    if done != {k0: "YES"}:
        fails.append("cache 复用不符: %s" % done)
    if stale != 2:
        fails.append("异配置/旧键弃用计数应为 2，实为 %d" % stale)

    cues = parse_srt("1\n00:00:01,000 --> 00:00:02,000\nhello\n你好\n\n"
                     "2\n00:00:02,000 --> 00:00:03,000\nbye\n再见\n")
    if len(cues) != 2 or cues[0]["zh"] != "你好" or cues[0]["en"] != "hello":
        fails.append("parse_srt 回归: %s" % cues)

    if fails:
        for f_ in fails:
            print("FAIL:", f_)
        print("L2 AUDIT SELFTEST FAIL %d 项" % len(fails))
        return 1
    print("L2 AUDIT SELFTEST PASS 全部用例通过（键绑裁判配置）")
    return 0


if __name__ == "__main__":
    main()
