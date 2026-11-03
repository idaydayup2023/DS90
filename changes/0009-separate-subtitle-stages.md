### Added

- `subtrans subtitles` 增加 `--stage translate|review|both`。默认 `both` 仍是翻译后审校并发布。`translate` 只把进度写入检查点，不调用审校模型，也不发布。`review` 只根据检查点审校并发布；没有匹配的翻译检查点时失败，不会改去翻译。
- 翻译和审校在每个完成的批次后把检查点写入状态库表 `subtitle_checkpoints`。中断后续跑跳过已完成的 cue。检查点不进媒体目录，也不保存 API 密钥。`--force` 丢弃检查点。

### Changed

- 状态库 schema 升到 1。打开旧库时保留原有 job，并补上 `subtitle_checkpoints`。
