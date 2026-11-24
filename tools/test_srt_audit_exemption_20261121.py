#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""srt_completeness_audit R6/R4 豁免单测（站长 2026-11-21 ① 令，闸改自证双样张）。

双对撞：豁免族（该降 warn 的）＋ 不破闸族（该仍 error 的）一起跑——
豁免生效与闸门灵敏度同批证明，防「豁免开太宽把真缺陷也放过」。

跑法：python3 tools/test_srt_audit_exemption_20261121.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import srt_completeness_audit as A

CUES = [
    # (zh_line_or_None, en_line, expect_rule, expect_level, tag)
    (None,            'Harry.',                                    'R6', 'warn',  '呼号单名'),
    (None,            '<i>Kat.</i>',                               'R6', 'warn',  '呼号带斜体'),
    (None,            'Kev?',                                      'R6', 'warn',  '呼号问号'),
    (None,            '- Harry. - <i>Conrad.</i>',                 'R6', 'warn',  '双呼号行'),
    (None,            '\u266a "Starburster " by Grian Chatten \u266a', 'R6', 'warn', '片尾credit署名'),
    (None,            '??? ... !!!',                               'R6', 'error', '零拉丁词纯符号-不豁免'),
    (None,            'I want Conrad and Maeve dead now',          'R6', 'error', '整句纯英文-不豁免'),
    ('\u53bb CERN Velocity Polaris The Home \u770b\u5c55', 'Go see it.',        'R4', None,  'global白名单-不报'),
    ('\u266a Johnny Cash \u7684 "God\u2019s Gonna Cut You Down" \u6b63\u5728\u64ad\u653e \u266a',
     '\u266a "God\u2019s Gonna Cut You Down" by Johnny Cash \u266a', 'R4', 'warn', 'music_line归warn'),
    ('\u8fd9\u91cc Alpha Beta Gamma Delta Epsilon \u6dfb\u4e86\u5927\u6bb5\u82f1\u6587', 'pure zh line', 'R4', 'error', '非music大段残留-仍error'),
    ('\u4e13\u5458\u53d1\u73b0 Starburster Fontaines \u540d\u5355', 'x',      'R4', None,  '按片白名单-不报'),
    # —— 型6 头衔缩写语境豁免（站长 2026-11-23 单·WAR 2026 S01E04 cue205 案）——
    ('Nicholas \u4e0d\u6562\u76f4\u89c6 St. John\uff0c\u56e0\u4e3a Singer \u90a3\u6863\u5b50\u4e8b\u3002', "Nicholas can't look St. John in the face\\nbecause of the Singer situation.", 'R4', 'warn', 'E04\u5b9e\u6848-St.\u5934\u8854+\u4e13\u540d-\u964dwarn\u4e0derror'),
    ('\u7267\u5e08\u8bf4 St. John \u548c Nicholas Singer \u90fd\u5728\u573a', 'x', 'R4', 'warn', 'St.\u5265\u540e3\u8bcd-\u4e0d\u5347error'),
    ('\u8b66\u957f\u53bb\u627e St John \u4e0e Nicholas Singer', 'x', 'R4', 'warn', '\u65e0\u70b9St\u5934\u8854\u540c\u6837\u8c41\u514d'),
    ('\u4ed6\u628a St \u548c John \u4e0e Nicholas Singer \u90fd\u5199\u4e86', 'x', 'R4', 'error', '\u8d1f\u4f8b-\u5149\u6746St\u4ecd\u8ba1-\u4ecderror'),
    ('John Nicholas Singer \u843d\u6b3e St.', 'x', 'R4', 'error', '\u8d1f\u4f8b-\u884c\u5c3eSt.\u65e0\u540e\u7eed\u4e13\u540d-\u4ecderror'),
    ('\u6587\u4ef6\u540d\u53eb St mary \u4e0e John Nicholas Singer', 'x', 'R4', 'error', '\u8d1f\u4f8b-St\u540e\u5c0f\u5199-\u4e0d\u8c41\u514d\u4ecderror'),
]


def srt_body(i, zh, en):
    lines = []
    if zh:
        lines.append(zh)
    if en:
        lines.append(en)
    return '%d\n%02d:%02d:%02d,000 --> %02d:%02d:%02d,500\n%s\n' % (
        i, i // 60, i // 60, i % 60, i // 60, i // 60, i % 60 + 1, '\n'.join(lines))


def main():
    d = tempfile.mkdtemp(prefix='audit_exempt_')
    zh_p = os.path.join(d, 'Movie.Show.S01E01.ai.srt')     # 文件名含 works 键 MobLand 需另测，这里先配 MobLand
    zh_p = os.path.join(d, 'MobLand.S02E10.The.Queen.ai.srt')
    en_p = os.path.join(d, 'MobLand.S02E10.The.Queen.en.srt')
    open(zh_p, 'w', encoding='utf-8').write('\n'.join(
        srt_body(i + 1, z, e) for i, (z, e, *_ ) in enumerate(CUES)))
    open(en_p, 'w', encoding='utf-8').write('\n'.join(
        srt_body(i + 1, None, e) for i, (z, e, *_ ) in enumerate(CUES)))

    # 装按片白名单（等效 --r4-whitelist；works 键 MobLand.S02E10）
    wl = os.path.join(d, 'wl.json')
    json.dump({'global': ['CERN', 'Velocity', 'Polaris', 'The Home'],
               'works': {'MobLand.S02E10': ['Starburster', 'Fontaines']}},
              open(wl, 'w', encoding='utf-8'), ensure_ascii=False)
    A.load_r4_whitelist(wl)

    findings = A.audit(zh_p, en_p)
    by_cue = {}
    for f in findings:
        by_cue.setdefault(f['cue'], []).append(f)

    fails = []
    for i, (z, e, rule, level, tag) in enumerate(CUES):
        cue = i + 1
        hits = [f for f in by_cue.get(cue, []) if f['rule'] == rule]
        if level is None:
            ok = not hits
            got = 'none' if ok else hits[0]['level']
        elif hits:
            ok = hits[0]['level'] == level
            got = hits[0]['level']
        else:
            ok, got = False, 'missing'
        mark = 'PASS' if ok else 'FAIL'
        print('[%s] cue%-3d %-5s expect=%-6s got=%-7s %s | en=%r' % (
            mark, cue, rule, level or 'none', got, tag, e[:46]))
        if not ok:
            fails.append(tag)

    # 零回归：不带 --r4-whitelist 时内置词表仍在（global 默认含 CERN）
    A.R4_WHITELIST_WORDS['global'] = ['CERN', 'Velocity', 'Polaris', 'The Home']
    A.R4_WHITELIST_WORDS['works'] = {}
    r = A.r4_probe_re(A.r4_words_for_file(zh_p))
    ok = r.sub(' ', 'CERN Velocity Polaris The Home') .strip() == ''
    print('[%s] 零回归：内置 global 词表剥尽' % ('PASS' if ok else 'FAIL'))
    if not ok:
        fails.append('zero-regression')

    print('\n== %s (%d fails)' % ('ALL PASS' if not fails else 'FAILS: %s' % fails, len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
