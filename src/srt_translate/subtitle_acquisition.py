from __future__ import annotations

import logging
import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domain import split_basename, subtitle_remote_paths
from .mcp.ftp import FtpMcp
from .mcp.media import MediaMcp, SubtitleTrack
from .mcp.pgs_ocr import PgsOcrMcp
from .subtitle_quality import SubtitleQuality, score_srt_content, validate_srt_diversity


log = logging.getLogger("srt_translate.subtitle_acquisition")


@dataclass(frozen=True)
class SubtitleSource:
    kind: str
    remote_path: str
    local_path: Path
    quality: SubtitleQuality | None
    meta: dict[str, Any]


def _is_english_track(t: SubtitleTrack) -> bool:
    if t.lang and t.lang.lower() in ("eng", "en"):
        return True
    title = (t.title or "").lower()
    return "english" in title or title.startswith("eng")


def _track_rank(t: SubtitleTrack) -> tuple[int, int, int, int]:
    sdh = 1 if "sdh" in (t.title or "").lower() or "hi" in (t.title or "").lower() else 0
    return (
        0 if t.is_text else 1,
        0 if t.is_default else 1,
        0 if not t.is_forced else 1,
        sdh,
    )


def _pick_best_english_track(tracks: list[SubtitleTrack]) -> SubtitleTrack | None:
    candidates = [t for t in tracks if _is_english_track(t) and t.is_text]
    if not candidates:
        return None
    candidates.sort(key=_track_rank)
    return candidates[0]


def _find_external_candidates(ftp: FtpMcp, video_remote_path: str) -> list[str]:
    directory, stem, _ = split_basename(video_remote_path)
    entries = ftp.list(directory)
    candidates: list[str] = []
    for e in entries:
        if e.type not in ("file",):
            continue
        name = posixpath.basename(e.path)
        lower = name.lower()
        if not lower.endswith(".srt"):
            continue
        if lower == f"{stem.lower()}.srt":
            candidates.append(e.path)
            continue
        if lower == f"{stem.lower()}.en.srt":
            candidates.append(e.path)
            continue
        if lower.startswith(stem.lower() + ".") and lower.endswith(".srt"):
            candidates.append(e.path)
            continue
    return candidates


def _score_remote_srt(ftp: FtpMcp, remote_path: str, local_path: Path) -> SubtitleQuality:
    ftp.download(remote_path, local_path)
    content = local_path.read_text(encoding="utf-8", errors="replace")
    return score_srt_content(content)


def choose_source_subtitle(
    ftp: FtpMcp,
    media: MediaMcp | None,
    pgs_ocr: PgsOcrMcp | None,
    cache_dir: Path,
    video_remote_path: str,
    local_video_path: Path | None,
    dry_run: bool,
) -> SubtitleSource | None:
    paths = subtitle_remote_paths(video_remote_path)

    emb_remote = paths["emb"]
    if ftp.exists(emb_remote):
        local = cache_dir / "subs" / Path(emb_remote).name
        ftp.download(emb_remote, local)
        q = score_srt_content(local.read_text(encoding="utf-8", errors="replace"))
        return SubtitleSource(kind="emb", remote_path=emb_remote, local_path=local, quality=q, meta={})

    candidates = _find_external_candidates(ftp, video_remote_path)
    if candidates:
        best_remote = None
        best_q: SubtitleQuality | None = None
        best_local: Path | None = None
        for rp in candidates:
            lp = cache_dir / "subs" / posixpath.basename(rp)
            q = _score_remote_srt(ftp, rp, lp)
            if best_q is None or q.score > best_q.score:
                best_q = q
                best_remote = rp
                best_local = lp
        if best_remote and best_local:
            return SubtitleSource(kind="external", remote_path=best_remote, local_path=best_local, quality=best_q, meta={})

    if media is not None and local_video_path is not None:
        tracks = media.probe_subtitles(local_video_path)
        candidates = [t for t in tracks if _is_english_track(t) and t.is_text]
        candidates.sort(key=_track_rank)
        candidates = candidates[:3]
        best_local: Path | None = None
        best_q: SubtitleQuality | None = None
        best_track: SubtitleTrack | None = None
        for t in candidates:
            local_try = cache_dir / "subs" / f"{Path(emb_remote).name}.track{t.stream_index}.srt"
            try:
                media.extract_subtitle_track(local_video_path, t.stream_index, local_try)
                q = score_srt_content(local_try.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if best_q is None or q.score > best_q.score:
                best_q = q
                best_local = local_try
                best_track = t
        if best_local is not None and best_track is not None:
            local_final = cache_dir / "subs" / Path(emb_remote).name
            local_final.parent.mkdir(parents=True, exist_ok=True)
            local_final.write_bytes(best_local.read_bytes())
            if not dry_run:
                ftp.atomic_write_from_file(emb_remote, local_final)
            return SubtitleSource(
                kind="emb",
                remote_path=emb_remote,
                local_path=local_final,
                quality=best_q,
                meta={"track": best_track.stream_index, "lang": best_track.lang, "title": best_track.title, "codec": best_track.codec},
            )

        if pgs_ocr is not None:
            pgs_tracks = [t for t in tracks if _is_english_track(t) and media.is_pgs(t)]
            pgs_tracks.sort(key=_track_rank)
            if pgs_tracks:
                t = pgs_tracks[0]
                local_try = cache_dir / "subs" / f"{Path(emb_remote).name}.pgs.track{t.stream_index}.srt"
                try:
                    pgs_ocr.track_to_srt(
                        video_path=local_video_path,
                        stream_index=t.stream_index,
                        out_srt_path=local_try,
                        language_hint=t.lang or "en",
                    )
                    q = score_srt_content(local_try.read_text(encoding="utf-8", errors="replace"))
                except Exception as e:
                    log.warning("pgs ocr failed video=%s track=%s error=%s", video_remote_path, t.stream_index, e)
                    q = None
                if q is not None:
                    local_final = cache_dir / "subs" / Path(emb_remote).name
                    local_final.parent.mkdir(parents=True, exist_ok=True)
                    local_final.write_bytes(local_try.read_bytes())
                    if not dry_run:
                        ftp.atomic_write_from_file(emb_remote, local_final)
                    return SubtitleSource(
                        kind="emb",
                        remote_path=emb_remote,
                        local_path=local_final,
                        quality=q,
                        meta={"track": t.stream_index, "lang": t.lang, "title": t.title, "codec": t.codec, "ocr": True},
                    )

    asr_remote = paths["asr"]
    if ftp.exists(asr_remote):
        local = cache_dir / "subs" / Path(asr_remote).name
        ftp.download(asr_remote, local)
        content = local.read_text(encoding="utf-8", errors="replace")
        ok, reason = validate_srt_diversity(content)
        q = score_srt_content(content)
        if not ok:
            log.warning("ignore existing asr subtitle due to low diversity: %s (%s)", asr_remote, reason)
            return None
        return SubtitleSource(kind="asr", remote_path=asr_remote, local_path=local, quality=q, meta={"existing": True})

    return None
