from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path

from .locked_venv import locked_venv_is_current, sync_locked_venv, venv_python


log = logging.getLogger("srt_translate.pgs_bootstrap")

_lock = threading.Lock()
_ensured: bool = False
_result: tuple[bool, str | None] | None = None


def _venv_paths(cache_dir: Path) -> tuple[Path, Path, Path]:
    venv_dir = cache_dir / "tools" / "pgsrip_venv"
    py = venv_python(venv_dir)
    exe = venv_dir / ("Scripts/pgsrip.exe" if py.name == "python.exe" else "bin/pgsrip")
    return venv_dir, py, exe


def _ensure_tesseract() -> tuple[bool, str | None]:
    if shutil.which("tesseract"):
        return True, None
    return False, "tesseract not found; install the external component before enabling PGS OCR"


def ensure_pgsrip_available(cache_dir: Path, auto_install: bool) -> tuple[bool, str | None]:
    global _ensured, _result
    with _lock:
        if _ensured and _result is not None:
            return _result
        _ensured = True

        ok, err = _ensure_tesseract()
        if not ok:
            _result = (False, err)
            return _result

        venv_dir, venv_py, exe = _venv_paths(cache_dir)
        if locked_venv_is_current(venv_dir, "ocr.lock") and exe.exists():
            _result = (True, None)
            return _result
        if not auto_install:
            message = "pgsrip environment is missing or not synchronized with requirements/ocr.lock"
            _result = (False, message + "; run the documented locked install first")
            return _result
        log.warning("pgsrip environment is missing or stale, synchronizing requirements/ocr.lock")
        ok, err = sync_locked_venv(venv_dir, "ocr.lock", timeout=1200)
        if not ok:
            _result = (False, f"locked pgsrip install failed: {err}")
            return _result

        if exe.exists():
            _result = (True, None)
            return _result
        _result = (False, "pgsrip still not available after auto-install")
        return _result


def resolve_pgsrip_command(cache_dir: Path, auto_install: bool) -> tuple[str, ...]:
    ok, err = ensure_pgsrip_available(cache_dir=cache_dir, auto_install=auto_install)
    if not ok:
        raise RuntimeError(err or "pgsrip not available")
    _venv_dir, _venv_py, exe = _venv_paths(cache_dir)
    return (str(exe),)
