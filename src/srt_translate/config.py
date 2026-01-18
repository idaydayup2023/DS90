from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class FtpConfig:
    host: str
    port: int
    username: str
    password: str
    root_path: str = "/Downloads"
    concurrency: int = 4


@dataclass(frozen=True)
class PathsConfig:
    local_cache_dir: Path
    state_db_path: Path


@dataclass(frozen=True)
class VideoConfig:
    extensions: tuple[str, ...]
    min_bytes: int


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    model: str
    timeout_seconds: int = 120
    temperature: float = 0.2


@dataclass(frozen=True)
class WhisperConfig:
    enabled: bool
    command: tuple[str, ...]
    language: str | None
    asr_workers: int = 1


@dataclass(frozen=True)
class TranslationConfig:
    workers: int = 2
    batch_size: int = 20
    max_retries: int = 2


@dataclass(frozen=True)
class AppConfig:
    ftp: FtpConfig
    paths: PathsConfig
    video: VideoConfig
    ollama: OllamaConfig
    whisper: WhisperConfig
    translation: TranslationConfig


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


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    ftp_raw = _require(raw, "ftp")
    ftp = FtpConfig(
        host=str(_require(ftp_raw, "host")),
        port=int(ftp_raw.get("port", 21)),
        username=str(_require(ftp_raw, "username")),
        password=str(_require(ftp_raw, "password")),
        root_path=str(ftp_raw.get("root_path", "/Downloads")),
        concurrency=int(ftp_raw.get("concurrency", 4)),
    )

    paths_raw = _require(raw, "paths")
    local_cache_dir = _expand_path(_require(paths_raw, "local_cache_dir"))
    state_db_path = _expand_path(_require(paths_raw, "state_db_path"))
    paths_cfg = PathsConfig(local_cache_dir=local_cache_dir, state_db_path=state_db_path)

    video_raw = _require(raw, "video")
    exts = _as_tuple_str(_require(video_raw, "extensions"))
    video = VideoConfig(extensions=exts, min_bytes=int(video_raw.get("min_bytes", 0)))

    ollama_raw = _require(raw, "ollama")
    ollama = OllamaConfig(
        base_url=str(_require(ollama_raw, "base_url")),
        model=str(_require(ollama_raw, "model")),
        timeout_seconds=int(ollama_raw.get("timeout_seconds", 120)),
        temperature=float(ollama_raw.get("temperature", 0.2)),
    )

    whisper_raw = _require(raw, "whisper")
    whisper = WhisperConfig(
        enabled=bool(whisper_raw.get("enabled", True)),
        command=_as_tuple_str(_require(whisper_raw, "command")),
        language=whisper_raw.get("language"),
        asr_workers=int(whisper_raw.get("asr_workers", 1)),
    )

    translation_raw = _require(raw, "translation")
    translation = TranslationConfig(
        workers=int(translation_raw.get("workers", 2)),
        batch_size=int(translation_raw.get("batch_size", 20)),
        max_retries=int(translation_raw.get("max_retries", 2)),
    )

    return AppConfig(
        ftp=ftp,
        paths=paths_cfg,
        video=video,
        ollama=ollama,
        whisper=whisper,
        translation=translation,
    )


def ensure_dirs(cfg: AppConfig) -> None:
    cfg.paths.local_cache_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.state_db_path.parent.mkdir(parents=True, exist_ok=True)


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
