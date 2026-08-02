from __future__ import annotations

import logging
import threading
from pathlib import Path

from srt_translate.locked_venv import locked_venv_is_current, sync_locked_venv, venv_python


log = logging.getLogger("dir_migrate.imdb_bootstrap")

_lock = threading.Lock()
_ensured: bool = False
_result: tuple[bool, str | None] | None = None


def _venv_paths(cache_dir: Path) -> tuple[Path, Path]:
    venv_dir = cache_dir / "tools" / "imdb_venv"
    py = venv_python(venv_dir)
    return venv_dir, py


def ensure_imdbpy_available(cache_dir: Path, auto_install: bool) -> tuple[bool, str | None]:
    global _ensured, _result
    with _lock:
        if _ensured and _result is not None:
            return _result
        _ensured = True

        venv_dir, venv_py = _venv_paths(cache_dir)
        if locked_venv_is_current(venv_dir, "imdb.lock") and venv_py.exists():
            _result = (True, None)
            return _result
        if not auto_install:
            message = "Cinemagoer environment is missing or not synchronized with requirements/imdb.lock"
            _result = (False, message + "; run the documented locked install first")
            return _result
        log.warning("Cinemagoer environment is missing or stale, synchronizing requirements/imdb.lock")
        ok, err = sync_locked_venv(venv_dir, "imdb.lock", timeout=1200)
        if not ok:
            _result = (False, f"locked Cinemagoer install failed: {err}")
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
