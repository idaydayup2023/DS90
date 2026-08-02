
import unittest
import dataclasses
from pathlib import Path
from unittest.mock import MagicMock, patch
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
from dir_migrate.domain import SourceFiles, ImdbKnowledge, LlmFields
from dir_migrate.mcp.llm import LlmMcp
from dir_migrate.mcp.imdb import ImdbMcp, ImdbLookupDebug

class TestPlannerLlmFallback(unittest.TestCase):
    def setUp(self):
        self.cfg = AppConfig(
            source=StorageConfig(kind="ftp"),
            dest=StorageConfig(kind="ftp"),
            paths=PathsConfig(local_cache_dir=Path("/tmp")),
            video=VideoConfig(extensions=(".mkv",), min_bytes=0),
            subtitle=SubtitleConfig(extensions=(".srt",)),
            cleanup=CleanupConfig(enabled=False),
            llm=LlmConfig(
                provider="ollama",
                base_url="http://localhost:11434",
                model="test",
            ),
            imdb=ImdbConfig(enabled=True, min_rating=6.0, skip_unrated=True),
            rules=RulesConfig(
                movie_1080_root="Movies",
                movie_4k_root="Movies4K",
                tv_1080_root="TV",
                tv_4k_root="TV4K",
            ),
            execution=ExecutionConfig(
                dry_run=True,
                apply=False,
                limit=None,
                workers=1,
            ),
        )

        self.llm = MagicMock(spec=LlmMcp)
        self.item = SourceFiles(video_path="/Downloads/Joe.Dirt.2.2015.mkv", subtitle_paths=(), video_size_bytes=None)
        
        # Mock infer result
        self.llm.infer.return_value = LlmFields(
            kind="movie", title="Joe Dirt 2", series=None, franchise_root=None,
            year=2015, season=None, episode=None, episode_title=None,
            resolution="1080p", source=None, codec=None, audio=None, group=None,
            video_tags=None, confidence=1.0
        )

    @patch("dir_migrate.agents.planner.ImdbMcp")
    def test_llm_priority(self, MockImdbMcp):
        # Mock LLM providing rating (Priority)
        self.llm.query_imdb.return_value = ImdbKnowledge(
            title="Joe Dirt 2", year=2015, imdb_id="tt123", imdb_rating=5.7, imdb_votes=1000, related_movies=()
        )
        
        # Mock IMDb returning DIFFERENT rating (e.g. 7.0) - should NOT be called/used
        mock_imdb = MockImdbMcp.return_value
        mock_imdb.lookup_debug.return_value = (None, ImdbLookupDebug(status="ok", error=None, candidates=()))

        plan = plan_one(self.cfg, self.llm, self.item)

        # Verify LLM query called
        self.llm.query_imdb.assert_called_with("Joe Dirt 2", 2015)
        
        # Verify IMDb lookup NOT called (short-circuit)
        mock_imdb.lookup_debug.assert_not_called()
        mock_imdb.lookup_by_id_debug.assert_not_called()
        
        # Verify decision: rating 5.7 (from LLM) < 6.0 => low_imdb
        self.assertEqual(plan.dest_dir, "/Downloads/low_imdb")

    @patch("dir_migrate.agents.planner.ImdbMcp")
    def test_llm_fallback_to_imdb(self, MockImdbMcp):
        # Mock LLM failing (no rating)
        self.llm.query_imdb.return_value = ImdbKnowledge(
            title=None, year=None, imdb_id=None, imdb_rating=None, imdb_votes=None, related_movies=()
        )
        
        # Mock IMDb returning valid rating (7.0)
        from src.dir_migrate.mcp.imdb import ImdbTitle
        mock_imdb = MockImdbMcp.return_value
        fake_title = ImdbTitle(
            imdb_id="tt123", kind="movie", title="Joe Dirt 2", year=2015, rating=7.0, votes=2000,
            canonical_title="Joe Dirt 2", canonical_year=2015, series_title=None, franchise_root=None
        )
        mock_imdb.lookup_debug.return_value = (fake_title, ImdbLookupDebug(status="ok", error=None, candidates=()))

        plan = plan_one(self.cfg, self.llm, self.item)

        # Verify LLM query called
        self.llm.query_imdb.assert_called_with("Joe Dirt 2", 2015)
        
        # Verify IMDb lookup CALLED (fallback)
        mock_imdb.lookup_debug.assert_called()
        
        # Verify decision: rating 7.0 (from IMDb) >= 6.0 => keep (Movies dir)
        self.assertTrue(plan.dest_dir.startswith("/Movies/"))
