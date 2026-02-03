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

    @property
    def model(self):
        return "x"

    @property
    def temperature(self):
        return 0.0


class _FakeImdbMcp:
    def __init__(self, *args, **kwargs):
        pass

    def lookup_debug(self, kind: str, title: str | None, year: int | None):
        return self.lookup(kind, title, year), type("_D", (), {"status": "ok", "error": None, "candidates": ()})()

    def lookup(self, kind: str, title: str | None, year: int | None):
        if kind != "movie":
            return None
        return ImdbTitle(
            imdb_id="0000000",
            kind="movie",
            title=title,
            year=year,
            rating=4.9,
            votes=100000,
            canonical_title="Reservoir Dogs",
            canonical_year=1992,
            series_title=None,
            franchise_root=None,
        )


class TestDirMigrateImdbIntegration(unittest.TestCase):
    def test_plan_one_routes_low_rating_to_low_imdb(self):
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
                imdb=ImdbConfig(enabled=True, auto_install=False, ttl_days=1, min_rating=5.0, min_votes=1000, skip_unrated=True, use_llm_judge=False),
                rules=RulesConfig(movie_1080_root="X-Movie", movie_4k_root="MOVIE", tv_1080_root="X-TV", tv_4k_root="TV", year_split=2024, franchise_map={}),
                execution=ExecutionConfig(dry_run=True, apply=False, limit=None, workers=1, on_conflict="skip"),
            )
            llm = _FakeLlm(
                LlmFields(
                    kind="movie",
                    title="Reservoir Dogs",
                    series=None,
                    franchise_root=None,
                    year=1992,
                    season=None,
                    episode=None,
                    episode_title=None,
                    resolution="1080p",
                    source="BluRay",
                    codec="HEVC",
                    audio="5.1",
                    group="BONE",
                    video_tags=None,
                    confidence=0.9,
                )
            )
            item = SourceFiles(video_path="Reservoir Dogs 1992 REMASTERED 1080p.mkv", subtitle_paths=(), video_size_bytes=None)

            old = planner_mod.ImdbMcp
            try:
                planner_mod.ImdbMcp = _FakeImdbMcp
                plan = planner_mod.plan_one(cfg, llm, item, dest_storage=LocalMcp(root=root / "dest"))
            finally:
                planner_mod.ImdbMcp = old

            self.assertEqual(plan.dest_dir, "/Downloads/low_imdb")
            self.assertTrue(plan.dest_video_path.startswith("/Downloads/low_imdb/"))
            self.assertIsNone(plan.skip_reason)

    def test_plan_one_keeps_when_imdb_error(self):
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
            llm = _FakeLlm(
                LlmFields(
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
            video_tags=None,
                    confidence=0.9,
                )
            )
            item = SourceFiles(video_path="The.Rip.2026.1080p.mkv", subtitle_paths=(), video_size_bytes=None)

            class _ErrorImdbMcp:
                def __init__(self, *a, **k):
                    pass

                def lookup_debug(self, kind: str, title: str | None, year: int | None):
                    dbg = type("_D", (), {"status": "error", "error": "test error", "candidates": ()})()
                    return None, dbg

            old = planner_mod.ImdbMcp
            try:
                planner_mod.ImdbMcp = _ErrorImdbMcp
                plan = planner_mod.plan_one(cfg, llm, item, dest_storage=LocalMcp(root=root / "dest"))
            finally:
                planner_mod.ImdbMcp = old

            self.assertNotEqual(plan.dest_dir, "/Downloads/low_imdb")

    def test_plan_one_keeps_franchise_movie_in_library(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            dest_root = root / "dest"
            (dest_root / "X-Movie" / "1990s" / "Rocky.1976.1080p.BluRay.X.5.1").mkdir(parents=True, exist_ok=True)

            cfg = AppConfig(
                source=StorageConfig(kind="local", ftp=None, local_root=root),
                dest=StorageConfig(kind="local", ftp=None, local_root=dest_root),
                paths=PathsConfig(local_cache_dir=root / ".cache"),
                video=VideoConfig(extensions=(".mkv",), min_bytes=0),
                subtitle=SubtitleConfig(extensions=(".srt",)),
                cleanup=CleanupConfig(enabled=False),
                ollama=OllamaConfig(base_url="http://localhost:11434", model="x", timeout_seconds=5, temperature=0.0),
                imdb=ImdbConfig(enabled=True, auto_install=False, ttl_days=1, min_rating=5.0, min_votes=None, skip_unrated=True, use_llm_judge=False),
                rules=RulesConfig(movie_1080_root="X-Movie", movie_4k_root="MOVIE", tv_1080_root="X-TV", tv_4k_root="TV", year_split=2024, franchise_map={}),
                execution=ExecutionConfig(dry_run=True, apply=False, limit=None, workers=1, on_conflict="skip"),
            )

            llm = _FakeLlm(
                LlmFields(
                    kind="movie",
                    title="Rocky V",
                    series=None,
                    franchise_root=None,
                    year=1990,
                    season=None,
                    episode=None,
                    episode_title=None,
                    resolution="1080p",
                    source="BluRay",
                    codec="X",
                    audio="5.1",
                    group=None,
            video_tags=None,
                    confidence=0.9,
                )
            )
            item = SourceFiles(video_path="Rocky.V.1990.1080p.mkv", subtitle_paths=(), video_size_bytes=None)

            class _FranchiseImdbMcp(_FakeImdbMcp):
                def lookup(self, kind: str, title: str | None, year: int | None):
                    t = super().lookup(kind, title, year)
                    assert t is not None
                    return ImdbTitle(
                        imdb_id=t.imdb_id,
                        kind=t.kind,
                        title=t.title,
                        year=t.year,
                        rating=4.0,
                        votes=100000,
                        canonical_title=t.canonical_title,
                        canonical_year=t.canonical_year,
                        series_title=t.series_title,
                        franchise_root=None,
                    )

            old = planner_mod.ImdbMcp
            old_judge = planner_mod.FranchiseJudgeMcp
            try:
                planner_mod.ImdbMcp = _FranchiseImdbMcp
                planner_mod.FranchiseJudgeMcp = lambda *a, **k: type(
                    "_J",
                    (),
                    {"judge": lambda self, _fn, _parsed, _imdb: type("_D", (), {"is_franchise": True, "franchise_root": "Rocky", "confidence": 0.9})()},
                )()
                plan = planner_mod.plan_one(cfg, llm, item, dest_storage=LocalMcp(root=dest_root))
            finally:
                planner_mod.ImdbMcp = old
                planner_mod.FranchiseJudgeMcp = old_judge

            self.assertNotEqual(plan.dest_dir, "/Downloads/low_imdb")

