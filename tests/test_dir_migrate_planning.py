import unittest
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dir_migrate.config import RulesConfig
from dir_migrate.domain import LlmFields
from dir_migrate.planning import dest_dir_for


class TestDirMigratePlanning(unittest.TestCase):
    def test_movie_1080_year_bucket(self):
        rules = RulesConfig(
            movie_1080_root="X-Movie",
            movie_4k_root="MOVIE",
            tv_1080_root="X-TV",
            tv_4k_root="TV",
            year_split=2024,
            franchise_map={},
        )
        f = LlmFields(
            kind="movie",
            title="The Thin Red Line",
            series=None,
            franchise_root=None,
            year=1998,
            season=None,
            episode=None,
            episode_title=None,
            resolution="1080p",
            source=None,
            codec=None,
            audio=None,
            group=None,
            confidence=None,
        )
        d = dest_dir_for(rules, f, "X")
        self.assertTrue(d.startswith("/X-Movie/1990s/"))

    def test_movie_4k_decade_bucket(self):
        rules = RulesConfig(
            movie_1080_root="X-Movie",
            movie_4k_root="MOVIE",
            tv_1080_root="X-TV",
            tv_4k_root="TV",
            year_split=2024,
            franchise_map={},
        )
        f = LlmFields(
            kind="movie",
            title="Dune",
            series=None,
            franchise_root=None,
            year=2024,
            season=None,
            episode=None,
            episode_title=None,
            resolution="2160p",
            source=None,
            codec=None,
            audio=None,
            group=None,
            confidence=None,
        )
        d = dest_dir_for(rules, f, "X")
        self.assertTrue(d.startswith("/MOVIE/2020s/"))

    def test_tv_includes_sxx(self):
        rules = RulesConfig(
            movie_1080_root="X-Movie",
            movie_4k_root="MOVIE",
            tv_1080_root="X-TV",
            tv_4k_root="TV",
            year_split=2024,
            franchise_map={},
        )
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
            source=None,
            codec=None,
            audio=None,
            group=None,
            confidence=None,
        )
        d = dest_dir_for(rules, f, "X")
        self.assertIn("/X-TV/NCIS/", d)
        self.assertTrue(d.endswith("/S02"))
