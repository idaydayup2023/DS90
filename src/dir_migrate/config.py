from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class FtpConnConfig:
    host: str
    port: int
    username: str
    password: str
    root_path: str
    timeout_seconds: int = 30


@dataclass(frozen=True)
class StorageConfig:
    kind: str
    ftp: FtpConnConfig | None = None
    local_root: Path | None = None


@dataclass(frozen=True)
class PathsConfig:
    local_cache_dir: Path


@dataclass(frozen=True)
class VideoConfig:
    extensions: tuple[str, ...]
    min_bytes: int


@dataclass(frozen=True)
class SubtitleConfig:
    extensions: tuple[str, ...]


@dataclass(frozen=True)
class CleanupConfig:
    enabled: bool = True
    protected_dirnames: tuple[str, ...] = ("torrent.files", "low_imdb")
    min_confidence: float = 0.85
    delete_residual_files: bool = True


@dataclass(frozen=True)
class LlmConfig:
    provider: str  # "ollama" or "lm-studio"
    base_url: str
    model: str
    timeout_seconds: int = 120
    temperature: float = 0.2


@dataclass(frozen=True)
class RulesConfig:
    movie_1080_root: str
    movie_4k_root: str
    tv_1080_root: str
    tv_4k_root: str
    year_split: int = 2024
    franchise_map: dict[str, str] | None = None


@dataclass(frozen=True)
class ExecutionConfig:
    dry_run: bool
    apply: bool
    limit: int | None
    workers: int
    on_conflict: str = "skip"


@dataclass(frozen=True)
class ImdbConfig:
    enabled: bool = False
    auto_install: bool = True
    ttl_days: int = 30
    min_rating: float | None = 5.0
    min_votes: int | None = None
    skip_unrated: bool = True
    use_llm_judge: bool = False


@dataclass(frozen=True)
class AppConfig:
    source: StorageConfig
    dest: StorageConfig
    paths: PathsConfig
    video: VideoConfig
    subtitle: SubtitleConfig
    cleanup: CleanupConfig
    llm: LlmConfig
    imdb: ImdbConfig
    rules: RulesConfig
    execution: ExecutionConfig

    def with_execution(self, dry_run: bool | None = None, apply: bool | None = None, limit: int | None = None) -> "AppConfig":
        ex = self.execution
        if dry_run is not None:
            ex = replace(ex, dry_run=dry_run)
        if apply is not None:
            ex = replace(ex, apply=apply)
        if limit is not None:
            ex = replace(ex, limit=limit)
        return replace(self, execution=ex)


def _require(d: dict[str, Any], key: str) -> Any:
    if key not in d:
        raise KeyError(f"missing config key: {key}")
    return d[key]


def _as_tuple_str(v: Any) -> tuple[str, ...]:
    if isinstance(v, (list, tuple)):
        return tuple(str(x) for x in v)
    raise TypeError("expected list/tuple of strings")


def _expand_path(p: str | Path) -> Path:
    return Path(p).expanduser().resolve()


