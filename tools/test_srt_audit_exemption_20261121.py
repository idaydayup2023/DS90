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
    # ---- 2026-11-23 五型扩展（站长 11:4x 单；豁免族＋真缺陷族双对撞） ----
    (None,            '<i>- N - N!</i>',                           'R6', 'warn',  '型1拼字比赛(WAR实弹cue134)'),
    (None,            '<i>N</i>',                                  'R6', 'warn',  '型1单字母(WAR实弹cue144)'),
    (None,            'M-A-N!',                                    'R6', 'warn',  '型1连字符拼读'),
    (None,            'Six-six-six-two-seven-one.',                'R6', 'warn',  '型2口播号码'),
    (None,            '666271',                                    'R6', 'warn',  '型2纯数字'),
    (None,            'Patrick Doyle, Bobby Cranes,',              'R6', 'warn',  '型3点名列举(MobLand cue166族)'),
    (None,            '- Kevin-ator. <i>- Paul.</i>',              'R6', 'warn',  '型4连字符戏称(E07 c761族)'),
    (None,            'patrick doyle, bobby cranes,',              'R6', 'error', '型3反例-全小写不豁免'),
    (None,            'twenty seven runners sprint now',           'R6', 'error', '型2反例-数词混普通词不豁免'),
    ('Kev、Dog，Dog，这就是 Kev，对吧？', 'x',                       'R4', 'warn',  '型5绰号重复-去重后不升error'),
    ('这里 Alpha Beta Gamma Delta Epsilon 添加了大段英文', 'pure zh line', 'R4', 'error', '型5反例-去重仍≥4-仍error'),
    ('\u53bb CERN Velocity Polaris The Home \u770b\u5c55', 'Go see it.',        'R4', None,  'global白名单-不报'),
    ('\u266a Johnny Cash \u7684 "God\u2019s Gonna Cut You Down" \u6b63\u5728\u64ad\u653e \u266a',
     '\u266a "God\u2019s Gonna Cut You Down" by Johnny Cash \u266a', 'R4', 'warn', 'music_line归warn'),
    ('\u8fd9\u91cc Alpha Beta Gamma Delta Epsilon \u6dfb\u4e86\u5927\u6bb5\u82f1\u6587', 'pure zh line', 'R4', 'error', '非music大段残留-仍error'),
    ('\u4e13\u5458\u53d1\u73b0 Starburster Fontaines \u540d\u5355', 'x',      'R4', None,  '按片白名单-不报'),
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
