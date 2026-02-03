from __future__ import annotations

import ftplib
import logging
import os
import posixpath
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FtpEntry:
    path: str
    type: str
    size: int | None
    mtime: int | None


class FtpMcp:
    def __init__(self, host: str, port: int, username: str, password: str, timeout: int = 14400):
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
        # Initial connect timeout
        ftp.connect(self._host, self._port, timeout=60)
        ftp.encoding = "utf-8"
        ftp.login(self._username, self._password)
        ftp.set_pasv(True)
        # Ensure binary mode for accurate SIZE and transfers
        ftp.voidcmd("TYPE I")
        
        # Set a long timeout for the session
        if ftp.sock:
            ftp.sock.settimeout(self._timeout)
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
        name_lower = name.lower()
        for e in self.list(parent):
            b = posixpath.basename(e.path)
            if b == name or b.lower() == name_lower:
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
        self.connect()
        
        size: int = 0
        try:
            sz = self.ftp.size(remote_path)
            if sz is not None:
                size = sz
        except Exception:
            try:
                entry = self.stat(remote_path)
                if entry and entry.size is not None:
                    size = entry.size
            except Exception:
                size = 0
            
        log.info("ftp: downloading %s (%s bytes)", remote_path, size)
        downloaded = 0
        last_log_time = time.time()

        with local_path.open("wb") as f:
            def _write(data: bytes) -> None:
                nonlocal downloaded, last_log_time
                f.write(data)
                downloaded += len(data)
                now = time.time()
                
                # Log progress every 10 seconds
                if now - last_log_time > 10:
                    if size > 0:
                        percent = (downloaded / size * 100)
                        log.info("ftp: download progress %s: %.1f%% (%d/%d)", remote_path, percent, downloaded, size)
                    else:
                        log.info("ftp: download progress %s: %d bytes", remote_path, downloaded)
                    last_log_time = now

            # Use a large blocksize (1MB) for faster transfers of large files
            self.ftp.retrbinary(f"RETR {remote_path}", _write, blocksize=1024*1024)
        
        log.info("ftp: download finished %s (%d bytes)", remote_path, downloaded)
        return downloaded

    def upload(self, local_path: Path, remote_path: str) -> int:
        self.ensure_dir(posixpath.dirname(remote_path))
        self.connect()
        
        size = local_path.stat().st_size
        log.info("ftp: uploading %s (%s bytes)", remote_path, size)
        uploaded = 0
        last_log_time = time.time()

        with local_path.open("rb") as f:
            def _read(data: bytes) -> None:
                nonlocal uploaded, last_log_time
                uploaded += len(data)
                now = time.time()
                
                # Log progress every 10 seconds
                if now - last_log_time > 10:
                    if size > 0:
                        percent = (uploaded / size * 100)
                        log.info("ftp: upload progress %s: %.1f%% (%d/%d)", remote_path, percent, uploaded, size)
                    else:
                        log.info("ftp: upload progress %s: %d bytes", uploaded)
                    last_log_time = now

            # Use a large blocksize (1MB) for faster transfers of large files
            self.ftp.storbinary(f"STOR {remote_path}", f, callback=_read, blocksize=1024*1024)
        
        log.info("ftp: upload finished %s (%d bytes)", remote_path, uploaded)
        return uploaded

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
            # For large files, rename on some FTP servers can take a long time
            # and might time out the control connection.
            try:
                self.ftp.voidcmd("NOOP")
            except Exception:
                self.close()
                self.connect()
            self.ftp.rename(src, dst)
        except ftplib.error_perm as e:
            if "cross-device" in str(e).lower() or "550" in str(e):
                # Try copy-delete fallback
                log.info("ftp: cross-device detected (550), falling back to copy+delete for %s", src)
                self.copy(src, dst)
                self.delete(src)
                return
            raise
        except Exception as e:
            err_str = str(e).lower()
            if "timed out" in err_str or "timeout" in err_str:
                # If rename timed out, it might be because the server is doing a slow move.
                # Fall back to copy+delete which is more robust for large files.
                log.warning("ftp: rename timed out for %s, falling back to copy+delete", src)
                try:
                    self.close()
                    self.connect()
                    self.copy(src, dst)
                    self.delete(src)
                    return
                except Exception as ce:
                    raise RuntimeError(f"fallback copy failed after rename timeout: {ce}") from ce
            
            # Reconnect and retry rename once if other exception (e.g. broken pipe)
            log.info("ftp: rename failed (%s), retrying after reconnect", e)
            self.close()
            self.connect()
            try:
                self.ftp.rename(src, dst)
            except Exception as e2:
                # If it fails again, try copy fallback as last resort if it looks like a timeout or 550
                if "550" in str(e2) or "timeout" in str(e2).lower():
                    self.copy(src, dst)
                    self.delete(src)
                    return
                raise

    def copy(self, src: str, dst: str) -> None:
        """Stream copy from src to dst using two connections and a memory buffer."""
        import queue
        import threading
        
        log.info("ftp: direct streaming copy start %s -> %s", src, dst)
        
        # 32MB buffer (32 blocks of 1MB)
        q = queue.Queue(maxsize=32)
        error_event = threading.Event()
        error_msg = []
        
        # We need to capture the current connection params
        host, port, user, pwd, timeout = self._host, self._port, self._username, self._password, self._timeout
        
        # Try to get file size for progress reporting
        total_size = 0
        try:
            sz = self.stat(src)
            if sz and sz.size:
                total_size = sz.size
        except Exception:
            pass

        def produce():
            processed = 0
            last_log = time.time()
            try:
                # Use a fresh connection for reading to avoid control connection interference
                with FtpMcp(host, port, user, pwd, timeout=timeout) as reader:
                    def _callback(data):
                        nonlocal processed, last_log
                        if error_event.is_set():
                            raise RuntimeError("aborting producer due to consumer error")
                        q.put(data)
                        processed += len(data)
                        now = time.time()
                        if now - last_log > 10:
                            if total_size > 0:
                                log.info("ftp: streaming copy progress %s: %.1f%% (%d/%d)", src, (processed/total_size*100), processed, total_size)
                            else:
                                log.info("ftp: streaming copy progress %s: %d bytes", src, processed)
                            last_log = now
                    reader.ftp.retrbinary(f"RETR {src}", _callback, blocksize=1024*1024)
                q.put(None) # Sentinel
            except Exception as e:
                error_event.set()
                error_msg.append(f"producer error: {e}")
                q.put(None)

        def consume():
            try:
                # Use a fresh connection for writing
                with FtpMcp(host, port, user, pwd, timeout=timeout) as writer:
                    writer.ensure_dir(posixpath.dirname(dst))
                    
                    # ftplib storbinary expects a file-like object with a read(size) method
                    class StreamFile:
                        def __init__(self, queue):
                            self.queue = queue
                            self.buffer = b""
                        def read(self, size: int = -1) -> bytes:
                            if error_event.is_set():
                                return b""
                            if not self.buffer:
                                try:
                                    data = self.queue.get(timeout=10.0)
                                except queue.Empty:
                                    if error_event.is_set(): return b""
                                    return b"" # Should not happen if producer is alive
                                if data is None:
                                    return b""
                                self.buffer = data
                            
                            # Return up to 'size' bytes
                            if size < 0:
                                res = self.buffer
                                self.buffer = b""
                            else:
                                res = self.buffer[:size]
                                self.buffer = self.buffer[size:]
                            return res
                    
                    writer.ftp.storbinary(f"STOR {dst}", StreamFile(q), blocksize=1024*1024)
            except Exception as e:
                error_event.set()
                error_msg.append(f"consumer error: {e}")
                # Drain queue to let producer finish
                while True:
                    try:
                        if q.get(timeout=0.1) is None:
                            break
                    except queue.Empty:
                        if error_event.is_set(): break

        t1 = threading.Thread(target=produce, name="FtpStreamProducer")
        t2 = threading.Thread(target=consume, name="FtpStreamConsumer")
        t1.daemon = True
        t2.daemon = True
        t1.start()
        t2.start()
        
        # Wait for threads to finish
        while t1.is_alive() or t2.is_alive():
            t1.join(1.0)
            t2.join(1.0)

        if error_event.is_set():
            raise RuntimeError(f"streaming copy failed: {' | '.join(error_msg)}")
        
        log.info("ftp: direct streaming copy done %s", dst)

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
