# Apple Silicon 生产部署

## 已选拓扑

`subtrans`、ffmpeg/ffprobe、Ollama 和可选 ASR/OCR worker 统一运行在 Apple Silicon。群晖只提供 FTP 媒体存储；字幕就绪状态、分类、计划和迁移不拆成两个执行端，也不再依赖 NFS/SMB 网络卷。

本机保存以下内容：

```text
/usr/local/subtrans/bin/subtrans       主程序
/usr/local/subtrans/etc/subtrans.toml  严格配置（不含密码）
/usr/local/subtrans/state/             SQLite 状态
/usr/local/subtrans/logs/              调度日志
```

状态库必须位于 Apple 本机磁盘。FTP 源根为 `/Downloads`，目标根为 `/`；目标根下必须能访问 `MOVIE`、`TV`、`X-Movie`、`X-TV`。真实服务器和端口写入被 Git 忽略的 `subtrans.toml`；TOML 只保存账号环境变量名，真实账号由执行环境提供。密码由环境变量或 macOS 钥匙串提供，不进入配置、计划、manifest 或日志；计划仅保存账号 SHA-256，用于防止换账号执行旧计划。

明文 FTP 没有传输加密，只能在隔离且可信的内网启用。若网络边界改变，应先迁移到 FTPS/SFTP 或 VPN，不得把当前端口暴露到公网。

## FTP 数据路径

目录迁移先尝试由群晖在同一 FTP 会话内改名。Downloads 和媒体库位于不同共享目录或存储卷时，群晖可能拒绝改名；程序会重新确认源仍存在且目标不存在，然后使用两个 FTP 会话把数据经 Apple 主机内存流写到目标临时名。上传大小和目标 SHA-256 全部验证通过后，才按伴随文件在前、视频在后的顺序删除源文件。

这种迁移不在 Apple 本机落一个完整媒体副本，但数据会经过 Apple 网络接口。应使用稳定有线网络；连接中断时临时文件会尽力清理，源文件不会在未验证目标前删除。

字幕处理不同：ffmpeg/ffprobe、PGS OCR 和 ASR 需要本地可寻址的视频。使用 FTP 时，程序会把当前视频下载到系统临时目录，处理结束自动删除。本机临时空间必须至少大于当前最大视频文件 128 MiB。状态数据库不能放进该临时目录。

## 凭据与启动

交互测试先设置 FTP 账号环境变量。生产部署建议把账号作为 launchd 的 `EnvironmentVariables` 注入，并录入与服务器、端口、运行时账号完全匹配的 macOS“互联网密码”；`-w` 必须放在命令最后，让系统安全提示输入：

```sh
export SUBTRANS_FTP_USERNAME='<FTP账号>'
security add-internet-password -U -a '<FTP账号>' -s '<FTP服务器>' -P 10021 -r 'ftp ' -w
subtrans doctor --config /usr/local/subtrans/etc/subtrans.toml
subtrans subtitles --config /usr/local/subtrans/etc/subtrans.toml --dry-run
```

不要把密码放入 shell 脚本、TOML、Git 或命令行参数。程序要求 `SUBTRANS_FTP_USERNAME` 存在；密码优先读取 `SUBTRANS_FTP_PASSWORD`，macOS 未设置密码变量时，通过 `/usr/bin/security` 读取匹配的钥匙串项目。launchd 模板只保存去敏后的账号占位符，不保存密码。账号缺失或两种密码来源都没有时，程序会在 FTP 登录前安全失败。

`subtrans doctor` 会检查 FTP 登录和所需目录，并在源根与四个目标根中分别短暂创建、验证、删除一个唯一空文件。探针清理失败会直接报错，不能视为部署成功。

## 安装和离线更新

1. 在相同 macOS/arm64 目标上执行 `cargo build --locked --release`。
2. 用 `shasum -a 256 target/release/subtrans` 记录校验和。
3. 停止调度，备份本机状态库及其 `-wal`/`-shm` 文件。
4. 将新文件放到临时名称，核对校验和和 `subtrans --version` 后原子替换旧主程序。
5. 运行 `subtrans doctor`、字幕 dry-run 和迁移 plan；人工复核后才恢复调度。

回退时恢复旧主程序。若新版本已写入状态库，不应直接恢复旧数据库；先保留完整副本，并按版本变更说明判断兼容性。

离线环境需预先固定并传输：`subtrans`、ffmpeg/ffprobe、Ollama 程序与模型、可选 worker 与模型。主程序运行时不会下载或安装任何依赖。

## 调度与人工批准

`deploy/com.subtrans.subtitles.plist.example` 是仅处理字幕的 launchd 模板。它包含 `SUBTRANS_FTP_USERNAME` 的替换占位符，但故意不包含 FTP 密码；本机安装副本必须填写账号且不得提交。目录迁移不放入无条件定时任务，流程始终是：

```sh
subtrans migrate plan --config /usr/local/subtrans/etc/subtrans.toml --output migration.plan.json
subtrans migrate review --config /usr/local/subtrans/etc/subtrans.toml --plan migration.plan.json
subtrans migrate apply --config /usr/local/subtrans/etc/subtrans.toml --plan migration.plan.json --approve '<plan_hash>'
```

每次修改覆盖、存储端点、阈值或命名规则后，都必须重新生成计划并重新批准哈希。

## 群晖原生执行门槛

目前不部署 DSM 执行端。只有确认群晖 CPU、DSM/glibc、断网恢复、共享锁和凭据管理均通过实机验收，并证明拆分有明显收益时才重新评估。macOS arm64 可执行文件不能复制到 DSM 运行。
