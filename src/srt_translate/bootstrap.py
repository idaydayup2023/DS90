from __future__ import annotations

import importlib.util
import logging
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from .config import WhisperConfig
from .locked_venv import locked_venv_is_current, sync_locked_venv, venv_python


log = logging.getLogger("srt_translate.bootstrap")

_WHISPER_MODULE = "whisper"
_ensured: bool = False
_ensure_result: tuple[bool, str | None] | None = None
_ensure_lock = threading.Lock()


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _run(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def _venv_paths(cache_dir: Path) -> tuple[Path, Path]:
    venv_dir = cache_dir / "tools" / "whisper_venv"
    py = venv_python(venv_dir)
    return venv_dir, py


def _venv_has_whisper(venv_python: Path) -> bool:
    if not venv_python.exists():
        return False
    code = "import whisper; print('ok')\n"
    rc, out, _err = _run([str(venv_python), "-c", code])
    return rc == 0 and out.strip() == "ok"


def _detect_torch_device(python: Path | None = None) -> str | None:
    if python is None and not _has_module("torch"):
        return None
    code = (
        "import torch\n"
        "dev='cpu'\n"
        "try:\n"
        "    if torch.cuda.is_available():\n"
        "        dev='cuda'\n"
        "    elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():\n"
        "        dev='mps'\n"
        "except Exception:\n"
        "    dev='cpu'\n"
        "print(dev)\n"
    )
    try:
        p = subprocess.run(
            [str(python or sys.executable), "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if p.returncode != 0:
        return None
    out = (p.stdout or "").strip().lower()
    return out if out in ("cuda", "mps", "cpu") else None


def resolve_whisper_device(cfg: WhisperConfig, cache_dir: Path | None = None) -> str:
    pref = (cfg.device or "auto").strip().lower()
    if pref in ("cuda", "mps", "cpu"):
        return pref
    python: Path | None = None
    if cache_dir is not None:
        venv_dir, venv_py = _venv_paths(cache_dir)
        if locked_venv_is_current(venv_dir, "asr.lock"):
            python = venv_py
    detected = _detect_torch_device(python)
    return detected or "cpu"


def resolve_whisper_command(cfg: WhisperConfig, cache_dir: Path) -> tuple[str, ...]:
    ok, err = ensure_whisper_available(cfg, cache_dir=cache_dir)
    if not ok:
        raise RuntimeError(err or "whisper is not available")
    venv_dir, venv_py = _venv_paths(cache_dir)
    if _venv_has_whisper(venv_py):
        return (str(venv_py), "-m", _WHISPER_MODULE)
    if cfg.command and shutil.which(cfg.command[0]):
        return cfg.command
    return cfg.command


def ensure_whisper_available(cfg: WhisperConfig, cache_dir: Path) -> tuple[bool, str | None]:
    global _ensured, _ensure_result
    with _ensure_lock:
        if _ensured and _ensure_result is not None:
            return _ensure_result
        _ensured = True

        if not cfg.enabled:
            _ensure_result = (True, None)
            return _ensure_result

        venv_dir, venv_py = _venv_paths(cache_dir)
        if locked_venv_is_current(venv_dir, "asr.lock") and _venv_has_whisper(venv_py):
            _ensure_result = (True, None)
            return _ensure_result

        if cfg.command and shutil.which(cfg.command[0]):
            _ensure_result = (True, None)
            return _ensure_result

        if not cfg.auto_install:
            if venv_py.exists():
                message = "whisper environment is not synchronized with requirements/asr.lock"
            else:
                message = f"whisper not found: {cfg.command[0] if cfg.command else 'whisper'}"
            _ensure_result = (False, message + "; run the documented locked install first")
            return _ensure_result

        log.warning("whisper not found or stale, synchronizing requirements/asr.lock")
        ok, err = sync_locked_venv(venv_dir, "asr.lock", timeout=1800)
        if not ok:
            _ensure_result = (False, f"locked whisper install failed: {err}")
            return _ensure_result

        if _venv_has_whisper(venv_py):
            _ensure_result = (True, None)
            return _ensure_result

        _ensure_result = (False, "whisper still not available after auto-install")
        return _ensure_result
