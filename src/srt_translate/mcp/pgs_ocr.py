from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from ..pgs_bootstrap import resolve_pgsrip_command
from ..subtitle_quality import validate_srt_diversity


def _normalize_lang_code(code: str | None) -> str:
    c = (code or "").strip().strip(".").lower()
    if not c:
        return "und"
    mapping = {
        "eng": "en",
        "en-us": "en-us",
        "en-gb": "en-gb",
        "fre": "fr",
        "fra": "fr",
        "ger": "de",
        "deu": "de",
        "spa": "es",
        "ita": "it",
        "por": "pt",
        "zho": "zh",
        "chi": "zh",
        "jpn": "ja",
        "kor": "ko",
        "rus": "ru",
    }
    return mapping.get(c, c)


def _normalize_sup_filename(name: str) -> str:
    p = Path(name)
    if p.suffix.lower() != ".sup":
        return name
    stem = p.stem
    if "." not in stem:
        return f"{stem}.und.sup"
    base, _, lang = stem.rpartition(".")
    return f"{base}.{_normalize_lang_code(lang)}.sup"


def _safe_tmp_sup_name(normalized_name: str) -> str:
    p = Path(normalized_name)
    if p.suffix.lower() != ".sup":
        return "subtitle.und.sup"
    stem = p.stem
    if "." not in stem:
        return "subtitle.und.sup"
    _base, _, lang = stem.rpartition(".")
    return f"subtitle.{_normalize_lang_code(lang)}.sup"


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

    def extract_track_to_sup(self, video_path: Path, stream_index: int, out_sup_path: Path) -> Path:
        out_sup_path.parent.mkdir(parents=True, exist_ok=True)
        self._extract_sup(video_path, stream_index, out_sup_path)
        return out_sup_path

    def sup_to_srt(self, sup_path: Path, out_srt_path: Path) -> Path:
        out_srt_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_name = _normalize_sup_filename(sup_path.name)
        tmp_name = _safe_tmp_sup_name(normalized_name)
        if self._keep_temp_files:
            work_dir = out_srt_path.parent / f".pgs_ocr_{sup_path.stem}"
            work_dir.mkdir(parents=True, exist_ok=True)
            tmp_sup = work_dir / tmp_name
            tmp_sup.write_bytes(sup_path.read_bytes())
            srts = self._run_pgsrip(work_dir=work_dir, sup_path=tmp_sup)
            out_srt_path.write_bytes(srts[0].read_bytes())
        else:
            with tempfile.TemporaryDirectory(prefix="srt_translate_pgs_ocr_") as td:
                work_dir = Path(td)
                tmp_sup = work_dir / tmp_name
                tmp_sup.write_bytes(sup_path.read_bytes())
                srts = self._run_pgsrip(work_dir=work_dir, sup_path=tmp_sup)
                out_srt_path.write_bytes(srts[0].read_bytes())

        ok, reason = validate_srt_diversity(out_srt_path.read_text(encoding="utf-8", errors="replace"))
        if not ok:
            raise RuntimeError(f"pgs ocr produced low-quality srt: {reason}")
        return out_srt_path

    def _run_pgsrip(self, work_dir: Path, sup_path: Path) -> list[Path]:
        if not sup_path.exists():
            raise RuntimeError(f"extracted sup missing: {sup_path}")

        def _run(extra_args: list[str]) -> tuple[int, str]:
            cmd = list(resolve_pgsrip_command(cache_dir=self._cache_dir, auto_install=self._auto_install))
            cmd += extra_args
            cmd.append(str(sup_path))
            env = os.environ.copy()
            p = subprocess.run(
                cmd,
                cwd=str(work_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                env=env,
            )
            out = ((p.stderr or "") + "\n" + (p.stdout or "")).strip()
            return p.returncode, out

        base_args: list[str] = []
        for lang in self._languages:
            if lang:
                base_args += ["--language", str(lang)]
        base_args += ["--tag", "default"]
        if self._keep_temp_files:
            base_args += ["--keep-temp-files"]

        rc, out = _run(base_args)
        if rc != 0:
            raise RuntimeError(f"pgsrip failed: {out[:2000] or f'exit={rc}'}")

        srts = sorted(work_dir.glob("*.srt"), key=lambda x: x.stat().st_size, reverse=True)
        if srts:
            return srts

        if "filtered out" in out and base_args:
            rc2, out2 = _run(["--verbose"])
            srts2 = sorted(work_dir.glob("*.srt"), key=lambda x: x.stat().st_size, reverse=True)
            if srts2:
                return srts2
            out = (out + "\n\nRETRY_OUTPUT:\n" + out2).strip()

        raise RuntimeError(f"pgsrip produced no srt. output={out[:2000]}")

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
        if not sup_path.exists():
            raise RuntimeError("ffmpeg extract returned success but sup file is missing")
        if sup_path.stat().st_size <= 0:
            raise RuntimeError("ffmpeg extracted sup is empty")

    def _persist_failure_artifacts(self, out_srt_path: Path, sup_path: Path) -> Path:
        base = self._cache_dir / "work" / "pgs_ocr_failures"
        base.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        d = base / f"{out_srt_path.stem}.{ts}"
        d.mkdir(parents=True, exist_ok=True)
        try:
            (d / sup_path.name).write_bytes(sup_path.read_bytes())
        except Exception:
            pass
        return d
