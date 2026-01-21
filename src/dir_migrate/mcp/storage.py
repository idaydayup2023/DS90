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
    def read_text(self, rel_path: str, max_bytes: int = 262144) -> str: ...
    def delete_file(self, rel_path: str) -> None: ...
    def delete_dir_tree(self, rel_dir: str) -> None: ...
    def rmdir_if_empty(self, rel_dir: str) -> bool: ...


def _ftp_abs(cfg: FtpConnConfig, rel_path: str) -> str:
    # If rel_path starts with /, assume it is already absolute relative to FTP root
    # But wait, our 'rel_path' in the app is relative to 'cfg.root_path'.
    # If cfg.root_path is /Downloads, and rel_path is /Sub/File.mkv, 
    # we want /Downloads/Sub/File.mkv.
    
    # However, if rel_path is MEANT to be absolute (like /X-TV/...), 
    # then we should NOT prepend root_path if it's already outside.
    
    # But 'StorageMcp' abstraction says:
    # "walk_files returns paths relative to root"
    # "rename takes src_rel and dst_rel"
    
    # The issue is that 'dst_dir_for' in planning.py returns an absolute path like "/X-TV/..."
    # If we prepend "/Downloads" to "/X-TV/...", we get "/Downloads/X-TV/..." which is WRONG.
    
    # We need to detect if the path is intended to be absolute (target) or relative (source).
    # But storage abstraction usually implies a chroot.
    
    # If the user wants to migrate FROM /Downloads TO /X-TV, 
    # these are likely two different "Storage" instances if they were truly chrooted.
    # But here we are using ONE FtpMcpStorage for both source and dest (or at least same connection config).
    
    # If we look at 'config.py', source and dest share the same FTP credentials usually.
    # If dest.root_path is "/" (root of FTP), then "/X-TV" works fine.
    # If source.root_path is "/Downloads", then "Sub/File.mkv" becomes "/Downloads/Sub/File.mkv".
    
    # Let's check how _ftp_abs is implemented:
    # rel_path = rel_path.strip("/") -> "X-TV/..."
    # root = cfg.root_path.rstrip("/") -> "/Downloads"
    # join -> "/Downloads/X-TV/..." -> WRONG for destination.
    
    # FIX: We should trust the caller. 
    # If the caller provides a path starting with "/", treat it as absolute on the FTP server?
    # Or, we should enforce that 'StorageMcp' is strictly rooted.
    
    # In 'dir_migrate', we have 'source_storage' (root=/Downloads) and 'dest_storage' (root=/).
    # If dest_storage is configured with root="/", then "/X-TV" becomes "X-TV" joined with "/", which is "/X-TV". Correct.
    
    # So the issue is likely that 'dest_storage' is being initialized with the WRONG root (maybe /Downloads?).
    # Let's check 'config.py' again.
    
    # If config.json says:
    # "dir_migrate": { "source": { "kind": "ftp", "ftp": { ... "root_path": "/Downloads" } }, 
    #                  "dest": { "kind": "ftp", "ftp": { ... "root_path": "/" } } }
    # Then it works.
    
    # But if the user reuses the "ftp" section from common config:
    # "ftp": { "root_path": "/Downloads" }
    # And "dest" falls back to this... then dest root is /Downloads.
    
    # We need to override root_path for destination if it's meant to be root-relative.
    # But let's look at _ftp_abs logic again.
    
    if rel_path.startswith("/"):
        return rel_path
    rel_path = rel_path.strip("/")
    root = cfg.root_path.rstrip("/") or "/"
    return posixpath.join(root, rel_path) if rel_path else root


