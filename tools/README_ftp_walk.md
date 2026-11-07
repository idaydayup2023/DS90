# ds90_ftp_walk — 全队共用 FTP 列举/遍历库

> 代码运维 2026-11-07，站长派单落库。两支文件：`ds90_ftp_walk.py`（库本体，
> **stdlib-only 零依赖**）、`ds90_ftp_walk_selftest.py`（自检，A 层需 pyftpdlib 起
> 本地测试服务器，B 层零依赖）。**今后 FTP 盘点头这库**，别再各写各的扫描脚本。

## 为什么必须有这个库（坑位清单，全是 NAS 实测）

| # | 坑 | 症状 | 本库的治法 |
|---|---|---|---|
| 1 | **方括号路径带参列举静默返 0** | `/TV/[A.B.C]` 这类组发 `NLST <路径>` / `MLSD <路径>` 返 **0 条且不报错**，看着像空目录，实际组内 80 条（11-07 实证） | 一律 **CWD 进目录 + 无参 LIST** 为准绳；代码路径不存在带参 MLSD/NLST（自检 B1 断言锁死） |
| 2 | **单姿势可能说谎** | LIST 偶发返 0 但目录有件 | LIST=0 自动换无参 MLSD（不支持则无参 NLST）复验；打架 → `SUSPECT_EMPTY`；**两旁证都不可用的 0 也不当空** |
| 3 | **中文路径 RNFR 偶发瞬态 550** | 迁移改名半道 550，重试即成（11-07 库务实证） | `rename_with_retry` 内置：瞬态 550/4xx/瞬断 → **新连接**指数退避（默认 3 次 1s、2s） |
| 4 | **`#recycle` 回收站混进盘点** | DSM 每共享下有 `<共享>/#recycle`，扫进来虚增件数 | `walk` 默认 `exclude=("#recycle",)`，可自行追加（如 `.Trash`） |
| 5 | **DS 中文路径列举老 bug**（10-30 铁律由来） | 中文路径列举不可靠 | **新建**任务/目录命名一律禁中文、英文点号化；存量中文路径本库读（UTF-8）无碍 |
| 6 | **MOVIE-EXT 不是 FTP 共享** | FTP 怎么扫都"没有"这个区 | 去 `/volume2/MOVIE-EXT` 要用 **SSH**（仓库 `tools/ds90_ssh.sh` 姿势），FTP 库读不到它 |

**死活契约**：`walk` 逐目录结果 fsync 落 jsonl，成功收尾写尾行 `{"event":"DONE",...}`。
判扫描死活**只认 DONE 行**——半截 jsonl = 进程死了，里面的计数一律不信。

## 用法

```bash
# CLI（只读遍历）：逐目录 fsync 落 jsonl + DONE 尾行；退出码 0 干净 / 2 有 missing
python3 tools/ds90_ftp_walk.py --root "/TV/[A.B.C]" --out logs/walk.jsonl

# 多根 / 限深 / 加严对照（每目录 LIST+MLSD 全跑）/ 自定义排除
python3 tools/ds90_ftp_walk.py --root /TV --root /影视 --out logs/w.jsonl \
    --corroborate all --depth 2 --exclude '#recycle' --exclude '.Trash'
```

```python
from ds90_ftp_walk import FtpWalker          # 凭证取 DSH_SECRET_SUBTRANS_FTP_* env
w = FtpWalker()                               # 默认 172.19.60.90:10021 明文 FTP PASV（60021 是 SFTP 假入口别用）
r = w.list_dir("/TV/[A.B.C]")                 # status: ok | ok_methods_differ | empty | suspect_empty | missing
                                              # entries: {dirs:[...], files:[{name,size}], unknown:[...]}
w.walk(["/TV"], "logs/w.jsonl")               # 死活只认尾行 DONE
w.rename_with_retry(src, dst)                 # 迁移改名姿势（瞬态 550 自动新连接退避）
w.makedirs(rel); w.delete_with_retry(p)
```

读数口径：`suspect_empty` ≠ 空，需人工/换时段复核；`missing` 仅指重试耗尽后仍 550；
`entries.unknown` 是无类型条目（NLST 旁证型），walk 自动试探定性——目录续爬、文件归
文件不污染 missing；直接调 `list_dir` 的调用方自行判 unknown。

## 自检（改库必跑）

```bash
python3 -m venv .venv && .venv/bin/pip install pyftpdlib   # 仅 A 层需要
.venv/bin/python tools/ds90_ftp_walk_selftest.py           # 期望 16/16 PASS，退出码 0
```

A 层：pyftpdlib 起真 FTP 端到端——方括号 80 件组、中文目录+中文文件名、空格、
超长名、7 层深嵌套不漏；真空中判 empty；`#recycle` 排除生效；DONE 计数对上。
B 层：mock 注入 NAS 病态——带参静默 0、LIST 假空打架、瞬态/持续 550、RNFR 重试、
NLST 绝对路径归一、unknown 试探定性、jsonl 死活契约。

## 真 NAS 实证（2026-11-07，`/TV/[A.B.C]` 80 件组）

| 姿势 | 条数 |
|---|---|
| CWD + 无参 LIST（库准绳） | **80** ✅ |
| `NLST /TV/[A.B.C]` 带参 | 0（坑复现） |
| `MLSD /TV/[A.B.C]` 带参 | 0（坑复现） |
| CWD 后无参 NLST / MLSD | 80 / 80 |

## 判主件别用扩展名正则（坑，2026-11-07）

种源壳目录里的正片常**没有扩展名**（如 `The Bone Collector 1080p BluRay
x265 HEVC 10bit AA`）。用 `\.(mkv|mp4|...)$` 之类正则筛会把它们全判成
"壳里没片"，白下一趟种。

用本库公开 helper：

```python
from ds90_ftp_walk import classify_file, is_video_candidate
classify_file(name, size)   # "main" | "noext" | "other"
is_video_candidate(name, size)  # main/noext 均为 True
```

默认口径：**size > 300 MB 且扩展名 ∉ nfo/sfv/字幕/图档排除表 即认主件**；
无扩展名大文件返回 `"noext"`（是主件，单列便于人工复核）。阈值与排除表
可经 `min_bytes` / `non_main_ext` 覆写。自检：`--selftest-classify`。
