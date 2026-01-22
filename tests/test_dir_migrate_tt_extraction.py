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


class TestDirMigrateImdbTtExtraction(unittest.TestCase):
    def test_extract_tt_from_nfo_and_lookup_by_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / "The.Rip.2026").mkdir(parents=True, exist_ok=True)
            (root / "The.Rip.2026" / "The.Rip.2026.mkv").write_bytes(b"v")
            (root / "The.Rip.2026" / "The.Rip.2026.nfo").write_text(
                "https://www.imdb.com/title/tt0137523/\n", encoding="utf-8"
            )

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
                title="The Rip",
                series=None,
                franchise_root=None,
                year=2026,
                season=None,
                episode=None,
                episode_title=None,
                resolution="1080p",
                source="WEB-DL",
                codec="x265",
                audio="5.1",
                group=None,
                confidence=0.9,
            )
            llm = _FakeLlm(fields)
            item = SourceFiles(video_path="The.Rip.2026/The.Rip.2026.mkv", subtitle_paths=(), video_size_bytes=None)
            source_storage = LocalMcp(root=root)
            dest_storage = LocalMcp(root=root / "dest")

            called: dict[str, str] = {}

            class _FakeImdbMcp:
                def __init__(self, *a, **k):
                    pass

                def lookup_by_id_debug(self, imdb_tt: str):
                    called["tt"] = imdb_tt
                    t = ImdbTitle(
                        imdb_id="0137523",
                        kind="movie",
                        title="Fight Club",
                        year=1999,
                        rating=8.8,
                        votes=1000,
                        canonical_title="Fight Club",
                        canonical_year=1999,
                        series_title=None,
                        franchise_root=None,
                    )
                    dbg = type("_D", (), {"status": "ok", "error": None, "candidates": ()})()
                    return t, dbg

                def lookup_debug(self, kind: str, title: str | None, year: int | None):
                    raise AssertionError("lookup_debug should not be called when tt is available")

            old = planner_mod.ImdbMcp
            try:
                planner_mod.ImdbMcp = _FakeImdbMcp
                plan = planner_mod.plan_one(cfg, llm, item, dest_storage=dest_storage, source_storage=source_storage)
            finally:
                planner_mod.ImdbMcp = old

            self.assertEqual(called.get("tt"), "tt0137523")
            self.assertNotEqual(plan.dest_dir, "/Downloads/low_imdb")

