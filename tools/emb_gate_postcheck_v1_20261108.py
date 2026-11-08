#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""emb 元话语修复写库 v2 · 闸门侧后验器具 v1（代码运维·非作者·fail-closed）。

站长 11-08 批复口径（四条全批）：
  ass 版五断言：①Dialogue 全局序号连续+奇偶自证（偶=中文行）
               ②新中文行非空/非纯标点/占位符残留=0（限本批新写行；全卷占位数旧↔新不增）
               ③新中文行无元话语/思考流——词表来自 tools/emb_gate_leaklex_20261108.py
                 （落仓固化·中途不得换表；版本号随 round 卷面记录）
               ④tag 白名单 + BROKEN 畸形开标签扫描（两段式 WELL/BROKEN 独立解析，
                 不与改写方共用正则——10-22 教训）
               ⑤去标签后全文件文字逐字相同，豁免面恰=清单本批中文行；EN 行/时间轴/
                 Style 头零改动
  TOCTOU 三断言：_Trash 留底逐条==清单 cur_zh；journal 改前 sha==我侧 _Trash 实拉；
               改动面 ⊆ 清单（本器以字节级还原强化：留底按清单正向映射重建 ≡ 库内新件）。
               留底对拍红＝区间内件被动过 → 该件停报站长，由执行方重编该件清单；
               闸门侧不改写清单内容，只判红绿（站长 11-08 硬规矩）。
  完卷三件套：sha 全值 + size + Dialogue 序号数
  每件全量旧↔新逐 cue 对拍（FBWL④ 定式，双侧我侧 RETR 原件）
  跨卷面对账主键＝(file,cue)；各卷 n 只作序号连续自证、不互校（站长 11-08 照准）。

 inline_bilingual 特例形制（站长 11-08 特例批裁定，Spit 案）：
  合并双语行件（单条 Dialogue 内 {\r中文}中文段\N{\rEnglish_N}英文段、Style 全列单一）
  天然违反「cue 偶=中文行」——**生效唯一通道＝清单逐件显式声明**：
    清单顶层 file_formats{"<file>": "inline_bilingual"} 或 item.format 同值（自洽断言）。
  闸门双向 fail-closed：声明而实测不符＝红；实测符合而未声明＝红停报，绝不自动豁免。
  豁免只免①奇偶判；序号数连续照跑。替代断言四条全跑：
    a) Style 列全文件零改动（全部条）；b) 英文段逐字同（en_segments 我侧两段式自切，
       不与改写方共用正则）；c) 每行结构不变量（\N 计数/{\r 计数/override 标签集合）；
    d) 改动面细化到段（清单条改动 ⊆ cue 集；非清单条整行逐字同——由⑤字节级还原覆盖）。
  new_zh 语义（清单可声明 new_zh_semantics，默认 full_line）：
    full_line＝new_zh 为整条新 text；cn_segment＝new_zh 为**中文侧完整文本**（须含
    {\r中文} override 与 \N 分隔），闸门拼旧件英文侧成期望行；丢结构由 inline-c 拦截。

用法（备而不发，站长 GO 才跑）：
  连库跑：emb_gate_postcheck_v1_20261108.py GO --batch-name B --journal <path> \
          --trash /volume1/homes/_Trash/B [--only fileA fileB ...] [--rounds 2]
  离线自检：emb_gate_postcheck_v1_20261108.py selftest   （零连库，验断言器本身）
