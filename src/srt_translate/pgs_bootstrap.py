from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
from pathlib import Path


log = logging.getLogger("srt_translate.pgs_bootstrap")

_lock = threading.Lock()
_ensured: bool = False
_result: tuple[bool, str | None] | None = None


def _run(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=timeout)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def _venv_paths(cache_dir: Path) -> tuple[Path, Path, Path]:
    venv_dir = cache_dir / "tools" / "pgsrip_venv"
    py = venv_dir / "bin" / "python"
    exe = venv_dir / "bin" / "pgsrip"
    return venv_dir, py, exe


def _ensure_tesseract(auto_install: bool) -> tuple[bool, str | None]:
    if shutil.which("tesseract"):
        return True, None
    if not auto_install:
        return False, "tesseract not found"
    brew = shutil.which("brew")
    if not brew:
        return False, "tesseract not found and brew not available"
    try:
        log.warning("tesseract not found, attempting brew install tesseract")
        rc, out, err = _run([brew, "install", "tesseract"], timeout=3600)
        if rc != 0:
            return False, f"brew install tesseract failed: {err.strip() or out.strip()}"
    except Exception as e:
        return False, f"brew install tesseract failed: {e}"
    if shutil.which("tesseract"):
        return True, None
    return False, "tesseract still not available after brew install"


def ensure_pgsrip_available(cache_dir: Path, auto_install: bool) -> tuple[bool, str | None]:
    global _ensured, _result
    with _lock:
        if _ensured and _result is not None:
            return _result
        _ensured = True

        ok, err = _ensure_tesseract(auto_install=auto_install)
        if not ok:
            _result = (False, err)
            return _result

        venv_dir, venv_py, exe = _venv_paths(cache_dir)
        if exe.exists():
            _result = (True, None)
            return _result
        if not auto_install:
            _result = (False, "pgsrip not installed")
            return _result
        try:
            venv_dir.parent.mkdir(parents=True, exist_ok=True)
            rc, out, err = _run([sys.executable, "-m", "venv", str(venv_dir)], timeout=120)
            if rc != 0:
                _result = (False, err.strip() or out.strip() or "venv creation failed")
                return _result
            rc, out, err = _run([str(venv_py), "-m", "pip", "install", "-U", "pip"], timeout=300)
            if rc != 0:
                _result = (False, err.strip() or out.strip() or "pip upgrade failed")
                return _result
            rc, out, err = _run([str(venv_py), "-m", "pip", "install", "pgsrip"], timeout=600)
            if rc != 0:
                _result = (False, err.strip() or out.strip() or "pip install pgsrip failed")
                return _result
        except Exception as e:
            _result = (False, str(e))
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

