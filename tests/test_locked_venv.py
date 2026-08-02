import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from srt_translate.locked_venv import (
    lock_path,
    locked_venv_is_current,
    project_root,
    sync_locked_venv,
    venv_python,
)


class TestLockedVenv(unittest.TestCase):
    def test_frozen_project_root_is_executable_directory(self):
        with (
            patch("srt_translate.locked_venv.sys.frozen", True, create=True),
            patch("srt_translate.locked_venv.sys.executable", "/Applications/DB90/db90-subtitles"),
        ):
            self.assertEqual(Path("/Applications/DB90"), project_root())

    def test_frozen_project_root_prefers_bundled_requirements(self):
        with tempfile.TemporaryDirectory() as td:
            bundled = Path(td)
            (bundled / "requirements").mkdir()
            with (
                patch("srt_translate.locked_venv.sys.frozen", True, create=True),
                patch("srt_translate.locked_venv.sys._MEIPASS", str(bundled), create=True),
                patch("srt_translate.locked_venv.sys.executable", "/Applications/DB90/db90"),
            ):
                self.assertEqual(bundled, project_root())

    def test_project_lock_files_exist(self):
        for name in ("asr.lock", "ocr.lock", "imdb.lock"):
            self.assertTrue(lock_path(name).is_file())

    def test_marker_must_match_lock_digest(self):
        path = lock_path("asr.lock")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            venv_dir = Path(td)
            py = venv_python(venv_dir)
            py.parent.mkdir(parents=True, exist_ok=True)
            py.touch()
            marker = venv_dir / ".db90-dependency-lock.json"
            marker.write_text(
                json.dumps({"lock": "asr.lock", "sha256": digest}),
                encoding="utf-8",
            )
            self.assertTrue(locked_venv_is_current(venv_dir, "asr.lock"))

            marker.write_text(
                json.dumps({"lock": "asr.lock", "sha256": "stale"}),
                encoding="utf-8",
            )
            self.assertFalse(locked_venv_is_current(venv_dir, "asr.lock"))

    def test_offline_install_rejects_missing_wheelhouse(self):
        with tempfile.TemporaryDirectory() as td:
            venv_dir = Path(td) / "venv"
            missing = Path(td) / "missing"
            py = venv_python(venv_dir)
            py.parent.mkdir(parents=True)
            py.touch()
            ok, error = sync_locked_venv(
                venv_dir,
                "imdb.lock",
                timeout=1,
                find_links=missing,
            )
        self.assertFalse(ok)
        self.assertIn("offline wheelhouse not found", error or "")


if __name__ == "__main__":
    unittest.main()
