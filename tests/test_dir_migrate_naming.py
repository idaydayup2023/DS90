import unittest
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dir_migrate.domain import LlmFields
from dir_migrate.naming import build_normalized_basename, subtitle_suffix


class TestDirMigrateNaming(unittest.TestCase):
    def test_movie_basename(self):
        f = LlmFields(
            kind="movie",
            title="Dune: Part Two",
            series=None,
            franchise_root=None,
            year=2024,
            season=None,
            episode=None,
            episode_title=None,
            resolution="2160p",
            source="WEB-DL",
            codec="HEVC",
            audio="Atmos",
            group="FLUX",
            video_tags=None,
            confidence=0.9,
        )
        name = build_normalized_basename(f, "Dune.Part.Two.2024.2160p")
        self.assertIn("Dune.Part.Two.2024.2160p", name)
        self.assertTrue(name.endswith("Atmos-FLUX"))

    def test_tv_basename_includes_season_episode(self):
        f = LlmFields(
            kind="tv",
            title=None,
            series="NCIS: Miami",
            franchise_root="NCIS",
            year=None,
            season=2,
            episode=1,
            episode_title=None,
            resolution="1080p",
            source="WEB-DL",
            codec="H264",
            audio="AAC",
            group="Group",
            video_tags=None,
            confidence=0.9,
        )
        name = build_normalized_basename(f, "NCIS.Miami.S02E01")
        self.assertIn("NCIS.Miami.S02E01", name)

    def test_movie_with_video_tags(self):
        f = LlmFields(
            kind="movie",
            title="Greenland: Migration",
            series=None,
            franchise_root=None,
            year=2026,
            season=None,
            episode=None,
            episode_title=None,
            resolution="2160p",
            source="AMZN.WEB-DL",
            codec="HEVC",
            audio="Atmos",
            group="Ben The Men",
            video_tags="DV.HDR10+",
            confidence=0.9,
        )
        name = build_normalized_basename(f, "Greenland.2.Migration.2026.2160p.AMZN.WEB-DL.DV.HDR10+[Ben The Men]")
        self.assertIn("DV.HDR10+", name)
        self.assertIn("AMZN.WEB-DL", name)
        self.assertTrue(name.endswith("-Ben.The.Men"))

    def test_subtitle_suffix(self):
        self.assertEqual(subtitle_suffix("Movie", "Movie"), "")
        self.assertEqual(subtitle_suffix("Movie", "Movie.en"), ".en")

