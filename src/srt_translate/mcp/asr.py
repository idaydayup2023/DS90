from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


class AsrMcp:
    def __init__(self, command: tuple[str, ...], language: str | None):
        self._command = command
        self._language = language

    def transcribe_to_srt(self, video_path: Path, out_srt_path: Path) -> Path:
        out_srt_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="srt_translate_whisper_") as td:
            out_dir = Path(td)
            cmd = list(self._command)
            cmd.append(str(video_path))
            cmd += ["--output_format", "srt", "--output_dir", str(out_dir)]
            if self._language:
                cmd += ["--language", self._language]
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if p.returncode != 0:
                raise RuntimeError(f"whisper failed: {p.stderr.strip()}")
            stem = video_path.stem
            produced = out_dir / f"{stem}.srt"
            if not produced.exists():
                srts = list(out_dir.glob("*.srt"))
                if not srts:
                    raise RuntimeError("whisper produced no srt")
                produced = srts[0]
            out_srt_path.write_bytes(produced.read_bytes())
        return out_srt_path

