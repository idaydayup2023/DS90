import unittest
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dir_migrate.config import FtpConnConfig
from dir_migrate.mcp.storage import _ftp_abs


class TestDirMigrateFtpPaths(unittest.TestCase):
    def test_ftp_abs_joins_root_for_relative_path(self):
        cfg = FtpConnConfig(host="h", port=21, username="u", password="p", root_path="/Downloads", timeout_seconds=5)
        self.assertEqual(_ftp_abs(cfg, "A/B.mkv"), "/Downloads/A/B.mkv")

    def test_ftp_abs_keeps_absolute_when_root_is_slash(self):
        cfg = FtpConnConfig(host="h", port=21, username="u", password="p", root_path="/", timeout_seconds=5)
        self.assertEqual(_ftp_abs(cfg, "/X-Movie/2026/A.mkv"), "/X-Movie/2026/A.mkv")

    def test_ftp_abs_keeps_absolute_when_root_not_slash(self):
        cfg = FtpConnConfig(host="h", port=21, username="u", password="p", root_path="/Downloads", timeout_seconds=5)
        self.assertEqual(_ftp_abs(cfg, "/X-Movie/2026/A.mkv"), "/X-Movie/2026/A.mkv")

