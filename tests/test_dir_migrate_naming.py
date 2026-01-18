import unittest

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
            confidence=0.9,
        )
        name = build_normalized_basename(f, "NCIS.Miami.S02E01")
        self.assertIn("NCIS.Miami.S02E01", name)

    def test_subtitle_suffix(self):
        self.assertEqual(subtitle_suffix("Movie", "Movie"), "")
        self.assertEqual(subtitle_suffix("Movie", "Movie.en"), ".en")

