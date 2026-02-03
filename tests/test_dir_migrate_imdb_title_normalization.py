import tempfile
import unittest
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dir_migrate.agents import planner as planner_mod
from dir_migrate.config import (
    AppConfig,
    CleanupConfig,
    ExecutionConfig,
    ImdbConfig,
    OllamaConfig,
    PathsConfig,
    RulesConfig,
    StorageConfig,
    SubtitleConfig,
    VideoConfig,
)
from dir_migrate.domain import ImdbKnowledge, LlmFields, SourceFiles
from dir_migrate.mcp.imdb import ImdbTitle
from dir_migrate.mcp.storage import LocalMcp


class _FakeLlm:
    def __init__(self, fields: LlmFields):
        self._fields = fields

    def infer(self, _filename: str, _rules: RulesConfig) -> LlmFields:
        return self._fields
    
    def query_imdb(self, title: str, year: int | None) -> ImdbKnowledge:
        # Default mock: no knowledge
        return ImdbKnowledge(title=None, year=None, imdb_id=None, imdb_rating=None, imdb_votes=None, related_movies=())

    @property
    def ollama(self):
        return object()


class TestImdbTitleNormalization(unittest.TestCase):
    def test_imdb_query_title_strips_year_and_tags(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            cfg = AppConfig(
                source=StorageConfig(kind="local", ftp=None, local_root=root),
                dest=StorageConfig(kind="local", ftp=None, local_root=root / "dest"),
                paths=PathsConfig(local_cache_dir=root / ".cache"),
                video=VideoConfig(extensions=(".mkv",), min_bytes=0),
                subtitle=SubtitleConfig(extensions=(".srt",)),
                cleanup=CleanupConfig(enabled=False),
                ollama=OllamaConfig(base_url="http://localhost:11434", model="x", timeout_seconds=5, temperature=0.0),
                imdb=ImdbConfig(enabled=True, auto_install=False, ttl_days=1, min_rating=5.0, min_votes=None, skip_unrated=True, use_llm_judge=False),
                rules=RulesConfig(movie_1080_root="X-Movie", movie_4k_root="MOVIE", tv_1080_root="X-TV", tv_4k_root="TV", year_split=2024, franchise_map={}),
                execution=ExecutionConfig(dry_run=True, apply=False, limit=None, workers=1, on_conflict="skip"),
            )
            fields = LlmFields(
                kind="movie",
                title="The Descent 2005 REMASTERED UNRATED",
                series=None,
                franchise_root=None,
                year=2005,
                season=None,
                episode=None,
                episode_title=None,
                resolution="1080p",
                source="BluRay",
                codec="x265",
                audio="5.1",
                group=None,
            video_tags=None,
                confidence=0.9,
            )
            llm = _FakeLlm(fields)
            item = SourceFiles(video_path="The Descent 2005 REMASTERED UNRATED.mkv", subtitle_paths=(), video_size_bytes=None)

            seen: dict[str, str] = {}

            class _FakeImdbMcp:
                def __init__(self, *a, **k):
                    pass

                def lookup_debug(self, kind: str, title: str | None, year: int | None):
                    seen["title"] = title or ""
                    t = ImdbTitle(
                        imdb_id="0443465",
                        kind="movie",
                        title="The Descent",
                        year=2005,
                        rating=7.2,
                        votes=1,
                        canonical_title="The Descent",
                        canonical_year=2005,
                        series_title=None,
                        franchise_root=None,
                    )
                    dbg = type("_D", (), {"status": "ok", "error": None, "candidates": ()})()
                    return t, dbg

                def lookup_by_id_debug(self, imdb_tt: str):
                    raise AssertionError("tt lookup should not be called in this test")

            old = planner_mod.ImdbMcp
            try:
                planner_mod.ImdbMcp = _FakeImdbMcp
                _ = planner_mod.plan_one(cfg, llm, item, dest_storage=LocalMcp(root=root / "dest"), source_storage=LocalMcp(root=root))
            finally:
                planner_mod.ImdbMcp = old

            self.assertEqual(seen.get("title"), "The Descent")


