from __future__ import annotations

import importlib.util
import logging
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Final

from .config import WhisperConfig


log = logging.getLogger("srt_translate.bootstrap")

_DEFAULT_PIP_PACKAGE: Final[str] = "openai-whisper"
_WHISPER_MODULE: Final[str] = "whisper"
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
    py = venv_dir / "bin" / "python"
    return venv_dir, py


def _venv_has_whisper(venv_python: Path) -> bool:
    if not venv_python.exists():
        return False
    code = "import whisper; print('ok')\n"
    rc, out, _err = _run([str(venv_python), "-c", code])
    return rc == 0 and out.strip() == "ok"


def _detect_torch_device() -> str | None:
    if not _has_module("torch"):
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
            [sys.executable, "-c", code],
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


def resolve_whisper_device(cfg: WhisperConfig) -> str:
    pref = (cfg.device or "auto").strip().lower()
    if pref in ("cuda", "mps", "cpu"):
        return pref
    detected = _detect_torch_device()
    return detected or "cpu"


def resolve_whisper_command(cfg: WhisperConfig, cache_dir: Path) -> tuple[str, ...]:
    ok, err = ensure_whisper_available(cfg, cache_dir=cache_dir)
    if not ok:
        raise RuntimeError(err or "whisper is not available")
    if _has_module(_WHISPER_MODULE):
        return (sys.executable, "-m", _WHISPER_MODULE)
    venv_dir, venv_py = _venv_paths(cache_dir)
    if _venv_has_whisper(venv_py):
        return (str(venv_py), "-m", _WHISPER_MODULE)
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

        if cfg.command and shutil.which(cfg.command[0]):
            _ensure_result = (True, None)
            return _ensure_result

        if _has_module(_WHISPER_MODULE):
            _ensure_result = (True, None)
            return _ensure_result

        venv_dir, venv_py = _venv_paths(cache_dir)
        if _venv_has_whisper(venv_py):
            _ensure_result = (True, None)
            return _ensure_result

        if not cfg.auto_install:
            _ensure_result = (False, f"whisper not found: {cfg.command[0] if cfg.command else 'whisper'}")
            return _ensure_result

        try:
            log.warning("whisper command not found, attempting pip install: %s", _DEFAULT_PIP_PACKAGE)
            rc, out, err = _run([sys.executable, "-m", "pip", "install", "-U", _DEFAULT_PIP_PACKAGE])
            if rc != 0:
                if "externally-managed-environment" in err.lower():
                    venv_dir.mkdir(parents=True, exist_ok=True)
                    rc2, _out2, err2 = _run([sys.executable, "-m", "venv", str(venv_dir)])
                    if rc2 != 0:
                        _ensure_result = (False, f"auto-install failed: {err2.strip() or err.strip() or out.strip()}")
                        return _ensure_result
                    rc3, out3, err3 = _run([str(venv_py), "-m", "pip", "install", "-U", _DEFAULT_PIP_PACKAGE])
                    if rc3 != 0:
                        _ensure_result = (False, f"auto-install failed: {err3.strip() or out3.strip()}")
                        return _ensure_result
                else:
                    _ensure_result = (False, f"auto-install failed: {err.strip() or out.strip()}")
                    return _ensure_result
        except Exception as e:
            _ensure_result = (False, f"auto-install failed: {e}")
            return _ensure_result

        if _has_module(_WHISPER_MODULE) or (cfg.command and shutil.which(cfg.command[0])) or _venv_has_whisper(venv_py):
            _ensure_result = (True, None)
            return _ensure_result

        _ensure_result = (False, "whisper still not available after auto-install")
        return _ensure_result
