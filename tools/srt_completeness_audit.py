#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中文完整性审计：抓「翻译截断」「审校加译/串行」「残留英文」「孤儿符号」四类。

执行者：DS90站长（审核线专用工具）
授权出处：站长自建工具（只读审计，不改文件、不上传）

背景（2026-10-21 Dark Matter S02E08 实测）：
  - cue 数 / 时间轴 / 展平 / srt_check 全都查不出「中文被截成开头片段」（E07 教训）
  - 必须逐条比对「英文句数 vs 中文句数」「中文断尾 vs 英文整句」才能标出

用法：
  python3 tools/srt_completeness_audit.py <zh.srt> <en.srt> [--json out.json]
  python3 tools/srt_completeness_audit.py --dir tmp/xxx/            # 同目录下 *ai.srt / *en.srt 配对
  python3 tools/srt_completeness_audit.py <zh> <en> --r1-mode legacy  # 旧口径（仅供新旧对比）

  R1 口径（2026-10-22 站长裁定）：R1 的中文句数与长度比在**去标签后**的中文上计算
  （用 tools/strip_tags_assert.py 的独立字符扫描器）—— 斜体批次不会再让 R1 warning 假性出现/消失。

判定规则（2026-10-21 21:30 站长裁定后修订；宁严勿宽，只报有硬证据的）：
  R1 截断      : 英文句子数 > 中文句数（中文少了整句）—— **降为 warn**
                  （中文并列合并两句 / 省略重复是字幕常态，不作 error）
  R2 断尾      : 中文以「，、；：」或省略号结尾，而英文以 . ! ? **整句**收尾
                  （英文以「...」收尾 ⇒ 不算整句收尾，不判尾）
  R3 串行      : 中文里出现了下一条英文的实义词（审校把下一句的译文挪上来）—— warn
  R4 残留英文  : 中文行里出现拉丁单词；>=2 词 warn，**>=4 词（大段）error**；
                  专名保留英文在白名单内不算残留。
                  白名单（站长 2026-11-21 令）：由硬编码改**可配置 + 按片登记**——
                  `--r4-whitelist <json>`，格式 {"global": [...], "works": {"<片名>": [...]}}；
                  内置默认仍含旧硬编码词（不带参数零回归）。
                  **♪ 音乐/歌曲行归 warn**（行内歌曲名/歌手名按令保留原文，
                  必撞「单行拉丁≥4」，不判 error；detail 标 music_line）。
  R5 孤儿符号  : 中文行出现落单的闭合符—— error
  R6 无中文    : 该 cue 完全没有中文行—— error；但两类**豁免归 warn**
                  （站长 2026-11-21 令，对齐 11-18 Rolling Loud 34 枚纯艺名行先例 /
                  MobLand S02E10 案）：
                    · 呼号/艺名行：剥标签与对话破折号后仅 1~2 个拉丁词（如 `Harry.` /
                      `<i>Kat.</i>` / `Kev?` / `- Harry. - Conrad.`）——硬造中文即加译；
                    · 片尾 credit / 音乐署名行：en 行含 ♪（如 `♪ "Starburster" by … ♪`）。
                  豁免只降 level、finding 留痕（detail 注明 exempt 理由）；
                  **零拉丁词的纯符号/数字行不豁免**（可能是真漏翻，仍 error）。

  **error 只保留机械级**：R2 真断尾 / R4 大段残留英文（非 ♪ 行）/ R5 孤儿符号 / R6 无中文行（非豁免两类）。
  新关卡口径：入库前 error 级 = 0（机械级）＋ R1 warn 逐条有结论（修 or 豁免并写明理由）。

句数统计口径（2026-10-21 21:30 站长裁定）：
  1. 省略号「…」「...」算**一个**边界，且**不制造句界**（不把一句拆成两句）
  2. 计数前先剥尾部引号/括号（" ' ” ’ ) ] 】 》 」 』）
  3. R2 判断前，英文若以省略号收尾则不视为「整句收尾」
