from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


_MARKER_NAME = ".db90-dependency-lock.json"


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        bundled_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        if (bundled_root / "requirements").is_dir():
            return bundled_root
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def lock_path(lock_name: str) -> Path:
    path = project_root() / "requirements" / lock_name
    if not path.is_file():
        raise FileNotFoundError(f"dependency lock not found: {path}")
    return path


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _lock_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locked_venv_is_current(venv_dir: Path, lock_name: str) -> bool:
    py = venv_python(venv_dir)
    marker = venv_dir / _MARKER_NAME
    if not py.is_file() or not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        path = lock_path(lock_name)
    except (OSError, ValueError, TypeError):
        return False
    return payload == {"lock": lock_name, "sha256": _lock_digest(path)}


def sync_locked_venv(
    venv_dir: Path,
    lock_name: str,
    *,
    timeout: int,
    find_links: Path | None = None,
) -> tuple[bool, str | None]:
    try:
        path = lock_path(lock_name)
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        py = venv_python(venv_dir)
        if not py.is_file():
            created = subprocess.run(
                [sys.executable, "-m", "venv", str(venv_dir)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=180,
            )
            if created.returncode != 0:
                return False, (created.stderr or created.stdout or "venv creation failed").strip()

        install_command = [
            str(py),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--require-hashes",
        ]
        if find_links is not None:
            if not find_links.is_dir():
                return False, f"offline wheelhouse not found: {find_links}"
            install_command.extend(("--no-index", "--find-links", str(find_links)))
        install_command.extend(("-r", str(path)))

        installed = subprocess.run(
            install_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
        )
        if installed.returncode != 0:
            return False, (installed.stderr or installed.stdout or "locked dependency install failed").strip()

        checked = subprocess.run(
            [str(py), "-m", "pip", "check"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=120,
        )
        if checked.returncode != 0:
            return False, (checked.stderr or checked.stdout or "pip check failed").strip()

        marker = venv_dir / _MARKER_NAME
        marker.write_text(
            json.dumps({"lock": lock_name, "sha256": _lock_digest(path)}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return True, None
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
