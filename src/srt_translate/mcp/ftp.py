from __future__ import annotations

import ftplib
import os
import posixpath
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FtpEntry:
    path: str
    type: str
    size: int | None
    mtime: int | None


class FtpMcp:
    def __init__(self, host: str, port: int, username: str, password: str, timeout: int = 30):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._timeout = timeout
        self._ftp: ftplib.FTP | None = None

    def __enter__(self) -> "FtpMcp":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> None:
        if self._ftp is not None:
            try:
                self._ftp.voidcmd("NOOP")
                return
            except Exception:
                self.close()
        
        ftp = ftplib.FTP()
        ftp.connect(self._host, self._port, timeout=self._timeout)
        ftp.encoding = "utf-8"
        ftp.login(self._username, self._password)
        self._ftp = ftp

    def close(self) -> None:
        if self._ftp is None:
            return
        try:
            self._ftp.quit()
        except Exception:
            try:
                self._ftp.close()
            except Exception:
                pass
        finally:
            self._ftp = None

    @property
    def ftp(self) -> ftplib.FTP:
        if self._ftp is None:
            raise RuntimeError("FTP not connected")
        return self._ftp

    def stat(self, path: str) -> FtpEntry | None:
        parent, name = posixpath.split(path.rstrip("/"))
        if not parent:
            parent = "/"
        for e in self.list(parent):
            if posixpath.basename(e.path) == name:
                return e
        return None

    def list(self, path: str) -> list[FtpEntry]:
        path = path or "/"
        out: list[FtpEntry] = []
        try:
            for name, facts in self.ftp.mlsd(path):
                if name in (".", ".."):
                    continue
                p = posixpath.join(path, name)
                t = facts.get("type", "file")
                size_str = facts.get("size")
                mtime = facts.get("modify")
                out.append(
                    FtpEntry(
                        path=p,
                        type=t,
                        size=int(size_str) if size_str is not None else None,
                        mtime=int(time.mktime(time.strptime(mtime, "%Y%m%d%H%M%S"))) if mtime else None,
                    )
                )
            return out
        except Exception:
            # Retry nlst once if connection is broken
            try:
                self.ftp.voidcmd("NOOP")
            except Exception:
                self.close()
                self.connect()

            try:
                names = self.ftp.nlst(path)
            except Exception:
                 # If nlst fails (e.g. 550 No such file), it might be because the dir doesn't exist.
                 # Return empty list in that case.
                 return []
                 
            for p in names:
                if p.endswith("/.") or p.endswith("/.."):
                    continue
                t = "file"
                try:
                    self.ftp.cwd(p)
                    self.ftp.cwd(path)
                    t = "dir"
                except Exception:
                    t = "file"
                size: int | None = None
                if t == "file":
                    try:
                        size = self.ftp.size(p)
                    except Exception:
                        size = None
                out.append(FtpEntry(path=p, type=t, size=size, mtime=None))
            return out

    def walk_files(self, root: str) -> Iterable[FtpEntry]:
        stack = [root.rstrip("/") or "/"]
        while stack:
            cur = stack.pop()
            for e in self.list(cur):
                if e.type in ("dir", "cdir", "pdir"):
                    if e.type == "dir":
                        stack.append(e.path)
                    continue
                out = e
                if out.type not in ("file",):
                    out = FtpEntry(path=e.path, type="file", size=e.size, mtime=e.mtime)
                yield out

    def download(self, remote_path: str, local_path: Path) -> int:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with local_path.open("wb") as f:
            def _write(chunk: bytes) -> None:
                nonlocal size
                size += len(chunk)
                f.write(chunk)

            self.ftp.retrbinary(f"RETR {remote_path}", _write)
        return size

    def upload(self, local_path: Path, remote_path: str) -> int:
        self.ensure_dir(posixpath.dirname(remote_path))
        size = 0
        with local_path.open("rb") as f:
            def _read(block: bytes) -> None:
                nonlocal size
                size += len(block)

            self.ftp.storbinary(f"STOR {remote_path}", f, callback=_read)
        return size

    def ensure_dir(self, remote_dir: str) -> None:
        remote_dir = remote_dir.rstrip("/")
        if not remote_dir:
            return
        parts = remote_dir.split("/")
        cur = ""
        for part in parts:
            if not part:
                continue
            cur = cur + "/" + part
            try:
                self.ftp.mkd(cur)
            except Exception:
                pass

    def exists(self, remote_path: str) -> bool:
        return self.stat(remote_path) is not None

    def delete(self, remote_path: str) -> None:
        try:
            self.ftp.delete(remote_path)
        except Exception:
            pass

    def rename(self, src: str, dst: str) -> None:
        try:
            self.ftp.rename(src, dst)
        except Exception:
            # Reconnect and retry once if broken pipe
            self.close()
            self.connect()
            self.ftp.rename(src, dst)

    def rmdir(self, remote_dir: str) -> None:
        remote_dir = remote_dir.rstrip("/") or "/"
        if remote_dir == "/":
            return
        self.ftp.rmd(remote_dir)

    def rmdir_if_empty(self, remote_dir: str) -> bool:
        remote_dir = remote_dir.rstrip("/") or "/"
        if remote_dir == "/":
            return False
        try:
            if self.list(remote_dir):
                return False
        except Exception:
            return False
        try:
            self.rmdir(remote_dir)
            return True
        except Exception:
            return False

    def atomic_write_from_bytes(self, remote_path: str, data: bytes) -> None:
        tmp = f"{remote_path}.tmp.{os.getpid()}.{int(time.time())}"
        self.ensure_dir(posixpath.dirname(remote_path))
        from io import BytesIO

        with BytesIO(data) as bio:
            self.ftp.storbinary(f"STOR {tmp}", bio)
        if self.exists(remote_path):
            self.delete(remote_path)
        self.rename(tmp, remote_path)

    def atomic_write_from_file(self, remote_path: str, local_path: Path) -> None:
        tmp = f"{remote_path}.tmp.{os.getpid()}.{int(time.time())}"
        self.ensure_dir(posixpath.dirname(remote_path))
        self.upload(local_path, tmp)
        if self.exists(remote_path):
            self.delete(remote_path)
        self.rename(tmp, remote_path)
