import json
import tempfile
import unittest
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dir_migrate.config import load_config


class TestDirMigrateConfig(unittest.TestCase):
    def _write(self, obj) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = Path(td.name) / "cfg.json"
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return p

    def test_load_standalone_dir_migrate_config(self):
        cfg_path = self._write(
            {
                "source": {
                    "kind": "ftp",
                    "ftp": {"host": "h", "port": 21, "username": "u", "password": "p", "root_path": "/Downloads"},
                },
                "dest": {
                    "kind": "ftp",
                    "ftp": {"host": "h", "port": 21, "username": "u", "password": "p", "root_path": "/"},
                },
                "paths": {"local_cache_dir": ".cache/dir_migrate"},
                "video": {"extensions": [".mkv"], "min_bytes": 0},
                "subtitle": {"extensions": [".srt"]},
                "llm": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
                "rules": {},
                "execution": {"dry_run": True, "apply": False, "limit": 1, "workers": 1, "on_conflict": "skip"},
            }
        )
        cfg = load_config(cfg_path)
        self.assertEqual(cfg.source.kind, "ftp")
        self.assertEqual(cfg.source.ftp.root_path, "/Downloads")
        self.assertEqual(cfg.dest.ftp.root_path, "/")

    def test_load_merged_config_inherits_common_ftp(self):
        cfg_path = self._write(
            {
                "ftp": {"host": "h", "port": 21, "username": "u", "password": "p", "root_path": "/Downloads"},
                "paths": {"local_cache_dir": ".cache/srt_translate", "state_db_path": ".cache/srt_translate/state.sqlite3"},
                "video": {"extensions": [".mkv"], "min_bytes": 0},
                "ollama": {"base_url": "http://localhost:11434", "model": "m"},
                "whisper": {"enabled": False, "command": ["whisper"], "language": "en"},
                "translation": {"workers": 1, "batch_size": 10, "max_retries": 1},
                "dir_migrate": {
                    "source": {"kind": "ftp", "root_path": "/Downloads"},
                    "dest": {"kind": "ftp", "root_path": "/"},
                    "execution": {"dry_run": True, "apply": False, "limit": 1, "workers": 1, "on_conflict": "skip"},
                },
            }
        )
        cfg = load_config(cfg_path)
        self.assertEqual(cfg.source.ftp.host, "h")
        self.assertEqual(cfg.source.ftp.root_path, "/Downloads")
        self.assertEqual(cfg.dest.ftp.root_path, "/")

