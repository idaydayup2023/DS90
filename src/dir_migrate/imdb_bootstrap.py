from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path


log = logging.getLogger("dir_migrate.imdb_bootstrap")

_lock = threading.Lock()
_ensured: bool = False
_result: tuple[bool, str | None] | None = None


def _run(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def _venv_paths(cache_dir: Path) -> tuple[Path, Path]:
    venv_dir = cache_dir / "tools" / "imdb_venv"
    py = venv_dir / "bin" / "python"
    return venv_dir, py


def ensure_imdbpy_available(cache_dir: Path, auto_install: bool) -> tuple[bool, str | None]:
    global _ensured, _result
    with _lock:
        if _ensured and _result is not None:
            return _result
        _ensured = True

        venv_dir, venv_py = _venv_paths(cache_dir)
        if venv_py.exists():
            _result = (True, None)
            return _result
        if not auto_install:
            _result = (False, "imdbpy not installed")
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
            rc, out, err = _run([str(venv_py), "-m", "pip", "install", "imdbpy"], timeout=900)
            if rc != 0:
                _result = (False, err.strip() or out.strip() or "pip install imdbpy failed")
                return _result
        except Exception as e:
            _result = (False, str(e))
            return _result
        if venv_py.exists():
            _result = (True, None)
            return _result
        _result = (False, "imdbpy still not available after auto-install")
        return _result


def resolve_imdbpy_python(cache_dir: Path, auto_install: bool) -> str:
    ok, err = ensure_imdbpy_available(cache_dir=cache_dir, auto_install=auto_install)
    if not ok:
        raise RuntimeError(err or "imdbpy not available")
    _venv_dir, py = _venv_paths(cache_dir)
    return str(py)

