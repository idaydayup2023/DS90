import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dir_migrate.classification import classify_media, sidecar_media_kind
from dir_migrate.agents.planner import plan_one
from dir_migrate.config import (
    AppConfig,
    CleanupConfig,
    ExecutionConfig,
    ImdbConfig,
    LlmConfig,
    PathsConfig,
    RulesConfig,
    StorageConfig,
    SubtitleConfig,
    VideoConfig,
)
from dir_migrate.domain import LlmFields, SourceFiles
from dir_migrate.mcp.llm import _fallback_from_filename, _sanitize_fields


def _fields(
    kind: str,
    *,
    year: int | None = 2024,
    season: int | None = None,
    episode: int | None = None,
    confidence: float | None = 0.9,
) -> LlmFields:
    return LlmFields(
        kind=kind,
        title="Example",
        series="Example" if kind == "tv" else None,
        franchise_root=None,
        year=year,
        season=season,
        episode=episode,
        episode_title=None,
        resolution="2160p",
        source="UHD",
        codec="HEVC",
        audio=None,
        group=None,
        video_tags=None,
        confidence=confidence,
    )


class TestMediaClassification(unittest.TestCase):
    def test_4k_episode_marker_overrides_movie_guess(self):
        decision = classify_media(
            "Foundation.4K/Season 02/Foundation.S02E03.2160p.UHD.HEVC.mkv",
            _fields("movie"),
        )
        self.assertEqual("tv", decision.kind)
        self.assertEqual((2, 3), (decision.season, decision.episode))

    def test_4k_movie_stays_movie(self):
        decision = classify_media(
            "Movies.4K/Dune.Part.Two.2024.2160p.UHD.HEVC.mkv",
            _fields("movie"),
        )
        self.assertEqual("movie", decision.kind)

    def test_4k_movie_franchise_number_is_not_episode(self):
        decision = classify_media(
            "Movies.4K/Mission.Impossible.7.2023.2160p.UHD.HEVC.mkv",
            _fields("movie"),
        )
        self.assertEqual("movie", decision.kind)
        self.assertIsNone(decision.episode)

    def test_supergirl_llm_hallucinated_s01e01_falls_back_to_movie(self):
        filename = (
            "Supergirl.2026.2160p.iT.WEB-DL.DV.HDR10+.MULTi."
            "DDP5.1.Atmos.H265.MP4-BTM.mkv"
        )
        raw = _fields("tv", season=1, episode=1, confidence=0.99)
        sanitized = _sanitize_fields(filename, raw, _fallback_from_filename(filename))
        decision = classify_media(filename, sanitized)
        self.assertEqual("unknown", sanitized.kind)
        self.assertEqual("movie", decision.kind)
        self.assertIsNone(decision.season)
        self.assertIsNone(decision.episode)
        self.assertIn("year 2026 + source WEB-DL", decision.explanation)

    def test_season_directory_and_episode_filename_are_tv(self):
        decision = classify_media(
            "Slow Horses/Season 04/E05.2160p.HEVC.mkv",
            _fields("movie"),
        )
        self.assertEqual("tv", decision.kind)
        self.assertEqual((4, 5), (decision.season, decision.episode))

    def test_chinese_season_episode_are_tv(self):
        decision = classify_media(
            "庆余年/第2季/庆余年.第12集.4K.HEVC.mkv",
            _fields("movie"),
        )
        self.assertEqual("tv", decision.kind)
        self.assertEqual((2, 12), (decision.season, decision.episode))

    def test_specials_season_zero_is_tv(self):
        decision = classify_media(
            "Show.Name/Specials/Show.Name.S00E03.2160p.HEVC.mkv",
            _fields("movie"),
        )
        self.assertEqual("tv", decision.kind)
        self.assertEqual((0, 3), (decision.season, decision.episode))

    def test_season_without_episode_is_pending_not_movie(self):
        decision = classify_media(
            "Show.Name.4K/Season 01/Show.Name.2160p.HEVC.mkv",
            _fields("movie"),
        )
        self.assertEqual("unknown", decision.kind)
        self.assertIn("pending", decision.explanation)

    def test_low_confidence_4k_guess_is_pending(self):
        decision = classify_media(
            "Ambiguous.Title.2024.4K.HEVC.mkv",
            _fields("movie", confidence=None),
        )
        self.assertEqual("unknown", decision.kind)

    def test_tv_sidecar_is_metadata_fallback(self):
        kind, evidence, season, episode = sidecar_media_kind(
            "episode.nfo",
            "<episodedetails><season>1</season><episode>2</episode></episodedetails>",
        )
        decision = classify_media(
            "Opaque.Name.mkv",
            _fields("movie", season=season, episode=episode, confidence=None),
            metadata_kind=kind,
            metadata_evidence=evidence,
        )
        self.assertEqual("tv", decision.kind)


