from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class VideoFile:
    remote_path: str
    size_bytes: int | None
    mtime: int | None


def compute_video_id(v: VideoFile) -> str:
    h = hashlib.sha1()
    h.update(v.remote_path.encode("utf-8"))
    h.update(b"\0")
    h.update(str(v.size_bytes or "").encode("utf-8"))
    h.update(b"\0")
    h.update(str(v.mtime or "").encode("utf-8"))
    return h.hexdigest()


def split_basename(remote_path: str) -> tuple[str, str, str]:
    import posixpath

    directory = posixpath.dirname(remote_path)
    filename = posixpath.basename(remote_path)
    stem, ext = posixpath.splitext(filename)
    return directory, stem, ext


def subtitle_remote_paths(video_remote_path: str) -> dict[str, str]:
    import posixpath

    d, stem, _ = split_basename(video_remote_path)
    return {
        "emb": posixpath.join(d, f"{stem}.emb.srt"),
        "asr": posixpath.join(d, f"{stem}.asr.srt"),
        "ai": posixpath.join(d, f"{stem}.ai.srt"),
    }

