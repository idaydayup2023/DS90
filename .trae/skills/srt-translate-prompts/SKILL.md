---
name: "srt-translate-prompts"
description: "维护 srt_translate 的提示词模板（TranslateGemma/场景切分/实体统一/一致性校验）。需要改翻译效果或提示词时调用。"
---

# srt_translate Prompts

## TranslateGemma 官方格式（单段翻译）

要求：单条 user message，且 `{TEXT}` 前必须有两个空行；输出只能是目标语言译文。

```
You are a professional {SOURCE_LANG} ({SOURCE_CODE}) to {TARGET_LANG} ({TARGET_CODE}) translator. Your goal is to accurately convey the meaning and nuances of the original {SOURCE_LANG} text while adhering to {TARGET_LANG} grammar, vocabulary, and cultural sensitivities.
Produce only the {TARGET_LANG} translation, without any additional explanations or commentary. Please translate the following {SOURCE_LANG} text into {TARGET_LANG}:


{TEXT}
```

## 逐条对齐的提示词策略

TranslateGemma 倾向“只输出译文”，对结构化输出（JSON/带索引）不一定稳定。为了确保 1:1 对齐，建议优先采用：

- 逐条翻译：每条字幕单独调用（最稳，但慢）
- 小批量翻译 + 外部切分：把多条字幕合并成一个文本输入，用明确的分隔符；然后对返回结果按分隔符解析与校验，失败回退到逐条

建议分隔符（输入侧）：

- 使用不可见歧义小的分隔线，例如：
  - `\n<<<SRT_LINE:{index}>>>\n{english}\n`

校验规则（输出侧）：

- 必须产生与输入相同数量的片段
- 每个片段必须能解析出对应 `index`
- 任一条缺失/合并/顺序错乱则判失败，缩小 batch 或逐条重试

## 场景切分（用于摘要判断，不参与最终字幕输出）

目标：为每个场景提供“术语域/语境提示”，降低跨场景术语误译。

输入：一段连续英文字幕（带时间范围）。输出：场景标签与术语域（医院/反恐/科幻/日常等）。

## 实体抽取与统一

目标：抽取人名/地名/组织/专有名词/缩写并给出统一译名建议，供一致性后处理使用。

约束：

- 同一英文实体在同一文件内必须唯一映射
- 输出不要夹带英文解释段落，尽量用可机器解析的结构（如 key-value 列表）

## 一致性校验（后处理）

检查项：

- 实体译名是否前后一致
- 缩写是否被翻成多个中文含义
- 中文行是否包含遗留英文（不应出现整句英文）

