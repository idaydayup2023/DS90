import unittest
from unittest.mock import MagicMock
from pathlib import PurePosixPath
import sys
from pathlib import Path

# Fix imports
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dir_migrate.agents.planner import plan_one
from dir_migrate.config import AppConfig, RulesConfig, PathsConfig, ImdbConfig
from dir_migrate.domain import SourceFiles, LlmFields
from dir_migrate.mcp.storage import StorageMcp
from dir_migrate.mcp.llm import LlmMcp

class TestDirMigratePlannerSidecar(unittest.TestCase):
    def test_md_file_migration(self):
        # Config
        cfg = MagicMock(spec=AppConfig)
        cfg.rules = RulesConfig(
            movie_1080_root="X-Movie",
            movie_4k_root="MOVIE",
            tv_1080_root="X-TV",
            tv_4k_root="TV",
            year_split=2024,
            franchise_map={},
        )
        cfg.imdb = ImdbConfig(enabled=False, auto_install=False, ttl_days=1, min_rating=None, min_votes=None, skip_unrated=False)
        cfg.paths = MagicMock(spec=PathsConfig)
        cfg.paths.local_cache_dir = Path("/tmp")
        cfg.source = MagicMock()
        cfg.source.kind = "ftp"
        cfg.source.local_root = None

        # LLM
        llm = MagicMock(spec=LlmMcp)
        llm.infer.return_value = LlmFields(
            kind="movie",
            title="My Video",
            year=2024,
            resolution="1080p",
            series=None, franchise_root=None, season=None, episode=None, episode_title=None,
            source=None, codec=None, audio=None, group=None,
            video_tags=None, confidence=None
        )

        # Source Files
        item = SourceFiles(
            video_path="/Downloads/My.Video.2024.mkv",
            subtitle_paths=(),
            video_size_bytes=100
        )

        # Storage
        source_storage = MagicMock(spec=StorageMcp)
        
        # Mock list_dir to return the video and the .md file
        # list_dir returns list of (path, type, size)
        source_storage.list_dir.return_value = [
            ("/Downloads/My.Video.2024.mkv", "file", 100),
            ("/Downloads/My.Video.2024.md", "file", 50),
            ("/Downloads/My.Video.2024.json", "file", 50),
        ]

        # Call plan_one
        plan = plan_one(cfg, llm, item, dest_storage=None, source_storage=source_storage)

        # Assertions
        # Expecting .md file to be in subtitle_moves (which holds sidecars too)
        # moves is a tuple of (source, dest)
        moves = plan.subtitle_moves
        
        # Check for MD
        md_move = next((m for m in moves if m[0].endswith(".md")), None)
        self.assertIsNotNone(md_move, "Should contain .md move")
        self.assertEqual(md_move[0], "/Downloads/My.Video.2024.md")
        # Destination should follow normalized name (My Video (2024))
        # "My Video" -> normalized "My.Video.2024"
        self.assertTrue(md_move[1].endswith(".md"))
        
        # Check for JSON
        json_move = next((m for m in moves if m[0].endswith(".json")), None)
        self.assertIsNotNone(json_move, "Should contain .json move")
        self.assertEqual(json_move[0], "/Downloads/My.Video.2024.json")

if __name__ == '__main__':
    unittest.main()