class TestPlannerClassification(unittest.TestCase):
    def setUp(self):
        self.cfg = AppConfig(
            source=StorageConfig(kind="ftp"),
            dest=StorageConfig(kind="ftp"),
            paths=PathsConfig(local_cache_dir=Path("/tmp/db90-classification-test")),
            video=VideoConfig(extensions=(".mkv",), min_bytes=0),
            subtitle=SubtitleConfig(extensions=(".srt",)),
            cleanup=CleanupConfig(enabled=False),
            llm=LlmConfig(provider="ollama", base_url="http://localhost:11434", model="test"),
            imdb=ImdbConfig(enabled=False),
            rules=RulesConfig(
                movie_1080_root="Movies",
                movie_4k_root="Movies4K",
                tv_1080_root="TV",
                tv_4k_root="TV4K",
            ),
            execution=ExecutionConfig(dry_run=True, apply=False, limit=None, workers=1),
        )

    def _plan(self, path: str, fields: LlmFields, source_storage=None):
        llm = MagicMock()
        llm.infer.return_value = fields
        item = SourceFiles(video_path=path, subtitle_paths=(), video_size_bytes=None)
        return plan_one(self.cfg, llm, item, source_storage=source_storage)

    def test_4k_tv_directory_plans_to_tv_root(self):
        plan = self._plan(
            "Foundation.4K/Season 02/Foundation.S02E03.2160p.UHD.HEVC.mkv",
            _fields("movie"),
        )
        self.assertIsNone(plan.skip_reason)
        self.assertTrue(plan.dest_dir.startswith("/TV4K/"))
        self.assertTrue(plan.dest_dir.endswith("/S02"))
        self.assertIn("S02E03", plan.normalized_basename)

    def test_4k_movie_franchise_plans_to_movie_root(self):
        plan = self._plan(
            "Mission.Impossible/"
            "Mission.Impossible.Dead.Reckoning.Part.One.2023.2160p.UHD.HEVC.mkv",
            _fields("movie"),
        )
        self.assertIsNone(plan.skip_reason)
        self.assertTrue(plan.dest_dir.startswith("/Movies4K/"))

    def test_supergirl_hallucinated_tv_plan_uses_movie_root(self):
        plan = self._plan(
            "Supergirl.2026.2160p.iT.WEB-DL.DV.HDR10+.MULTi."
            "DDP5.1.Atmos.H265.MP4-BTM.mkv",
            _fields("tv", year=2026, season=1, episode=1, confidence=0.99),
        )
        self.assertIsNone(plan.skip_reason)
        self.assertTrue(plan.dest_dir.startswith("/Movies4K/2026/"))
        self.assertNotIn("S01E01", plan.normalized_basename)

    def test_incomplete_tv_evidence_is_pending(self):
        plan = self._plan(
            "Show.Name.4K/Season 01/Show.Name.2160p.HEVC.mkv",
            _fields("movie"),
        )
        self.assertIn("classification pending", plan.skip_reason or "")
        self.assertEqual(plan.source.video_path, plan.dest_video_path)

    def test_nfo_metadata_recovers_opaque_tv_episode(self):
        storage = MagicMock()
        storage.list_dir.return_value = [("Opaque.Name.nfo", "file", 100)]
        storage.read_text.return_value = (
            "<episodedetails><tvshowtitle>Example Show</tvshowtitle>"
            "<season>3</season><episode>7</episode></episodedetails>"
        )
        plan = self._plan("Opaque.Name.mkv", _fields("movie"), source_storage=storage)
        self.assertIsNone(plan.skip_reason)
        self.assertTrue(plan.dest_dir.startswith("/TV4K/"))
        self.assertTrue(plan.dest_dir.endswith("/S03"))
        self.assertIn("S03E07", plan.normalized_basename)


if __name__ == "__main__":
    unittest.main()
