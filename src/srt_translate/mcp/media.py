from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SubtitleTrack:
    stream_index: int
    lang: str | None
    title: str | None
    codec: str | None
    is_text: bool
    is_default: bool
    is_forced: bool


_TEXT_CODECS = {
    "subrip",
    "srt",
    "ass",
    "ssa",
    "webvtt",
    "mov_text",
    "text",
}


class MediaMcp:
    def __init__(self, ffprobe: str = "ffprobe", ffmpeg: str = "ffmpeg"):
        self._ffprobe = ffprobe
        self._ffmpeg = ffmpeg

    def probe_subtitles(self, video_path: Path) -> list[SubtitleTrack]:
        cmd = [
            self._ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            str(video_path),
        ]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=60)
        if p.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {p.stderr.strip()}")
        data = json.loads(p.stdout)
        tracks: list[SubtitleTrack] = []
        for s in data.get("streams", []):
            if s.get("codec_type") != "subtitle":
                continue
            tags = s.get("tags") or {}
            disp = s.get("disposition") or {}
            codec = s.get("codec_name")
            lang = tags.get("language")
            title = tags.get("title")
            tracks.append(
                SubtitleTrack(
                    stream_index=int(s.get("index")),
                    lang=str(lang) if lang else None,
                    title=str(title) if title else None,
                    codec=str(codec) if codec else None,
                    is_text=(str(codec).lower() in _TEXT_CODECS) if codec else False,
                    is_default=bool(disp.get("default", 0)),
                    is_forced=bool(disp.get("forced", 0)),
                )
            )
        return tracks

    def extract_subtitle_track(self, video_path: Path, stream_index: int, out_srt_path: Path) -> Path:
        out_srt_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self._ffmpeg,
            "-y",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-map",
            f"0:{stream_index}",
            str(out_srt_path),
        ]
        # Add timeout to prevent hanging
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=300)
        if p.returncode != 0:
            raise RuntimeError(f"ffmpeg extract subtitle failed: {p.stderr.strip()}")
        return out_srt_path