"""
import sys, os, re, json, glob

# R1 去标签口径（2026-10-22 站长裁定）：斜体批次会让 R1 的**长度比**把标签字符算进去
#   ⇒ warning 假性出现/消失（实测：加 <i></i> 后 len(zh) 变长 → 长度比门槛不再触发 → R1 假性消失）。
# 修法：R1 的中文句数与长度比都在**去标签后**的中文上算，用可复用工具里的独立字符扫描器。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from strip_tags_assert import strip_tags as _strip_tags
except Exception:          # 工具不可用时退回本地等价实现（不静默改变口径）
    _strip_tags = None

R1_MODE = 'stripped'      # 'stripped'（默认，去标签后算）| 'legacy'（旧口径，仅供新旧对比）


def _zh_for_r1(zt, mode=None):
    """R1 用的中文文本：stripped 模式下先剥掉 <i…> 标签。mode 优先于全局 R1_MODE。"""
    if (mode or R1_MODE) == 'legacy':
        return zt
    if _strip_tags is not None:
        return _strip_tags(zt)
    return re.sub(r'</?i(?:/\s*|\s[^>]*)?>', '', zt)

CJK = re.compile(r'[\u4e00-\u9fff]')
LATIN_WORD = re.compile(r'[A-Za-z]{2,}')
SENT_SPLIT = re.compile(r'[.!?]+')
ELLIPSIS = re.compile(r'(?:\.{2,}|…+)')
TRAILING_QUOTES = re.compile(r'["\'”’）)\]】》」』]+\s*$')
TRAILING_DANGLING = re.compile(r'(?:[，、；：]|…|\.\.\.)\s*$')
ORPHAN_CLOSE = re.compile(r'[】》」』]')
ASS_TAG = re.compile(r'\{\\[^}]*\}')          # ASS 覆写标签 {\an8} {\pos(..)} 等
CJK_CLOSE = re.compile(r'[】》」』]')
# R4 白名单（站长 2026-11-21 令：硬编码改可配置 + 按片登记）：
#   内置 global 保持旧硬编码词 ⇒ 不带 --r4-whitelist 时行为与旧版逐位一致（零回归）；
#   按片词条走 --r4-whitelist <json>：{"global": [...], "works": {"<片名子串>": [...]}}。
R4_WHITELIST_WORDS = {
    'global': ['CERN', 'Velocity', 'Polaris', 'The Home'],
    'works': {},
}
R4_WHITELIST = re.compile(r'CERN|Velocity|Polaris|The\s+Home', re.I)   # 兼容旧引用名


def load_r4_whitelist(path):
    """读 --r4-whitelist json（{"global": [...], "works": {"片名": [...]}}）。"""
    data = json.load(open(path, encoding='utf-8'))
    R4_WHITELIST_WORDS['global'] = list(data.get('global') or R4_WHITELIST_WORDS['global'])
    R4_WHITELIST_WORDS['works'] = {k: list(v) for k, v in (data.get('works') or {}).items()}


def r4_words_for_file(path):
    """按片匹配：works 里键（片名子串，忽略大小写）命中文件名者，取**最长命中键**的词条。"""
    name = os.path.basename(path).lower()
    best, best_words = -1, []
    for key, words in R4_WHITELIST_WORDS['works'].items():
        if key.lower() in name and len(key) > best:
            best, best_words = len(key), words
    return best_words


def r4_probe_re(extra_words=()):
    """合并 global + 本片词条 编译剥离正则；词长按降序，防短词先吞长词。"""
    words = list(R4_WHITELIST_WORDS['global']) + list(extra_words)
    words = sorted({w for w in words if w.strip()}, key=len, reverse=True)
    if not words:
        return re.compile(r'(?!x)x')          # 空白名单：永不匹配
    pats = [re.escape(w).replace(r'\ ', r'\s+') for w in words]
    return re.compile('|'.join(pats), re.I)


def r6_exempt_reason(en_text):
    """R6 豁免判定（站长 2026-11-21 令）：返回豁免理由串，不豁免返 None。
    判据宁严勿宽——只认两类：♪ 署名行 / 剥尽标签与对话记号后 1~2 个拉丁词的呼号行。"""
    if '\u266a' in en_text:                                    # ♪ 片尾 credit / 音乐署名行
        return 'credit/music line (exempt per 2026-11-21)'
    probe = re.sub(r'<[^>]*>|\{\\[^}]*\}', ' ', en_text)       # 剥 HTML/ASS 标签
    probe = re.sub(r'^\s*[-—–]\s*', ' ', probe)                # 对话破折号（行首）
    words = LATIN_WORD.findall(probe)
    if not words:
        return None                                             # 零拉丁词＝纯符号/数字，可能是真漏翻
    if len(words) <= 2 and len(re.sub(r'\s+', '', probe)) <= 40:
        return 'name/call line (exempt per 2026-11-21)'         # 呼号/艺名行
    return None


def parse_srt(path):
    t = open(path, encoding='utf-8', errors='replace').read()
    t = t.replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.findall(
        r'(\d+)\n(\d\d:\d\d:\d\d,\d+ --> \d\d:\d\d:\d\d,\d+)\n(.*?)(?=\n\n|\Z)', t, re.S)
    out = {}
    for num, ts, body in blocks:
        lines = [ASS_TAG.sub('', l).strip() for l in body.split('\n') if l.strip()]
        cn = [l for l in lines if CJK.search(l)]
        en = [l for l in lines if not CJK.search(l)]
        out[int(num)] = {'ts': ts, 'cn': cn, 'en': en,
                         'cn_text': ' '.join(cn), 'en_text': ' '.join(en)}
    return out


def en_sentences(s):
    """英文句数：先剥尾部引号/括号；省略号不当句界（不把一句拆成两句）。"""
    s = TRAILING_QUOTES.sub('', s.strip())
    if not s:
        return 0
    s = ELLIPSIS.sub('\x00', s)
    parts = [p for p in SENT_SPLIT.split(s) if p.strip()]
    return max(1, len(parts))


def zh_sentences(s):
    """中文句数：先剥尾部引号/括号；省略号不当句界。"""
    s = TRAILING_QUOTES.sub('', s.strip())
    if not s:
        return 0
    s = ELLIPSIS.sub('\x00', s)
    parts = [p for p in re.split(r'[。！？]', s) if p.strip()]
    return max(1, len(parts))


def en_ends_complete(s):
    """英文是否「整句收尾」：以 . ! ? 结尾且**不是**以省略号收尾。"""
    s = TRAILING_QUOTES.sub('', s.strip())
    if not s:
        return False
    if re.search(r'(?:\.{2,}|…+)\s*$', s):
        return False          # 英文以省略号收尾 ⇒ 不算整句收尾（站长 2026-10-21 21:30）
    return bool(re.search(r'[.!?]$', s))


def stopword_en(s):
    return set(w.lower() for w in LATIN_WORD.findall(s) if len(w) > 3)


def audit(zh_path, en_path, r1_mode=None, r4_extra_words=None):
    """r1_mode='stripped'（默认）/ 'legacy'（仅供新旧对比）。
    **必须用参数传、不靠全局** —— 全局变量在多线程下会串台（2026-10-22 全库重跑踩过）。
    r4_extra_words=None 时按 zh 文件名自动匹配按片白名单（works）；显式传 list 则覆盖。"""
    zh = parse_srt(zh_path)
    en = parse_srt(en_path)
    if r4_extra_words is None:
        r4_extra_words = r4_words_for_file(zh_path)
    r4_re = r4_probe_re(r4_extra_words)
    findings = []
    keys = sorted(set(zh) | set(en))
    for k in keys:
        z = zh.get(k)
        e = en.get(k)
        if not z:
            findings.append({'cue': k, 'rule': 'R0', 'level': 'error',
                             'detail': '中文文件缺该 cue',
                             'en': e['en_text'][:200] if e else ''})
            continue
        zt, et = z['cn_text'], (e['en_text'] if e else '')
        if not zt:
            exempt = r6_exempt_reason(et)                      # 呼号/艺名行、♪ 署名行豁免（2026-11-21 令）
            findings.append({'cue': k, 'rule': 'R6',
                             'level': 'warn' if exempt else 'error',
                             'detail': '无中文行%s' % ('（%s）' % exempt if exempt else ''),
                             'exempt': exempt or '', 'en': et[:200]})
            continue
        if not et:
            continue
        zr = _zh_for_r1(zt, r1_mode)
        er = _zh_for_r1(et, r1_mode)   # 英文侧同样去标签（2026-10-22 同一口径延伸：</i> 会被
                                       # SENT_SPLIT 当成第 2 句 → 英文句数虚高 1 → R1 假性告警）
        if en_sentences(er) > zh_sentences(zr) and len(zr) * 100 < len(er) * 35:
            findings.append({'cue': k, 'rule': 'R1', 'level': 'warn',
                             'detail': '英文 %d 句 / 中文 %d 句，中文少了整句（并列合并/省略重复属常态，需逐条结论）' % (
                                 en_sentences(er), zh_sentences(zr)),
                             'en': et[:300], 'zh': zt[:200],
                             'zh_r1_text': zr[:200]})
        if TRAILING_DANGLING.search(zt) and en_ends_complete(er):
            findings.append({'cue': k, 'rule': 'R2', 'level': 'error',
                             'detail': '中文断尾，英文整句收尾（疑似截断）',
                             'en': et[:300], 'zh': zt[:200]})
            continue
        nxt = en.get(k + 1)
        if nxt:
            ns = stopword_en(nxt['en_text'])
            zs = stopword_en(et)
            cand = [w for w in ns - zs if len(w) >= 5]
            if cand:
                hits = [w for w in cand if re.search(r'\b%s\b' % re.escape(w), zt, re.I)]
                if hits:
                    findings.append({'cue': k, 'rule': 'R3', 'level': 'warn',
                                     'detail': '中文疑似含下一条内容（词 %s）' % ','.join(hits[:3]),
                                     'en': et[:300], 'zh': zt[:200],
                                     'next_en': nxt['en_text'][:200]})
                    continue
        for ln in z['cn']:
            probe = re.sub(r'<[^>]*>|\{\\[^}]*\}', ' ', ln)   # 去掉 HTML/ASS 标签（样式属性不是残留英文）
            probe = r4_re.sub(' ', probe)                      # 白名单剥离（global + 按片，2026-11-21 可配置化）
            words = LATIN_WORD.findall(probe)
            music = '\u266a' in ln                             # ♪ 音乐/歌曲行：歌名/歌手名按令保留原文
            if len(words) >= 4:
                findings.append({'cue': k, 'rule': 'R4',
                                 'level': 'warn' if music else 'error',
                                 'detail': '中文行大段残留英文%s：%s' % (
                                     '（music_line）' if music else '', ' '.join(words)),
                                 'en': et[:200], 'zh': ln[:200]})
                break
            if len(words) >= 2:
                findings.append({'cue': k, 'rule': 'R4', 'level': 'warn',
                                 'detail': '中文行残留英文：%s' % ' '.join(words),
                                 'en': et[:200], 'zh': ln[:200]})
                break
        for ln in z['cn']:
            if ORPHAN_CLOSE.search(ln) and not re.search(r'[【《「『]', ln):
                findings.append({'cue': k, 'rule': 'R5', 'level': 'error',
                                 'detail': '中文行落单闭合符', 'en': et[:200], 'zh': ln[:200]})
                break
    return findings


def main():
    args = sys.argv[1:]
    out_json = None
    if '--r1-mode' in args:
        i = args.index('--r1-mode')
        globals()['R1_MODE'] = args[i + 1]
        args = args[:i] + args[i + 2:]
    if '--r4-whitelist' in args:
        i = args.index('--r4-whitelist')
        load_r4_whitelist(args[i + 1])
        args = args[:i] + args[i + 2:]
    if '--json' in args:
        i = args.index('--json')
        out_json = args[i + 1]
        args = args[:i] + args[i + 2:]
    if not args:
        print(__doc__)
        sys.exit(1)
    pairs = []
    if args[0] == '--dir':
        d = args[1]
        for zhf in sorted(glob.glob(os.path.join(d, '*ai.srt'))):
            base = os.path.basename(zhf)[:-len('ai.srt')]
            enf = os.path.join(d, base + 'en.srt')
            if os.path.exists(enf):
                pairs.append((zhf, enf))
    else:
        pairs.append((args[0], args[1]))
    total = 0
    report = []
    for zhf, enf in pairs:
        f = audit(zhf, enf)
        errs = [x for x in f if x['level'] == 'error']
        warns = [x for x in f if x['level'] == 'warn']
        total += len(errs)
        print('=== %s' % os.path.basename(zhf))
        print('    error=%d  warn=%d' % (len(errs), len(warns)))
        for x in f:
            print('  [%-2s %-3s] cue %-4d %s' % (x['rule'], x['level'], x['cue'], x['detail']))
            if x['level'] == 'error':
                print('        EN: %s' % x.get('en', '')[:160])
                print('        ZH: %s' % x.get('zh', '')[:160])
        report.append({'zh': zhf, 'en': enf, 'error': len(errs), 'warn': len(warns),
                       'findings': f})
    print('\n合计 error=%d' % total)
    if out_json:
        json.dump(report, open(out_json, 'w'), ensure_ascii=False, indent=1)
        print('written', out_json)


if __name__ == '__main__':
    main()