def _ftp_strip_root(cfg: FtpConnConfig, abs_path: str) -> str:
    root = cfg.root_path.rstrip("/") or "/"
    if root == "/":
        return abs_path
    if abs_path == root:
        return ""
    if abs_path.startswith(root + "/"):
        return abs_path[len(root) + 1 :]
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
            rel = str(p.relative_to(self.root)).replace("\\", "/")
            out.append((rel, p.stat().st_size))
        return out

    def list_dir(self, path: str) -> list[tuple[str, str, int | None]]:
        d = self._abs(path)
        out: list[tuple[str, str, int | None]] = []
        if not d.exists():
            return out
        for p in d.iterdir():
            rel = str(p.relative_to(self.root)).replace("\\", "/")
            t = "dir" if p.is_dir() else "file"
            size = p.stat().st_size if p.is_file() else None
            out.append((rel, t, size))
        return out

    def exists(self, rel_path: str) -> bool:
        return self._abs(rel_path).exists()

    def read_text(self, rel_path: str, max_bytes: int = 262144) -> str:
        p = self._abs(rel_path)
        if not p.exists() or not p.is_file():
            return ""
        data = p.read_bytes()[: max(0, int(max_bytes))]
        return data.decode("utf-8", errors="replace")

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

    def delete_file(self, rel_path: str) -> None:
        p = self._abs(rel_path)
        if not p.exists() or not p.is_file():
            return
        try:
            p.unlink()
        except Exception:
            pass

    def rmdir_if_empty(self, rel_dir: str) -> bool:
        p = self._abs(rel_dir)
        if not p.exists() or not p.is_dir():
            return False
        try:
            p.rmdir()
            return True
        except Exception:
            return False

    def delete_dir_tree(self, rel_dir: str) -> None:
        p = self._abs(rel_dir)
        if not p.exists() or not p.is_dir():
            return
        shutil.rmtree(p, ignore_errors=True)


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
            try:
                return ftp.exists(_ftp_abs(self._cfg, rel_path))
            except Exception:
                return False

    def read_text(self, rel_path: str, max_bytes: int = 262144) -> str:
        import tempfile
        abs_path = _ftp_abs(self._cfg, rel_path)
        with FtpMcp(self._cfg.host, self._cfg.port, self._cfg.username, self._cfg.password, timeout=self._cfg.timeout_seconds) as ftp:
            with tempfile.NamedTemporaryFile(delete=True) as tmp:
                try:
                    ftp.download(abs_path, Path(tmp.name))
                except Exception:
                    return ""
                try:
                    data = Path(tmp.name).read_bytes()[: max(0, int(max_bytes))]
                except Exception:
                    return ""
        return data.decode("utf-8", errors="replace")

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

    def delete_file(self, rel_path: str) -> None:
        with FtpMcp(self._cfg.host, self._cfg.port, self._cfg.username, self._cfg.password, timeout=self._cfg.timeout_seconds) as ftp:
            try:
                ftp.delete(_ftp_abs(self._cfg, rel_path))
            except Exception:
                pass

    def rmdir_if_empty(self, rel_dir: str) -> bool:
        with FtpMcp(self._cfg.host, self._cfg.port, self._cfg.username, self._cfg.password, timeout=self._cfg.timeout_seconds) as ftp:
            try:
                return ftp.rmdir_if_empty(_ftp_abs(self._cfg, rel_dir))
            except Exception:
                return False

    def delete_dir_tree(self, rel_dir: str) -> None:
        base = rel_dir.rstrip("/") or "/"
        if base == "/":
            return
        with FtpMcp(self._cfg.host, self._cfg.port, self._cfg.username, self._cfg.password, timeout=self._cfg.timeout_seconds) as ftp:
            stack = [base]
            while stack:
                cur = stack.pop()
                entries = ftp.list(_ftp_abs(self._cfg, cur))
                dirs: list[str] = []
                files: list[str] = []
                for e in entries:
                    rel = _ftp_strip_root(self._cfg, e.path)
                    if e.type in ("dir", "cdir", "pdir"):
                        if e.type == "dir":
                            dirs.append(rel)
                        continue
                    files.append(rel)
                if dirs:
                    stack.append(cur)
                    stack.extend(dirs)
                    continue
                for f in files:
                    try:
                        ftp.delete(_ftp_abs(self._cfg, f))
                    except Exception:
                        pass
                try:
                    ftp.rmdir(_ftp_abs(self._cfg, cur))
                except Exception:
                    pass


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
