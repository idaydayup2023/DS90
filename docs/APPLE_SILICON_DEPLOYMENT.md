# Apple Silicon 生产部署

## 已选拓扑

`subtrans`、ffmpeg/ffprobe、Ollama 和可选 ASR/OCR worker 统一运行在 Apple Silicon。群晖只提供媒体存储，优先通过 SMB/NFS 挂载到 `/Volumes`。字幕就绪状态、分类、计划和迁移不得拆到两个执行端。

原因是迁移明确依赖字幕的 `ready` manifest；一体化运行不需要跨机队列、分布式锁、远程凭据或两端状态修复。FTP 仅为旧环境兼容，明文模式必须显式开启并限定在可信网络。

## 固定目录

建议使用以下布局，并由专用普通用户运行：

```text
/usr/local/subtrans/bin/subtrans       主程序
/usr/local/subtrans/etc/subtrans.toml  严格配置（不含密钥）
/usr/local/subtrans/state/             SQLite 状态（必须是 Apple 本机磁盘）
/usr/local/subtrans/logs/              调度日志
/Volumes/Media/...                     群晖 SMB/NFS 挂载
```

不要把状态库放在 NAS 网络共享。配置中的 `source.root` 与 `destination.root` 应是两个已经挂载且由运行用户可读写的绝对目录。程序不会创建缺失的存储根，因此 NAS 未挂载时会安全失败，不会误写本机同名目录。

## 安装和离线更新

1. 在相同 macOS/arm64 目标上执行 `cargo build --locked --release`。
2. 用 `shasum -a 256 target/release/subtrans` 记录校验和。
3. 停止调度，备份本机状态库及其 `-wal`/`-shm` 文件。
4. 将新文件放到临时名称，核对校验和和 `subtrans --version` 后原子替换旧主程序。
5. 运行 `subtrans doctor --config /usr/local/subtrans/etc/subtrans.toml`，再执行字幕 dry-run 和迁移 plan；确认后恢复调度。

回退时恢复旧主程序。若新版本已写入状态库，不应直接恢复旧数据库；先保留完整副本，并按版本变更说明判断兼容性。

离线环境需预先固定并传输：`subtrans`、ffmpeg/ffprobe、Ollama 程序与模型、可选 worker 与模型。主程序运行时不会下载或安装任何依赖。

## 调度与人工批准

`deploy/com.subtrans.subtitles.plist.example` 是仅处理字幕的 launchd 模板。复制前替换所有 `/usr/local/subtrans` 路径；调度用户必须已经能访问 NAS 挂载。日志文件轮转由系统或运维配置负责。

目录迁移不放入无条件定时任务。正确流程始终是：

```sh
subtrans migrate plan --config /usr/local/subtrans/etc/subtrans.toml --output migration.plan.json
subtrans migrate review --config /usr/local/subtrans/etc/subtrans.toml --plan migration.plan.json
subtrans migrate apply --config /usr/local/subtrans/etc/subtrans.toml --plan migration.plan.json --approve '<plan_hash>'
```

每次修改覆盖、存储路径、阈值或命名规则后都必须重新生成计划并重新批准哈希。

## 群晖原生执行门槛

目前不部署 DSM 执行端。只有同时满足以下条件才重新评估：

- 已确认具体群晖 CPU、DSM 版本与 glibc，并在实机验证专用构建；
- NAS 能可靠访问同一状态/任务协议，断网、重启、并发和锁冲突测试全部通过；
- 证明拆分带来显著可用性或性能收益；
- 字幕 `ready` 与迁移提交仍只有一个权威写入者。

macOS arm64 可执行文件绝不能直接复制到 DSM 运行。
