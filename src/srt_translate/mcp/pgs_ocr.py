from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from ..pgs_bootstrap import resolve_pgsrip_command
from ..subtitle_quality import validate_srt_diversity


class PgsOcrMcp:
    def __init__(
        self,
        cache_dir: Path,
        auto_install: bool,
        languages: tuple[str, ...],
        keep_temp_files: bool,
        ffmpeg: str = "ffmpeg",
    ):
        self._cache_dir = cache_dir
        self._auto_install = auto_install
        self._languages = languages
        self._keep_temp_files = keep_temp_files
        self._ffmpeg = ffmpeg

    def track_to_srt(
        self,
        video_path: Path,
        stream_index: int,
        out_srt_path: Path,
    ) -> Path:
        out_srt_path.parent.mkdir(parents=True, exist_ok=True)
        if self._keep_temp_files:
            work_dir = out_srt_path.parent / f".pgs_ocr_track{stream_index}"
            work_dir.mkdir(parents=True, exist_ok=True)
            sup = work_dir / "subtitle.sup"
            self._extract_sup(video_path, stream_index, sup)
            srts = self._run_pgsrip(work_dir=work_dir, sup_path=sup)
            out_srt_path.write_bytes(srts[0].read_bytes())
        else:
            with tempfile.TemporaryDirectory(prefix="srt_translate_pgs_ocr_") as td:
                work_dir = Path(td)
                sup = work_dir / "subtitle.sup"
                self._extract_sup(video_path, stream_index, sup)
                srts = self._run_pgsrip(work_dir=work_dir, sup_path=sup)
                out_srt_path.write_bytes(srts[0].read_bytes())

        ok, reason = validate_srt_diversity(out_srt_path.read_text(encoding="utf-8", errors="replace"))
        if not ok:
            raise RuntimeError(f"pgs ocr produced low-quality srt: {reason}")
        return out_srt_path

    def _run_pgsrip(self, work_dir: Path, sup_path: Path) -> list[Path]:
        cmd = list(resolve_pgsrip_command(cache_dir=self._cache_dir, auto_install=self._auto_install))
        for lang in self._languages:
            if lang:
                cmd += ["--language", str(lang)]
        if self._keep_temp_files:
            cmd += ["--keep-temp-files"]
        cmd.append(str(sup_path))
        env = os.environ.copy()
        p = subprocess.run(
            cmd,
            cwd=str(work_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            env=env,
        )
        if p.returncode != 0:
            msg = (p.stderr or p.stdout or "").strip() or f"exit={p.returncode}"
            raise RuntimeError(f"pgsrip failed: {msg}")

        srts = sorted(work_dir.glob("*.srt"), key=lambda x: x.stat().st_size, reverse=True)
        if not srts:
            detail = ((p.stderr or "") + "\n" + (p.stdout or "")).strip()
            raise RuntimeError(f"pgsrip produced no srt. output={detail[:2000]}")
        return srts

    def _extract_sup(self, video_path: Path, stream_index: int, sup_path: Path) -> None:
        cmd = [
            self._ffmpeg,
            "-y",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-map",
            f"0:{stream_index}",
            "-c:s",
            "copy",
            str(sup_path),
        ]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=300)
        if p.returncode != 0:
            raise RuntimeError(f"ffmpeg extract pgs failed: {(p.stderr or '').strip()}")
