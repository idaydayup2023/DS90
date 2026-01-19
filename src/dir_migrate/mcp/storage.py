from __future__ import annotations

import posixpath
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from srt_translate.mcp.ftp import FtpMcp

from ..config import FtpConnConfig, StorageConfig


class StorageMcp(Protocol):
    def walk_files(self, root: str) -> list[tuple[str, int | None]]: ...
    def list_dir(self, path: str) -> list[tuple[str, str, int | None]]: ...
    def exists(self, rel_path: str) -> bool: ...
    def ensure_dir(self, rel_dir: str) -> None: ...
    def rename(self, src_rel: str, dst_rel: str, overwrite: bool) -> None: ...


def _ftp_abs(cfg: FtpConnConfig, rel_path: str) -> str:
    rel_path = rel_path.strip("/")
    root = cfg.root_path.rstrip("/") or "/"
    return posixpath.join(root, rel_path) if rel_path else root


def _ftp_strip_root(cfg: FtpConnConfig, abs_path: str) -> str:
    root = cfg.root_path.rstrip("/") or "/"
    if abs_path == root:
        return "/"
    if abs_path.startswith(root + "/"):
        return "/" + abs_path[len(root) + 1 :]
    return abs_path


@dataclass(frozen=True)
class LocalMcp(StorageMcp):
    root: Path

    def _abs(self, rel: str) -> Path:
        return (self.root / rel.strip("/")).resolve()

    def walk_files(self, root: str) -> list[tuple[str, int | None]]:
        base = self._abs(root)
        out: list[tuple[str, int | None]] = []
        if not base.exists():
            return out
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = "/" + str(p.relative_to(self.root)).replace("\\", "/")
            out.append((rel, p.stat().st_size))
        return out

    def list_dir(self, path: str) -> list[tuple[str, str, int | None]]:
        d = self._abs(path)
        out: list[tuple[str, str, int | None]] = []
        if not d.exists():
            return out
        for p in d.iterdir():
            rel = "/" + str(p.relative_to(self.root)).replace("\\", "/")
            t = "dir" if p.is_dir() else "file"
            size = p.stat().st_size if p.is_file() else None
            out.append((rel, t, size))
        return out

    def exists(self, rel_path: str) -> bool:
        return self._abs(rel_path).exists()

    def ensure_dir(self, rel_dir: str) -> None:
        self._abs(rel_dir).mkdir(parents=True, exist_ok=True)

    def rename(self, src_rel: str, dst_rel: str, overwrite: bool) -> None:
        src_p = self._abs(src_rel)
        dst_p = self._abs(dst_rel)
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        if dst_p.exists():
            if not overwrite:
                raise FileExistsError(str(dst_p))
            if dst_p.is_dir():
                shutil.rmtree(dst_p)
            else:
                dst_p.unlink()
        shutil.move(str(src_p), str(dst_p))


class FtpMcpStorage(StorageMcp):
    def __init__(self, cfg: FtpConnConfig):
        self._cfg = cfg

    def walk_files(self, root: str) -> list[tuple[str, int | None]]:
        out: list[tuple[str, int | None]] = []
        with FtpMcp(self._cfg.host, self._cfg.port, self._cfg.username, self._cfg.password, timeout=self._cfg.timeout_seconds) as ftp:
            for e in ftp.walk_files(_ftp_abs(self._cfg, root)):
                out.append((_ftp_strip_root(self._cfg, e.path), e.size))
        return out

    def list_dir(self, path: str) -> list[tuple[str, str, int | None]]:
        out: list[tuple[str, str, int | None]] = []
        with FtpMcp(self._cfg.host, self._cfg.port, self._cfg.username, self._cfg.password, timeout=self._cfg.timeout_seconds) as ftp:
            for e in ftp.list(_ftp_abs(self._cfg, path)):
                out.append((_ftp_strip_root(self._cfg, e.path), e.type, e.size))
        return out

    def exists(self, rel_path: str) -> bool:
        with FtpMcp(self._cfg.host, self._cfg.port, self._cfg.username, self._cfg.password, timeout=self._cfg.timeout_seconds) as ftp:
            return ftp.exists(_ftp_abs(self._cfg, rel_path))

    def ensure_dir(self, rel_dir: str) -> None:
        with FtpMcp(self._cfg.host, self._cfg.port, self._cfg.username, self._cfg.password, timeout=self._cfg.timeout_seconds) as ftp:
            ftp.ensure_dir(_ftp_abs(self._cfg, rel_dir))

    def rename(self, src_rel: str, dst_rel: str, overwrite: bool) -> None:
        src_abs = _ftp_abs(self._cfg, src_rel)
        dst_abs = _ftp_abs(self._cfg, dst_rel)
        with FtpMcp(self._cfg.host, self._cfg.port, self._cfg.username, self._cfg.password, timeout=self._cfg.timeout_seconds) as ftp:
            ftp.ensure_dir(posixpath.dirname(dst_abs))
            if ftp.exists(dst_abs):
                if not overwrite:
                    raise FileExistsError(dst_abs)
                ftp.delete(dst_abs)
            ftp.rename(src_abs, dst_abs)


def build_storage_mcp(cfg: StorageConfig) -> StorageMcp:
    if cfg.kind == "local":
        if cfg.local_root is None:
            raise ValueError("local_root is required for local storage")
        return LocalMcp(root=cfg.local_root)
    if cfg.kind == "ftp":
        if cfg.ftp is None:
            raise ValueError("ftp config is required for ftp storage")
        return FtpMcpStorage(cfg.ftp)
    raise ValueError(f"unsupported storage kind: {cfg.kind}")

