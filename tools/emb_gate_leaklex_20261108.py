#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""emb 闸门词表与判据（唯一真源·落仓固化）。

站长 11-08 批复第 1 条③：独立泄漏词表由闸门侧（代码运维）自建、**落仓固化，
今后全站后验以此为准，中途不得换表**。换表＝向 version3 再提 PR 升版本号；
跑批中途换表属违规，后验读数作废重跑。

版本沿革：
  emb-gate-lex-2026-11-08.1  首版（emb 元话语修复写库 v2 首批起用）：
    强泄漏＝fail-closed 判据；弱泄漏＝附报候审；占位符/纯标点/tag 白名单/
    BROKEN 两段式（11-07 站长立、10-22 教训同源）。

被闸的人不许改闸：本文件只准代码运维提仓内 PR 修改（闸门治理，11-07）。
"""

LEX_VERSION = "emb-gate-lex-2026-11-08.1"

import re

# ③ 强元话语/思考流：命中即 FAIL（限本批新写中文行；语义均为「模型自述」而非台词）
LEAK_STRONG = re.compile(
    r"翻译如下|翻译结果|译文如下|以下是翻译|下面是翻译|以下是对话|下面是台词"
    r"|需要.{0,12}(?:英文)?字幕|字幕文本|才能进行翻译|无法完成翻译|无法翻译"
    r"|作为AI|作为人工智能|抱歉[，,]?\s*我|请提供.{0,8}字幕|继续翻译"
    r"|让我来翻译|正在为您?翻译|以下是.{0,6}(?:原文|内容)")

# ③ 弱泄漏：只附报候审不判红（日常台词高频，单条命中多为巧合，人工过目）
LEAK_WEAK = re.compile(
    r"^(?:好的|没问题|当然)[，,]?\s*(?:我|将|让我)|首先[，,]|接下来我|然后我"
    r"|我将|我会(?:为|帮|把)|直译|意译|参考译文|未找到|没有找到|稍等|抱歉"
    r"|需要您|请你?提供|抱歉，我无法")

# ② 占位符残留（本批新写行命中即 FAIL；全卷计数只断不增——非本批半件本就占位）
PLACEHOLDER = re.compile(r"^\s*\[?\s*(?:中文翻译|英文翻译)\s*\]?\s*$")

# ② 汉字/字母检测（新中文行须含其一，否则视同纯标点/空）
HAN = re.compile(r"[\u4e00-\u9fff]")
LATIN = re.compile(r"[A-Za-z]")

# ④ tag 词表：WELL＝规范 <...>；OVERRIDE＝ASS {\...} 块；
#    白名单＝斜体/粗/下划线/颜色（font color 六位 16 进制，可带 #）
TAG_WELL = re.compile(r"<[^<>]*>")
OVERRIDE = re.compile(r"\{[^{}]*\}")
TAG_WHITELIST = re.compile(r"^(?:/?[ibuf]|font color=\"#?[0-9A-Fa-f]{6}\"?|/font)$")

# 目录残留（STOR 半道件）
RESIDUE = re.compile(r"(\.tmp-|\.orig|\.new|\.uploading|\.aria2)", re.I)

# journal 弹性字段名（执行方 journal 记法不一，取到即用；取不到＝红，fail-closed）
JOURNAL_KEYS_OLD = ("old_sha256", "before_sha256", "pre_sha256", "old_sha",
                    "sha_before", "sha256_before")
JOURNAL_KEYS_NEW = ("new_sha256", "after_sha256", "post_sha256", "new_sha",
                    "sha_after", "sha256_after", "output_sha256")
JOURNAL_KEYS_FILE = ("file", "fname", "name", "basename")


if __name__ == "__main__":
    print(LEX_VERSION)
