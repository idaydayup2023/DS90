from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from collections import Counter


def _validate_srt_quality(srt_path: Path) -> tuple[bool, str | None]:
    try:
        lines = srt_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as e:
        return False, str(e)

    text_lines: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.isdigit():
            continue
        if "-->" in s:
            continue
        text_lines.append(s)

    if not text_lines:
        return False, "empty transcription"

    lowered = [t.lower() for t in text_lines]
    c = Counter(lowered)
    most_common, most_n = c.most_common(1)[0]
    total = len(lowered)

    casting = sum(1 for t in lowered if "castingwords" in t)
    if total >= 10 and (most_n / total) >= 0.7:
        return False, f"repetitive transcription: {most_common!r} x{most_n}/{total}"
    if total >= 10 and (casting / total) >= 0.2:
        return False, f"likely hallucination/watermark: castingwords {casting}/{total}"
    return True, None


class AsrMcp:
    def __init__(
        self,
        command: tuple[str, ...],
        language: str | None,
        device: str | None,
        model: str | None,
        task: str | None,
        temperature: float | None,
        no_speech_threshold: float | None,
        fallback_models: tuple[str, ...] = (),
    ):
        self._command = command
        self._language = language
        self._device = device
        self._model = model
        self._task = task
        self._temperature = temperature
        self._no_speech_threshold = no_speech_threshold
        self._fallback_models = fallback_models

    def transcribe_to_srt(self, video_path: Path, out_srt_path: Path) -> Path:
        tried: list[str] = []
        models = [self._model] if self._model else []
        models += [m for m in self._fallback_models if m]
        if not models:
            models = [None]

        last_err: str | None = None
        for model in models:
            languages: list[str | None] = [self._language] if self._language else [None]
            if self._language is not None:
                languages.append(None)
            for lang in languages:
                tried.append(f"{model or 'default'}:{lang or 'auto'}")
                last_err = self._run_once(video_path, out_srt_path, model=model, language=lang)
                if last_err is None:
                    return out_srt_path

        raise RuntimeError(f"whisper failed ({' -> '.join(tried)}): {last_err or 'unknown error'}")

    def _run_once(self, video_path: Path, out_srt_path: Path, model: str | None, language: str | None) -> str | None:
        out_srt_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="srt_translate_whisper_") as td:
            out_dir = Path(td)
            cmd = list(self._command)
            cmd.append(str(video_path))
            cmd += ["--output_format", "srt", "--output_dir", str(out_dir)]
            if language:
                cmd += ["--language", language]
            if self._device:
                cmd += ["--device", self._device]
            if model:
                cmd += ["--model", model]
            if self._task:
                cmd += ["--task", self._task]
            if self._temperature is not None:
                cmd += ["--temperature", str(self._temperature)]
            if self._no_speech_threshold is not None:
                cmd += ["--no_speech_threshold", str(self._no_speech_threshold)]
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if p.returncode != 0:
                return p.stderr.strip() or p.stdout.strip() or f"exit={p.returncode}"
            stem = video_path.stem
            produced = out_dir / f"{stem}.srt"
            if not produced.exists():
                srts = list(out_dir.glob("*.srt"))
                if not srts:
                    return "whisper produced no srt"
                produced = srts[0]
            out_srt_path.write_bytes(produced.read_bytes())
        ok, reason = _validate_srt_quality(out_srt_path)
        if not ok:
            return reason or "quality check failed"
        return None
