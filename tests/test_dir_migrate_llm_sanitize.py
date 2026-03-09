import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dir_migrate.domain import LlmFields
from dir_migrate.mcp.llm import _fallback_from_filename, _sanitize_fields
from dir_migrate.naming import build_normalized_basename


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

    def test_4k_movie_never_generates_s00e00(self):
        filename = "War.Machine.2026.2160p.WEB-DL.HEVC.x265.5.1.BONE.mkv"
        fallback = _fallback_from_filename(filename)
        fields = LlmFields(
            kind="tv",
            title="War Machine",
            series="War Machine",
            franchise_root=None,
            year=2026,
            season=0,
            episode=0,
            episode_title=None,
            resolution="2160p",
            source="WEB-DL",
            codec="x265",
            audio="5.1",
            group="BONE",
            video_tags=None,
            confidence=0.8,
        )
        sanitized = _sanitize_fields(filename, fields, fallback)
        self.assertEqual("movie", sanitized.kind)
        self.assertIsNone(sanitized.season)
        self.assertIsNone(sanitized.episode)
        name = build_normalized_basename(sanitized, Path(filename).stem)
        self.assertNotIn("S00E00", name)

    def test_remove_eztvx_ad_tag_from_group(self):
        filename = "Show.Name.S01E01.1080p.WEB.h264.[EZTVx.to].mkv"
        fallback = _fallback_from_filename(filename)
        fields = LlmFields(
            kind="tv",
            title=None,
            series="Show Name",
            franchise_root=None,
            year=None,
            season=1,
            episode=1,
            episode_title=None,
            resolution="1080p",
            source="WEB",
            codec="h264",
            audio=None,
            group="EZTVx.to",
            video_tags=None,
            confidence=0.9,
        )
        sanitized = _sanitize_fields(filename, fields, fallback)
        name = build_normalized_basename(sanitized, Path(filename).stem)
        self.assertNotIn("EZTVx.to", name)
        self.assertNotIn("EZTVx", name)


if __name__ == "__main__":
    unittest.main()
