import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_db90


class TestDb90Cli(unittest.TestCase):
    def test_help_lists_both_commands(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = run_db90.main(["--help"])
        self.assertEqual(0, result)
        self.assertIn("subtitles", output.getvalue())
        self.assertIn("migrate", output.getvalue())

    def test_subtitles_command_is_forwarded(self):
        with patch.object(run_db90, "subtitles_main", return_value=7) as command:
            result = run_db90.main(["subtitles", "--config", "config.json"])
        self.assertEqual(7, result)
        command.assert_called_once_with(["--config", "config.json"])

    def test_migrate_command_is_forwarded(self):
        with patch.object(run_db90, "migrate_main", return_value=8) as command:
            result = run_db90.main(["migrate", "--dry-run"])
        self.assertEqual(8, result)
        command.assert_called_once_with(["--dry-run"])


if __name__ == "__main__":
    unittest.main()
