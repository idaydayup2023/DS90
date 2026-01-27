from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class VideoInfo:
    stream_index: int
    codec: str | None
    width: int | None
    height: int | None

    @property
    def resolution_label(self) -> str | None:
        """Return standardized resolution label (2160p, 1080p, 720p)."""
        if not self.width or not self.height:
            return None
        # Logic based on height usually
        h = self.height
        if h >= 2000: return "2160p"
        if h >= 1000: return "1080p"
        if h >= 700: return "720p"
        if h >= 480: return "480p"
        return f"{h}p"


@dataclass(frozen=True)
class AudioInfo:
    stream_index: int
    codec: str | None
    channels: int | None
    lang: str | None
    is_default: bool


@dataclass(frozen=True)
class MediaInfo:
    video: VideoInfo | None = None
    audio: list[AudioInfo] = field(default_factory=list)
    subtitles: list[SubtitleTrack] = field(default_factory=list)
    duration: float | None = None


_TEXT_CODECS = {
    "subrip",
    "srt",
    "ass",
    "ssa",
    "webvtt",
    "mov_text",
    "text",
}

_PGS_CODECS = {
    "hdmv_pgs_subtitle",
    "pgs",
}


class MediaMcp:
    def __init__(self, ffprobe: str = "ffprobe", ffmpeg: str = "ffmpeg"):
        self._ffprobe = ffprobe
        self._ffmpeg = ffmpeg

    def _probe_json(self, video_path: Path) -> dict:
        cmd = [
            self._ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(video_path),
        ]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=60)
        if p.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {p.stderr.strip()}")
        return json.loads(p.stdout)

    def probe_subtitles(self, video_path: Path) -> list[SubtitleTrack]:
        # Legacy method kept for compatibility, now delegates to _probe_json
        data = self._probe_json(video_path)
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

    def probe_media_info(self, video_path: Path) -> MediaInfo:
        data = self._probe_json(video_path)
        
        video_info = None
        audio_tracks = []
        subtitle_tracks = []
        
        fmt = data.get("format", {})
        duration = None
        if "duration" in fmt:
            try:
                duration = float(fmt["duration"])
            except (ValueError, TypeError):
                pass

        for s in data.get("streams", []):
            codec_type = s.get("codec_type")
            tags = s.get("tags") or {}
            disp = s.get("disposition") or {}
            codec = s.get("codec_name")
            idx = int(s.get("index"))
            
            if codec_type == "video":
                # Only pick the first video stream as the main video
                if video_info is None:
                    video_info = VideoInfo(
                        stream_index=idx,
                        codec=str(codec) if codec else None,
                        width=int(s.get("width")) if s.get("width") else None,
                        height=int(s.get("height")) if s.get("height") else None,
                    )
            
            elif codec_type == "audio":
                audio_tracks.append(AudioInfo(
                    stream_index=idx,
                    codec=str(codec) if codec else None,
                    channels=int(s.get("channels")) if s.get("channels") else None,
                    lang=tags.get("language"),
                    is_default=bool(disp.get("default", 0)),
                ))
                
            elif codec_type == "subtitle":
                lang = tags.get("language")
                title = tags.get("title")
                subtitle_tracks.append(
                    SubtitleTrack(
                        stream_index=idx,
                        lang=str(lang) if lang else None,
                        title=str(title) if title else None,
                        codec=str(codec) if codec else None,
                        is_text=(str(codec).lower() in _TEXT_CODECS) if codec else False,
                        is_default=bool(disp.get("default", 0)),
                        is_forced=bool(disp.get("forced", 0)),
                    )
                )
        
        return MediaInfo(
            video=video_info,
            audio=audio_tracks,
            subtitles=subtitle_tracks,
            duration=duration
        )

    @staticmethod
    def is_pgs(track: SubtitleTrack) -> bool:
        if not track.codec:
            return False
        return track.codec.lower() in _PGS_CODECS

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