每轮全部新开 FTP 连接；SSH 仅只读 df 核 _Trash 落盘分区（11-04 教训：禁 md0）。
任何断言红 → exit 2 停手报站长，不带伤放行、不重试。
"""
import argparse, ftplib, hashlib, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from emb_gate_leaklex_20261108 import (LEX_VERSION, LEAK_STRONG, LEAK_WEAK, PLACEHOLDER,
                                       HAN, LATIN, TAG_WELL, OVERRIDE, TAG_WHITELIST,
                                       RESIDUE, JOURNAL_KEYS_OLD, JOURNAL_KEYS_NEW,
                                       JOURNAL_KEYS_FILE)

WS = os.path.dirname(os.path.dirname(HERE))  # 仓内跑：DS90/tools→DS90→ws；ws/tools 跑同径
if not os.path.isdir(os.path.join(WS, "logs")):
    WS = os.path.dirname(HERE) if os.path.isdir(os.path.join(os.path.dirname(HERE), "logs")) \
        else os.getcwd()
LIST_JSON = os.environ.get(
    "EMB_GATE_LIST",
    os.path.join(WS, "logs", "landing_2026-11-08", "landing_list_v2_2026-11-08.json"))
SSH = os.environ.get("DS90_SSH", os.path.join(HERE, "ds90_ssh.sh"))
HOST, PORT = "172.19.60.90", 10021
U = os.environ.get("DSH_SECRET_SUBTRANS_FTP_USERNAME", "")
P = os.environ.get("DSH_SECRET_SUBTRANS_FTP_PASSWORD", "")


# ---------- FTP/SSH 底座（FBWL 后验同款，我侧自持） ----------
def conn():
    f = ftplib.FTP()
    f.connect(HOST, PORT, timeout=120)
    f.login(U, P)
    f.set_pasv(True)
    f.voidcmd("TYPE I")
    return f


def listing(d):
    """目录清单。11-08 实测坑：群晖 FTPd 对**目录名含 [ ]** 的路径，绝对路径 MLSD/LIST
    一律返 0 条（e1 作用域 50 目录里 21 个中招），而 CWD 进目录再列完全正常。
    绝对路径直列会让 size 断言变红（尚可发现），但「目录无残留」拿到空表＝**空表假绿**。
    故：一律 CWD 进目录再列；MLSD 空则退 LIST；两路皆空即抛（fail-closed，禁空表过关）。"""
    f = conn()
    try:
        try:
            f.cwd(d)
        except ftplib.error_perm as e:
            raise AssertionError("CWD 失败（目录不存在或不可达）%s: %s" % (d, e))
        out = {}
        for name, facts in f.mlsd(""):
            facts = dict(facts)
            if facts.get("type") != "file":
                continue
            out[name] = {"size": int(facts.get("size", -1)), "modify": facts.get("modify", ""),
                         "owner": facts.get("unix.owner", "")}
        if not out:
            rows = []
            f.dir("", rows.append)
            for r in rows:
                parts = r.split()
                if len(parts) >= 9 and parts[0][0] in "-l":
                    out[parts[-1]] = {"size": int(parts[4]), "modify": " ".join(parts[5:8]),
                                      "owner": parts[2]}
        if not out:
            raise AssertionError("目录列空（MLSD/LIST 双路皆空），无法核 size/残留: %s" % d)
        return out
    finally:
        f.quit()


def pull(path):
    """新连接 RETR → (bytes, sha256)；size 以第二条连接 MLSD 交叉。"""
    f = conn()
    try:
        size = listing(os.path.dirname(path)).get(os.path.basename(path), {}).get("size")
        buf = []
        f.retrbinary("RETR " + path, buf.append, 1 << 20)
        b = b"".join(buf)
    finally:
        f.quit()
    if size is not None and size >= 0:
        assert len(b) == size, "RETR 短读 %s: %d != MLSD size %d" % (path, len(b), size)
    return b, hashlib.sha256(b).hexdigest()


def ssh_ro(cmd, timeout=180):
    p = subprocess.run(["bash", SSH, cmd], capture_output=True, text=True, timeout=timeout)
    return (p.stdout or "").strip(), p.returncode


# ---------- 独立 ass 解析（两段式 WELL/BROKEN，10-22 教训） ----------
def parse_ass(b):
    """bytes → dict：lines(keepends)、by_ordinal{ordinal:{line_no,head,text,style,marker_labels,n_backslashN,n_override}}、ordinals。"""
    try:
        txt = b.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise AssertionError("非 UTF-8，fail-closed: %s" % e)
    lines = txt.splitlines(keepends=True)
    text_col, style_col, in_events = None, None, False
    dlg, ordn = [], 0
    for i, ln in enumerate(lines):
        s = ln.rstrip("\r\n")
        if s.startswith("[Events]"):
            in_events = True
            continue
        if s.startswith("["):
            in_events = False
            continue
        if in_events and s.startswith("Format:"):
            fields = [x.strip() for x in s[len("Format:"):].split(",")]
            if "Text" in fields:
                text_col = fields.index("Text")
            if "Style" in fields:
                style_col = fields.index("Style")
            continue
        if in_events and s.startswith("Dialogue:"):
            ordn += 1
            rest = s[len("Dialogue:"):]
            if text_col is None:
                raise AssertionError("第 %d 行前有 Dialogue 但无 Format:Text 定义" % (i + 1))
            parts = rest.split(",", text_col)
            assert len(parts) == text_col + 1, "Dialogue 列数不足 line %d" % (i + 1)
            style = parts[style_col].strip() if style_col is not None and style_col < text_col else None
            t = parts[-1]
            dlg.append({"line_no": i + 1, "ordinal": ordn, "style": style,
                        "marker_labels": tuple(m.group(1) for m in MARKER.finditer(t)),
                        "n_backslashN": t.count("\\N"), "n_override": t.count("{\\r"),
                        "head": "Dialogue:" + ",".join(parts[:-1]) + ",", "text": t})
    assert text_col is not None, "全文无 Format: Text"
    return {"lines": lines, "dlg": dlg, "ordinals": ordn,
            "by_ordinal": {d["ordinal"]: d for d in dlg}}


MARKER = re.compile(r"\{\\r([^}]*)\}")


def en_segments(text):
    """我侧独立两段式切分（11-08 站长令：不与改写方共用正则）。
    返回 tuple[(label, 其后英文段)]——label 以 English 开头者；及其前中文段 cn_head。"""
    ms = list(MARKER.finditer(text))
    segs = []
    cn_head = text
    for k, m in enumerate(ms):
        end = ms[k + 1].start() if k + 1 < len(ms) else len(text)
        if m.group(1).lower().startswith("english"):
            segs.append((m.group(1), text[m.end():end]))
            cn_head = text[:m.start()]
    return tuple(segs), cn_head


def classify_inline(p):
    """单行双语形制实测：Style 列单一值 且 每条 Dialogue 含 English override。
    返回 (is_inline, reason)。仅作复核用——生效必须靠清单显式声明（双向 fail-closed）。"""
    if not p["dlg"]:
        return False, "无 Dialogue"
    styles = {d["style"] for d in p["dlg"]}
    if len(styles) != 1:
        return False, "Style 非单一值: %s" % sorted(map(str, styles))[:4]
    no_en = [d["ordinal"] for d in p["dlg"]
             if not any(lb.lower().startswith("english") for lb in d["marker_labels"])]
    if no_en:
        return False, "无 English override 的条数=%d 首=%s" % (len(no_en), no_en[:5])
    return True, "Style=%s 全 %d 条含 English override" % (list(styles)[0], len(p["dlg"]))


def expected_new_text(x, dO, semantics):
    """清单声明新文本 → 期望的新行 text。
    full_line：new_zh 即整条 text；cn_segment：新中文段 + 旧件英文侧逐字保留拼接。"""
    if dO is None:
        return None
    if semantics != "cn_segment":
        return x["new_zh"]
    segs, cn_head = en_segments(dO["text"])
    if not segs:
        return None  # 声明 cn_segment 但旧条无英文段——调用侧判红
    return x["new_zh"] + dO["text"][len(cn_head):]


def strip_tags(s):
    """WELL 吃规范标签；BROKEN 只吃畸形开标签 2 字符（两段式，独立实现）。"""
    s = OVERRIDE.sub("", s)
    out, i = [], 0
    while i < len(s):
        if s[i] == "<":
            close = s.find(">", i + 1)
            nxt = s.find("<", i + 1)
            if close != -1 and (nxt == -1 or close < nxt):
                i = close + 1  # WELL：整体丢弃
                continue
            i += 2  # BROKEN：只吃畸形开标签 2 字符
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def broken_tags(s):
    """BROKEN 畸形开标签位置列表（'<' 无配对 '>' 即算）。"""
    hits, i = [], 0
    while i < len(s):
        if s[i] == "<":
            close = s.find(">", i + 1)
            nxt = s.find("<", i + 1)
            if close == -1 or (nxt != -1 and nxt < close):
                hits.append(i)
                i += 2
                continue
            i = close + 1
            continue
        i += 1
    return hits


# ---------- 断言器 ----------
class Gate:
    def __init__(self):
        self.checks = []

    def ck(self, name, ok, got=None, expected=None, file=None, level="fail"):
        self.checks.append({"name": name, "file": file, "ok": bool(ok), "got": got,
                            "expected": expected, "level": level})
        return bool(ok)

    @property
    def reds(self):
        return [c for c in self.checks if not c["ok"] and c["level"] == "fail"]


def journal_index(path):
    """journal jsonl/json → {basename: {old,new,raw}}；字段名弹性，缺字段后验判红。"""
    ent = {}
    if not path or not os.path.exists(path):
        return ent
    raw = open(path, encoding="utf-8").read().strip()
    rows = []
    try:
        j = json.loads(raw)
        rows = j if isinstance(j, list) else j.get("entries") or j.get("items") or []
    except json.JSONDecodeError:
        for ln in raw.splitlines():
            ln = ln.strip()
            if ln:
                rows.append(json.loads(ln))

    def pick(d, keys):
        for k in keys:
            if isinstance(d, dict) and d.get(k):
                return d[k]
        return None

    for r in rows:
        fn = pick(r, JOURNAL_KEYS_FILE)
        if not fn:
            continue
        ent[os.path.basename(fn)] = {"old": pick(r, JOURNAL_KEYS_OLD),
                                     "new": pick(r, JOURNAL_KEYS_NEW), "raw": r}
    return ent


def check_new_text(g, base, text, side):
    """对本批新写中文行跑 ②③④。"""
    st = strip_tags(text).strip()
    g.ck("②新中文行非空[%s]" % side, bool(st), got=repr(text[:40]), expected="非空", file=base)
    g.ck("②非纯标点[%s]" % side, bool(HAN.search(st)) or bool(LATIN.search(st)),
         got=repr(st[:40]), expected="含汉字或字母", file=base)
    g.ck("②无占位符残留[%s]" % side, not PLACEHOLDER.match(st),
         got=repr(st[:40]), expected="≠[中文翻译]/[英文翻译]", file=base)
    hs = [m.group(0) for m in LEAK_STRONG.finditer(st)]
    g.ck("③无强元话语[%s]" % side, not hs, got=",".join(hs) or None, expected="0", file=base)
    bw = broken_tags(text)
    g.ck("④无BROKEN畸形开标签[%s]" % side, not bw, got=bw or None, expected="[]", file=base)
    # TAG_WELL 连尖角括号一起吐出（`<i>`），而 TAG_WHITELIST 表体是**去括号的内文形**
    # （`/?[ibuf]`、`/font`、`font color="#hex6"`）——原样喂入则永不命中＝任何带 tag 的
    # 行必红（11-08 e1 实测 5 件 8 条误红）。表体冻结不动（站长「中途不得换表」），
    # 只修正调用侧：剥掉尖角括号再按表体口径匹配。
    unknown = [t for t in TAG_WELL.findall(text)
               if not TAG_WHITELIST.match(t.strip().strip("<>").lower())]
    g.ck("④tag白名单内[%s]" % side, not unknown, got=",".join(unknown) or None,
         expected="⊆{i,b,u,font color,#font}", file=base)
    weak = [m.group(0) for m in LEAK_WEAK.finditer(st)]
    if weak:
        g.ck("③弱泄漏候审[%s]" % side, True, got=",".join(weak), expected="附报", file=base,
             level="report")


def ph_count(pa):
    return sum(1 for x in pa["dlg"] if PLACEHOLDER.match(strip_tags(x["text"]).strip()))


def inline_checks(g, base, old, new, fmt_decl):
    """inline_bilingual 形制：双向 fail-closed 声明复核 + 站长 11-08 批准的四条加码。
    纯函数（FTP-free 可自检）。返回 inline(bool)——True 时调用侧才跳奇偶判。"""
    mi, ri = classify_inline(old)
    mn, rn = classify_inline(new)
    if mi != mn:
        g.ck("inline:旧↔新形制一致", False, got="%s | %s" % (ri, rn),
             expected="两侧同形制", file=base)
    measured = mi and mn
    if fmt_decl == "inline_bilingual":
        g.ck("inline:声明→实测复核", measured, got=None if measured else (rn or ri),
             expected="实测=inline（声明了必须真符）", file=base)
        inline = measured
    else:
        g.ck("inline:未声明而实测inline（即停报，不自动豁免）", not measured,
             got=rn if measured else None, expected="inline 形制须清单显式声明", file=base)
        inline = False
    if not inline:
        return False
    bad_style = [o for o in old["by_ordinal"]
                 if o not in new["by_ordinal"]
                 or new["by_ordinal"][o]["style"] != old["by_ordinal"][o]["style"]]
    g.ck("inline-a:Style列全文件零改动", not bad_style, got=bad_style[:8] or None,
         expected="零改动（全部条，非仅清单条）", file=base)
    bad_en, bad_st = [], []
    for o, dO in old["by_ordinal"].items():
        dN = new["by_ordinal"].get(o)
        if dN is None:
            bad_st.append(o)
            continue
        so, _ = en_segments(dO["text"])
        sn, _ = en_segments(dN["text"])
        if so != sn:
            bad_en.append(o)
        if (dO["marker_labels"] != dN["marker_labels"]
                or dO["n_backslashN"] != dN["n_backslashN"]
                or dO["n_override"] != dN["n_override"]):
            bad_st.append(o)
    g.ck("inline-b:英文段逐字同（我侧两段式解析·逐cue）", not bad_en, got=bad_en[:8] or None,
         expected="零改动", file=base)
    g.ck("inline-c:每行结构不变量(\\N/\\{\\\\r/override标签集合)", not bad_st,
         got=bad_st[:8] or None, expected="零改动", file=base)
    return True


def postcheck_file(g, items, base, ent, trash_root, stagedir, fmt_decl=None,
                   semantics="full_line"):
    d = items[0]["dir"]
    lib = d + "/" + base
    trash = "/".join([trash_root.rstrip("/"), d.lstrip("/"), base])
    os.makedirs(stagedir, exist_ok=True)

    # 取件：库内新件 + _Trash 留底（各自新连接）
    new_b, new_sha = pull(lib)
    try:
        old_b, old_sha = pull(trash)
    except Exception as e:
        g.ck("留底可取(_Trash)", False, got=str(e)[:120], expected=trash, file=base)
        return
    # TOCTOU-2：journal 改前 sha==_Trash 实拉；改后 sha==库内实拉（缺字段即红，fail-closed）
    j = ent.get(base, {})
    g.ck("TOCTOU:journal改前sha==_Trash实拉", j.get("old") == old_sha,
         got="%s|%s" % (j.get("old"), old_sha), expected="两值全等", file=base)
    g.ck("TOCTOU:journal改后sha==库内实拉", j.get("new") == new_sha,
         got="%s|%s" % (j.get("new"), new_sha), expected="两值全等", file=base)

    old, new = parse_ass(old_b), parse_ass(new_b)
    inline = inline_checks(g, base, old, new, fmt_decl)
    # TOCTOU-1：留底逐条 == 清单 cur_zh（整行等值；红＝该件停报站长，执行方重编清单）
    for x in items:
        dO = old["by_ordinal"].get(x["cue"])
        full = (dO["head"] + dO["text"]) if dO else None
        g.ck("TOCTOU:留底==清单cur_zh(n=%d cue=%d)" % (x["n"], x["cue"]),
             full == x["cur_zh"], got=full, expected=x["cur_zh"], file=base)
    # ①序号数旧==新 + cue 偶数自证（inline_bilingual 件豁免奇偶、连续照跑——站长 11-08 裁定）
    g.ck("①序号数旧==新", old["ordinals"] == new["ordinals"],
         got="%d/%d" % (old["ordinals"], new["ordinals"]), expected="相等", file=base)
    if inline:
        g.ck("①奇偶判豁免(inline)", True, got="声明+实测复核通过", expected="附报",
             file=base, level="report")
    else:
        for x in items:
            g.ck("①cue偶数(n=%d)" % x["n"], x["cue"] % 2 == 0, got=x["cue"], expected="偶",
                 file=base)

    # ⑤/FBWL④：字节级还原——留底按清单正向映射重建 ≡ 库内新件
    rebuilt = list(old["lines"])
    for x in items:
        dO = old["by_ordinal"].get(x["cue"])
        exp = expected_new_text(x, dO, semantics)
        if dO and exp is None:
            g.ck("inline:cn_segment语义但旧条无英文段(n=%d)" % x["n"], False,
                 got="旧条无 English override", expected="有英文段", file=base)
            continue
        if dO:
            ln = rebuilt[dO["line_no"] - 1]
            eol = ln[len(ln.rstrip("\r\n")):]
            rebuilt[dO["line_no"] - 1] = dO["head"] + exp + eol
    rb_b = "".join(rebuilt).encode("utf-8")
    g.ck("⑤字节级还原≡库内新件", rb_b == new_b,
         got="len %d/%d sha %s/%s" % (len(rb_b), len(new_b),
                                      hashlib.sha256(rb_b).hexdigest()[:16], new_sha[:16]),
         expected="逐字节等", file=base)
    # ⑤去标签全文件逐字同（独立实现，豁免面恰=清单中文行所在文件行）
    so = [strip_tags(l.rstrip("\r\n")) for l in old["lines"]]
    sn = [strip_tags(l.rstrip("\r\n")) for l in new["lines"]]
    diff_idx = ([i for i, (a, bb) in enumerate(zip(so, sn)) if a != bb]
                if len(so) == len(sn) else None)
    exp_lines = {old["by_ordinal"][x["cue"]]["line_no"] - 1 for x in items
                 if x["cue"] in old["by_ordinal"]}
    g.ck("⑤去标签diff面==清单中文行", diff_idx is not None and set(diff_idx) == exp_lines,
         got=("diff %s" % sorted(diff_idx)[:12]) if diff_idx is not None
         else "行数不等(%d/%d)" % (len(so), len(sn)),
         expected="改动面恰=%d行" % len(exp_lines), file=base)
    # ②全卷占位数不增（非本批半件本就占位，禁新增即绿）
    g.ck("②占位数旧↔新不增", ph_count(old) >= ph_count(new),
         got="%d→%d" % (ph_count(old), ph_count(new)), expected="不增", file=base)
    # 实拉新文逐条 == 期望新文本 + ②③④（实拉面，不信重建）
    for x in items:
        dN = new["by_ordinal"].get(x["cue"])
        exp = expected_new_text(x, old["by_ordinal"].get(x["cue"]), semantics)
        g.ck("实拉新文==期望新文本(n=%d)" % x["n"], dN is not None and exp is not None
             and dN["text"] == exp,
             got=(dN or {}).get("text", "缺"), expected=exp, file=base)
        check_new_text(g, base, (dN or {}).get("text", ""), "实拉n%d" % x["n"])
    # 三件套：size(MLSD==bytes)；sha 全值已在还原/TOCTOU；Dialogue 序号数已核
    ml = listing(d)
    g.ck("三件套:size(MLSD==bytes)", ml.get(base, {}).get("size") == len(new_b),
         got=ml.get(base, {}).get("size"), expected=len(new_b), file=base)
    resid = [n for n in ml if RESIDUE.search(n)]
    g.ck("目录无残留", not resid, got=",".join(resid) or None, expected="0", file=base)


def run(batch, journal_path, trash_root, only=None, rounds=2):
    d = json.load(open(LIST_JSON, encoding="utf-8"))
    items = d["items"]
    by_file = {}
    for x in items:
        by_file.setdefault(x["file"], []).append(x)
    assert len({(x["file"], x["cue"]) for x in items}) == len(items), \
        "清单存在重复 (file,cue)，先查清单再开工"
    files = sorted(set(x["file"] for x in items))
    # 声明面归清单（执行方），复核归闸门：file_formats{base: "inline_bilingual"|{...}} 与/或 item.format
    fmeta = d.get("file_formats") or {}
    sem_global = d.get("new_zh_semantics", "full_line")
    fmt_map, sem_map = {}, {}
    for fn in files:
        vals, sems = set(), set()
        m = fmeta.get(fn) or fmeta.get(os.path.basename(fn))
        if isinstance(m, str):
            vals.add(m); m = {}
        elif isinstance(m, dict):
            if m.get("format"): vals.add(m["format"])
            if m.get("new_zh_semantics"): sems.add(m["new_zh_semantics"])
        for x in by_file[fn]:
            if x.get("format"): vals.add(x["format"])
            if x.get("new_zh_semantics"): sems.add(x["new_zh_semantics"])
        assert len(vals) <= 1, "%s 的 format 声明自相矛盾: %s" % (fn, vals)
        assert len(sems) <= 1, "%s 的 new_zh_semantics 自相矛盾: %s" % (fn, sems)
        fmt_map[fn] = vals.pop() if vals else None
        sem_map[fn] = sems.pop() if sems else sem_global
        assert fmt_map[fn] in (None, "inline_bilingual"), "%s 未知 format: %s" % (fn, fmt_map[fn])
        assert sem_map[fn] in ("full_line", "cn_segment"), "%s 未知语义" % fn
    if only:
        files = [f for f in files if f in set(only)]
    assert files, "--only 与清单无交集，先核对件名"
    ent = journal_index(journal_path)
    top = Gate()
    out, rc = ssh_ro("df -h | grep -E ' /volume1$|/homes' | head -5")
    top.ck("_Trash落盘分区核(df)",
           rc == 0 and out != "" and "md0" not in out.lower() and "volume" in out.lower(),
           got=out[:200] or None, expected="volume卷、非空、无md0")
    if top.reds:
        print("!! _Trash 分区核验红（11-04 教训），停手报站长:", top.reds)
        return 2

    results = []
    for r in range(1, rounds + 1):
        g = Gate()
        for fn in files:
            postcheck_file(g, by_file[fn], fn, ent, trash_root,
                           os.path.join(WS, "tmp", "emb_gate", "r%d" % r),
                           fmt_map.get(fn), sem_map.get(fn, "full_line"))
        results.append(g)
        print("round%d: files=%d checks=%d reds=%d" % (r, len(files), len(g.checks), len(g.reds)))
        tagdir = os.path.join(WS, "logs", "landing_2026-11-08")
        os.makedirs(tagdir, exist_ok=True)
        with open(os.path.join(tagdir, "gate_postcheck_%s_r%d.json" % (batch, r)),
                  "w", encoding="utf-8") as f:
            json.dump({"ts": time.strftime("%F %T"), "batch": batch, "round": r,
                       "by": os.path.basename(__file__), "lex_version": LEX_VERSION,
                       "list_json": LIST_JSON, "files": len(files),
                       "checks": g.checks, "reds": g.reds,
                       "verdict": "PASS" if not g.reds else "MISMATCH-STOP"},
                      f, ensure_ascii=False, indent=1)
        if g.reds:
            print("!! round%d 有 %d 红，fail-closed 停手报站长" % (r, len(g.reds)))
            return 2
    key = lambda gs: json.dumps([[c["name"], c["file"], c["got"], c["expected"], c["ok"]]
                                 for c in gs.checks], ensure_ascii=False, sort_keys=True)
    if rounds > 1 and key(results[0]) != key(results[1]):
        print("!! 两遍读数不一致，停手报站长")
        return 2
    print("ALL GREEN × %d rounds, identical. lex=%s 完卷候站长核。" % (rounds, LEX_VERSION))
    return 0


# ---------- 离线自检：注入故障验断言器本身（零连库） ----------
def selftest():
    HDR = ("[Script Info]\nTitle: t\n\n[V4+ Styles]\nFormat: Name\nStyle: Chinese\n\n"
           "[Events]\nFormat: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, "
           "Effect, Text\n")
    good = HDR + ("Dialogue: 0,0:00:01.00,0:00:02.00,Chinese,,0,0,0,,All right, man.\n"
                  "Dialogue: 0,0:00:01.00,0:00:02.00,Chinese,,0,0,0,,没问题，伙计。\n")
    cases = [("good", good, False),
             # 白名单回归闸：库内真实 tag 形（A.Complete.Unknown 等件实拉所见）必须判绿。
             # 11-08 之前这条会误红——调用侧把尖角括号一起喂给白名单，表体永不命中。
             ("good_tags", good.replace("没问题，伙计。",
                                        '<i><font color="80FFFF">没问题</i></font>，伙计。'), False),
             ("leak", good.replace("没问题，伙计。", "没问题，翻译如下："), True),
             ("placeholder", good.replace("没问题，伙计。", "[中文翻译]"), True),
             ("broken", good.replace("没问题，伙计。", "<i没问题，伙计。</i>"), True),
             ("badtag", good.replace("没问题，伙计。", '<blink>没问题</blink>'), True),
             ("badtag_attr", good.replace("没问题，伙计。", '<font color=red>没问题</font>'), True),
             ("badtag_attr2", good.replace("没问题，伙计。", '<font size="3">没问题</font>'), True),
             ("punct", good.replace("没问题，伙计。", "……！"), True)]
    for name, blob, exp_fail in cases:
        gg = Gate()
        t = parse_ass(blob.encode())["by_ordinal"][2]["text"]
        check_new_text(gg, name, t, "st")
        red = bool(gg.reds)
        print("selftest %s: red=%s expect_red=%s" % (name, red, exp_fail),
              "OK" if red == exp_fail else "!! FAIL")
        if red != exp_fail:
            print("  reds:", gg.reds)
            return 2
    p = parse_ass(good.encode())
    assert p["ordinals"] == 2 and p["by_ordinal"][2]["text"] == "没问题，伙计。"
    assert strip_tags('<i><font color="80FFFF">没问题</i></font>') == "没问题"
    assert broken_tags("<i他没有回来。</i>") == [0]

    # ---- inline_bilingual 形制六例（站长 11-08 特例批裁定：四条加码+双向 fail-closed）----
    def DL(sty, txt):
        return "Dialogue: 0,0:00:01.00,0:00:02.00,%s,,0,0,0,,%s\n" % (sty, txt)
    IL_HDR = ("[Script Info]\nTitle: t\n\n[V4+ Styles]\nFormat: Name\nStyle: Chinese\n\n"
              "[Events]\nFormat: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, "
              "Effect, Text\n")
    il_old = IL_HDR + (DL("Chinese", r"{\r中文}你好，伙计。\N{\rEnglish_1}Hello, man.")
                       + DL("Chinese", r"{\r中文}再见。\N{\rEnglish_2}Goodbye."))
    il_new_ok = IL_HDR + (DL("Chinese", r"{\r中文}你好啊，兄弟。\N{\rEnglish_1}Hello, man.")
                          + DL("Chinese", r"{\r中文}再见。\N{\rEnglish_2}Goodbye."))
    il_cases = [
        ("il_good", il_old, il_new_ok, "inline_bilingual", False),
        ("il_pair_declared", il_old.replace("{\\rEnglish_1}", "EN").replace(
            "\\N{\\rEnglish_2}", "\\NEN"), il_new_ok, "inline_bilingual", True),   # 声明而实测不符→红
        ("il_undeclared", il_old, il_new_ok, None, True),                            # 实测inline未声明→红
        ("il_en_touched", il_old, IL_HDR + (
            DL("Chinese", r"{\r中文}你好啊，兄弟。\N{\rEnglish_1}Hello BRO, man.")
            + DL("Chinese", r"{\r中文}再见。\N{\rEnglish_2}Goodbye.")), "inline_bilingual", True),
        ("il_style_touched", il_old, IL_HDR + (
            DL("Default", r"{\r中文}你好，伙计。\N{\rEnglish_1}Hello, man.")
            + DL("Chinese", r"{\r中文}再见。\N{\rEnglish_2}Goodbye.")), "inline_bilingual", True),
        ("il_override_inject", il_old, IL_HDR + (
            DL("Chinese", r"{\r中文}你好啊，兄弟。{\rFoo}\N{\rEnglish_1}Hello, man.")
            + DL("Chinese", r"{\r中文}再见。\N{\rEnglish_2}Goodbye.")), "inline_bilingual", True)]
    for name, ob, nb, decl, exp_fail in il_cases:
        gg = Gate()
        inline_checks(gg, name, parse_ass(ob.encode()), parse_ass(nb.encode()), decl)
        red = bool(gg.reds)
        print("selftest %s: red=%s expect_red=%s" % (name, red, exp_fail),
              "OK" if red == exp_fail else "!! FAIL")
        if red != exp_fail:
            print("  reds:", gg.reds)
            return 2
    # cn_segment 拼接语义验：new_zh 必须=中文侧完整文本（含 {\r中文} override 与 \N 分隔），
    # 只给净中文会丢结构→inline-c 结构不变量当场判红（确定性契约，修复侧照此填 v4）
    dO = parse_ass(il_old.encode())["by_ordinal"][1]
    assert expected_new_text({"new_zh": r"{\r中文}你好啊，兄弟。\N"}, dO, "cn_segment") \
        == r"{\r中文}你好啊，兄弟。\N{\rEnglish_1}Hello, man."
    assert expected_new_text({"new_zh": r"{\r中文}你好啊，兄弟。"}, dO, "cn_segment") \
        == r"{\r中文}你好啊，兄弟。{\rEnglish_1}Hello, man."   # 丢 \N 的坏例——拼接仍确定性，由 inline-c 拦截
    assert expected_new_text({"new_zh": "整条文本"}, dO, "full_line") == "整条文本"
    print("selftest ALL OK —— 断言器验讫（lex=%s，含 inline 六例+拼接语义）。" % LEX_VERSION)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["GO", "selftest"])
    ap.add_argument("--batch-name")
    ap.add_argument("--journal")
    ap.add_argument("--trash")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--rounds", type=int, default=2)
    a = ap.parse_args()
    if a.mode == "selftest":
        sys.exit(selftest())
    if not (a.batch_name and a.journal and a.trash):
        print("GO 须 --batch-name/--journal/--trash；器具备而不发，候站长 GO。", file=sys.stderr)
        sys.exit(3)
    sys.exit(run(a.batch_name, a.journal, a.trash, a.only, a.rounds))


if __name__ == "__main__":
    main()
