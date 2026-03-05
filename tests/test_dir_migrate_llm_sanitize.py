import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dir_migrate.domain import LlmFields
from dir_migrate.mcp.llm import _fallback_from_filename, _sanitize_fields


class TestDirMigrateLlmSanitize(unittest.TestCase):
    def test_tv_series_drops_episode_tail(self):
        filename = "Tehran.S03E02.Friend.or.Foe.1080p.x265-ELiTE.mkv"
        fallback = _fallback_from_filename(filename)
        fields = LlmFields(
            kind="tv",
            title=None,
            series="Tehran.S03E02.Friend.or.Foe",
            franchise_root=None,
            year=None,
            season=3,
            episode=2,
            episode_title="Friend or Foe",
            resolution="1080p",
            source=None,
            codec="x265",
            audio=None,
            group="ELiTE",
            video_tags=None,
            confidence=0.9,
        )
        sanitized = _sanitize_fields(filename, fields, fallback)
        self.assertEqual("Tehran", sanitized.series)


if __name__ == "__main__":
    unittest.main()