def normalize_extensions(exts: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    for e in exts:
        e = e.strip().lower()
        if not e:
            continue
        if not e.startswith("."):
            e = "." + e
        out.append(e)
    return tuple(dict.fromkeys(out))


def _load_storage(raw: dict[str, Any]) -> StorageConfig:
    kind = str(_require(raw, "kind")).lower()
    if kind == "ftp":
        ftp_raw = _require(raw, "ftp")
        ftp = FtpConnConfig(
            host=str(_require(ftp_raw, "host")),
            port=int(ftp_raw.get("port", 21)),
            username=str(_require(ftp_raw, "username")),
            password=str(_require(ftp_raw, "password")),
            root_path=str(_require(ftp_raw, "root_path")),
            timeout_seconds=int(ftp_raw.get("timeout_seconds", 30)),
        )
        return StorageConfig(kind="ftp", ftp=ftp, local_root=None)
    if kind == "local":
        local_root = _expand_path(_require(raw, "root_path"))
        return StorageConfig(kind="local", ftp=None, local_root=local_root)
    raise ValueError(f"unsupported storage kind: {kind}")


def _load_storage_with_fallback(storage_raw: dict[str, Any], common_ftp_raw: dict[str, Any] | None) -> StorageConfig:
    kind = str(_require(storage_raw, "kind")).lower()
    if kind == "ftp":
        if "ftp" in storage_raw and storage_raw["ftp"] is not None:
            return _load_storage(storage_raw)
        if common_ftp_raw is None:
            raise KeyError("missing config key: ftp (no common ftp to inherit)")
        ftp = FtpConnConfig(
            host=str(_require(common_ftp_raw, "host")),
            port=int(common_ftp_raw.get("port", 21)),
            username=str(_require(common_ftp_raw, "username")),
            password=str(_require(common_ftp_raw, "password")),
            root_path=str(storage_raw.get("root_path") or common_ftp_raw.get("root_path") or "/"),
            timeout_seconds=int(common_ftp_raw.get("timeout_seconds", 30)),
        )
        return StorageConfig(kind="ftp", ftp=ftp, local_root=None)
    if kind == "local":
        if "root_path" in storage_raw:
            return _load_storage(storage_raw)
        if "local_root" in storage_raw:
            local_root = _expand_path(storage_raw["local_root"])
            return StorageConfig(kind="local", ftp=None, local_root=local_root)
        raise KeyError("missing config key: root_path")
    raise ValueError(f"unsupported storage kind: {kind}")


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    raw_all = json.loads(path.read_text(encoding="utf-8"))

    tool_raw = raw_all.get("dir_migrate") if isinstance(raw_all, dict) and "dir_migrate" in raw_all else raw_all
    if not isinstance(tool_raw, dict):
        raise TypeError("invalid config: expected object")

    common_ftp_raw = raw_all.get("ftp") if isinstance(raw_all, dict) else None
    common_paths_raw = raw_all.get("paths") if isinstance(raw_all, dict) else None
    common_video_raw = raw_all.get("video") if isinstance(raw_all, dict) else None
    common_ollama_raw = raw_all.get("ollama") if isinstance(raw_all, dict) else None

    source = _load_storage_with_fallback(_require(tool_raw, "source"), common_ftp_raw)
    dest = _load_storage_with_fallback(_require(tool_raw, "dest"), common_ftp_raw)

    paths_raw = tool_raw.get("paths")
    if paths_raw is None and isinstance(common_paths_raw, dict) and "local_cache_dir" in common_paths_raw:
        common_cache = _expand_path(common_paths_raw["local_cache_dir"])
        paths = PathsConfig(local_cache_dir=(common_cache.parent / "dir_migrate").resolve())
    else:
        paths_raw = paths_raw or {}
        default_cache = ".cache/dir_migrate"
        if isinstance(common_paths_raw, dict) and "local_cache_dir" in common_paths_raw:
            try:
                default_cache = str((_expand_path(common_paths_raw["local_cache_dir"]).parent / "dir_migrate").resolve())
            except Exception:
                default_cache = ".cache/dir_migrate"
        paths = PathsConfig(local_cache_dir=_expand_path(paths_raw.get("local_cache_dir", default_cache)))

    video_raw = tool_raw.get("video") or common_video_raw
    if video_raw is None:
        raise KeyError("missing config key: video")
    video = VideoConfig(
        extensions=normalize_extensions(_as_tuple_str(_require(video_raw, "extensions"))),
        min_bytes=int(video_raw.get("min_bytes", 0)),
    )

    sub_raw = tool_raw.get("subtitle") or {}
    subtitle = SubtitleConfig(extensions=normalize_extensions(_as_tuple_str(sub_raw.get("extensions", [".srt", ".ass", ".ssa", ".vtt"]))))

    cleanup_raw = tool_raw.get("cleanup") or {}
    protected = [str(x).strip() for x in cleanup_raw.get("protected_dirnames", ["torrent.files", "low_imdb"]) if str(x).strip()]
    lower_set = {p.lower() for p in protected}
    if "torrent.files" not in lower_set:
        protected.append("torrent.files")
    if "low_imdb" not in lower_set:
        protected.append("low_imdb")
    cleanup = CleanupConfig(
        enabled=bool(cleanup_raw.get("enabled", True)),
        protected_dirnames=tuple(dict.fromkeys(protected)),
        min_confidence=float(cleanup_raw.get("min_confidence", 0.85)),
        delete_residual_files=bool(cleanup_raw.get("delete_residual_files", True)),
    )

    # Support both "llm" and "ollama" keys for backward compatibility
    llm_raw = tool_raw.get("llm") or tool_raw.get("ollama") or common_ollama_raw
    if llm_raw is None:
        raise KeyError("missing config key: llm (or ollama)")
    
    llm = LlmConfig(
        provider=str(llm_raw.get("provider", "ollama")),
        base_url=str(_require(llm_raw, "base_url")),
        model=str(llm_raw.get("model", "translategemma")),
        timeout_seconds=int(llm_raw.get("timeout_seconds", 120)),
        temperature=float(llm_raw.get("temperature", 0.2)),
    )

    imdb_raw = tool_raw.get("imdb") or {}
    imdb = ImdbConfig(
        enabled=bool(imdb_raw.get("enabled", False)),
        auto_install=bool(imdb_raw.get("auto_install", True)),
        ttl_days=int(imdb_raw.get("ttl_days", 30)),
        min_rating=float(imdb_raw["min_rating"]) if "min_rating" in imdb_raw and imdb_raw["min_rating"] is not None else None,
        min_votes=int(imdb_raw["min_votes"]) if "min_votes" in imdb_raw and imdb_raw["min_votes"] is not None else None,
        skip_unrated=bool(imdb_raw.get("skip_unrated", False)),
        use_llm_judge=bool(imdb_raw.get("use_llm_judge", True)),
    )

    rules_raw = tool_raw.get("rules") or {}
    rules = RulesConfig(
        movie_1080_root=str(rules_raw.get("movie_1080_root", "X-Movie")),
        movie_4k_root=str(rules_raw.get("movie_4k_root", "MOVIE")),
        tv_1080_root=str(rules_raw.get("tv_1080_root", "X-TV")),
        tv_4k_root=str(rules_raw.get("tv_4k_root", "TV")),
        year_split=int(rules_raw.get("year_split", 2024)),
        franchise_map=dict(rules_raw.get("franchise_map") or {}),
    )

    exec_raw = tool_raw.get("execution") or {}
    execution = ExecutionConfig(
        dry_run=bool(exec_raw.get("dry_run", True)),
        apply=bool(exec_raw.get("apply", False)),
        limit=exec_raw.get("limit"),
        workers=int(exec_raw.get("workers", 2)),
        on_conflict=str(exec_raw.get("on_conflict", "skip")),
    )

    return AppConfig(
        source=source,
        dest=dest,
        paths=paths,
        video=video,
        subtitle=subtitle,
        cleanup=cleanup,
        llm=llm,
        imdb=imdb,
        rules=rules,
        execution=execution,
    )


def ensure_dirs(cfg: AppConfig) -> None:
    cfg.paths.local_cache_dir.mkdir(parents=True, exist_ok=True)
