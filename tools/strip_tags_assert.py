#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可复用断言器：去标签后整份文件文字逐字相同（**独立字符扫描器，非正则**）。

出处：DS90站长 2026-10-22 立为通用规则 ——
  「任何用正则改写字幕，必须配一个独立的、全文件级的『去标签后整份文件文字逐字相同』断言，
    且断言器不得复用改写用的同一套正则」
 起因：2026-10-22 我自曝 —— 断言器与改写器共用同一套宽松正则，畸形开标签 `<i他没有回来。</i>`
       被整段吞掉、正文清空，而断言两边都成空所以照样 PASS（一个不设防的校验等于没有校验）。

本工具的实现是**字符扫描器**：
  - 规范标签 `<i>` `<i attr="x">` `<i/>` `<i />` `</i>` `</i attr>`  → 整体剥掉
  - 畸形开标签 `<i` 后直接跟非 / > 空白 的字符（如 `<i他没有回来。</i>`）
    → **只吃 "<i" 两个字符**，正文一律保留（正是当初吞正文的坑）
  - 其它 `<` 原样保留

用法：
  python3 tools/strip_tags_assert.py <fileA> <fileB>          # 断言 strip(A)==strip(B)
  python3 tools/strip_tags_assert.py <fileA> <fileB> --json out.json
  python3 tools/strip_tags_assert.py --selftest                # 自测（含阳性/阴性对照）
退出码：0 = 通过，1 = 不通过
"""
import hashlib
import json
import os
import sys

__all__ = ["strip_tags", "strip_file", "assert_same_text", "scan_pairs"]


def strip_tags(text):
    """剥掉全部 <i…> 标签（含闭标签与畸形开标签），返回纯文字。字符扫描器实现。"""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("</i", i):
            k = text.find(">", i)
            i = (k + 1) if k != -1 else (i + 3)
            continue
        if text.startswith("<i", i):
            j = i + 2
            if j < n and text[j] == ">":
                i = j + 1
                continue
            if j < n and (text[j] == "/" or text[j].isspace()):
                k = text.find(">", j)
                i = (k + 1) if k != -1 else j
                continue
            # 畸形开标签：只吃 "<i"，正文保留
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def read_text(path):
    """编码容错读取（库内字幕件不一定都是 UTF-8）。"""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def strip_file(path):
    return strip_tags(read_text(path))


def assert_same_text(path_a, path_b):
    """返回 (ok, detail)。detail 含两侧 sha256、strip 后 sha256、首个差异位置。"""
    ta, tb = read_text(path_a), read_text(path_b)
    sa, sb = strip_tags(ta), strip_tags(tb)
    ok = (sa == sb)
    detail = {
        "a": path_a, "b": path_b,
        "a_sha": hashlib.sha256(ta.encode("utf-8")).hexdigest(),
        "b_sha": hashlib.sha256(tb.encode("utf-8")).hexdigest(),
        "a_strip_sha": hashlib.sha256(sa.encode("utf-8")).hexdigest(),
        "b_strip_sha": hashlib.sha256(sb.encode("utf-8")).hexdigest(),
        "equal": ok,
    }
    if not ok:
        n = min(len(sa), len(sb))
        pos = next((k for k in range(n) if sa[k] != sb[k]), n)
        detail["first_diff_pos"] = pos
        detail["a_ctx"] = sa[max(0, pos - 60):pos + 60]
        detail["b_ctx"] = sb[max(0, pos - 60):pos + 60]
    return ok, detail


def scan_pairs(pairs):
    """pairs = [(a_path, b_path), …] → 汇总结果。"""
    rows = []
    ok_all = True
    for a, b in pairs:
        ok, d = assert_same_text(a, b)
        ok_all &= ok
        rows.append(d)
    return ok_all, rows


def _selftest():
    """自测：含阳性对照（能检出差异）与阴性对照（畸形标签不吃正文）。"""
    cases = [
        ("<i>你好</i>", "你好", "规范标签"),
        ("<i lang=\"es\">你好</i>", "你好", "带属性"),
        ("<i/>", "", "自闭合"),
        ("<i>你好</i>", "你好", "剥后应得纯文字"),
        ("<i他没有回来。</i>", "他没有回来。", "畸形开标签只吃 2 字符"),
        ("a<i>b</i>c", "abc", "行内"),
        ("<i>a</i><i>b</i>", "ab", "两个标签"),
        ("</i>orphan", "orphan", "孤立闭标签也剥掉（是标记不是正文）"),
        ("1 < 2", "1 < 2", "非标签的 < 原样保留"),
    ]
    ok = True
    for src, want, why in cases:
        got = strip_tags(src)
        good = (got == want)
        ok &= good
        print("  %-5s %-28s → %-20r 期望 %-20r  %s"
              % ("PASS" if good else "FAIL", src[:28], got, want, why))
    # 阳性对照：两个不同文字必须被检出
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        pa, pb = os.path.join(td, "a.srt"), os.path.join(td, "b.srt")
        open(pa, "w", encoding="utf-8").write("<i>甲</i>乙")
        open(pb, "w", encoding="utf-8").write("<i>丙</i>乙")
        okk, d = assert_same_text(pa, pb)
        print("  %-5s 阳性对照：文字不同必须检出差异 → %s（first_diff_pos=%s）"
              % ("PASS" if not okk else "FAIL", "已检出" if not okk else "未检出",
                 d.get("first_diff_pos")))
        ok &= (not okk)
    print("\n自测总判定: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--selftest":
        return _selftest()
    if len(argv) < 2:
        print(__doc__)
        return 2
    out_json = None
    if "--json" in argv:
        i = argv.index("--json")
        out_json = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    ok, rows = scan_pairs([(argv[0], argv[1])])
    for d in rows:
        print("去标签后逐字相同: %s" % ("PASS" if d["equal"] else "FAIL"))
        print("  %s\n    sha      = %s" % (d["a"], d["a_sha"]))
        print("  %s\n    sha      = %s" % (d["b"], d["b_sha"]))
        print("  strip 后 sha  %s / %s" % (d["a_strip_sha"], d["b_strip_sha"]))
        if not d["equal"]:
            print("  首个差异位置 %s\n    A: %r\n    B: %r"
                  % (d["first_diff_pos"], d["a_ctx"], d["b_ctx"]))
    if out_json:
        json.dump(rows, open(out_json, "w"), ensure_ascii=False, indent=1)
        print("written", out_json)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
