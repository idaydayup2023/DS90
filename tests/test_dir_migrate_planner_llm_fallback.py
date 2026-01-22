
import unittest
import dataclasses
from unittest.mock import MagicMock, patch, ANY
from src.dir_migrate.agents.planner import plan_one
from src.dir_migrate.config import AppConfig, ImdbConfig, RulesConfig, PathsConfig, OllamaConfig
from src.dir_migrate.domain import SourceFiles, ImdbKnowledge, LlmFields
from src.dir_migrate.mcp.llm import LlmMcp
from src.dir_migrate.mcp.imdb import ImdbMcp, ImdbLookupDebug

class TestPlannerLlmFallback(unittest.TestCase):
    def setUp(self):
        self.cfg = MagicMock(spec=AppConfig)
        self.cfg.rules = RulesConfig(
            movie_1080_root="Movies", 
            movie_4k_root="Movies4K",
            tv_1080_root="TV",
            tv_4k_root="TV4K"
        )
        self.cfg.imdb = ImdbConfig(enabled=True, min_rating=6.0, skip_unrated=True)
        self.cfg.paths = MagicMock(spec=PathsConfig)
        self.cfg.paths.local_cache_dir = "/tmp"
        self.cfg.ollama = MagicMock(spec=OllamaConfig)
        self.cfg.ollama.model = "test"

        self.llm = MagicMock(spec=LlmMcp)
        self.item = SourceFiles(video_path="/Downloads/Joe.Dirt.2.2015.mkv", subtitle_paths=(), video_size_bytes=None)
        
        # Mock infer result
        self.llm.infer.return_value = LlmFields(
            kind="movie", title="Joe Dirt 2", series=None, franchise_root=None,
            year=2015, season=None, episode=None, episode_title=None,
            resolution="1080p", source=None, codec=None, audio=None, group=None, confidence=1.0
        )

    @patch("src.dir_migrate.agents.planner.ImdbMcp")
    def test_llm_fallback_used(self, MockImdbMcp):
        # Mock IMDb returning NO rating (unrated)
        mock_imdb = MockImdbMcp.return_value
        mock_imdb.lookup_debug.return_value = (None, ImdbLookupDebug(status="not_found", error=None, candidates=()))
        mock_imdb.lookup_by_id_debug.return_value = (None, ImdbLookupDebug(status="not_found", error=None, candidates=()))

        # Mock LLM knowledge providing rating
        self.llm.query_imdb.return_value = ImdbKnowledge(
            title="Joe Dirt 2", year=2015, imdb_rating=5.7, related_movies=()
        )

        plan = plan_one(self.cfg, self.llm, self.item)

        # Verify LLM query called
        self.llm.query_imdb.assert_called_with("Joe Dirt 2", 2015)
        
        # Verify decision: rating 5.7 < 6.0 => low_imdb
        # If fallback worked, rating=5.7, min_rating=6.0 => should go to low_imdb
        self.assertEqual(plan.dest_dir, "/Downloads/low_imdb")
        
    @patch("src.dir_migrate.agents.planner.ImdbMcp")
    def test_llm_fallback_skipped_for_new_movies(self, MockImdbMcp):
        # Change year to 2025
        self.llm.infer.return_value = dataclasses.replace(self.llm.infer.return_value, year=2025)
        self.item = dataclasses.replace(self.item, video_path="/Downloads/New.Movie.2025.mkv")
        
        mock_imdb = MockImdbMcp.return_value
        mock_imdb.lookup_debug.return_value = (None, ImdbLookupDebug(status="not_found", error=None, candidates=()))

        plan = plan_one(self.cfg, self.llm, self.item)

        # Verify LLM query NOT called (too new)
        self.llm.query_imdb.assert_not_called()
