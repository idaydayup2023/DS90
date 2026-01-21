import tempfile
import unittest
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dir_migrate.agents import cleaner
from dir_migrate.config import (
    AppConfig,
    CleanupConfig,
    ExecutionConfig,
    OllamaConfig,
    PathsConfig,
    RulesConfig,
    StorageConfig,
    SubtitleConfig,
    VideoConfig,
)
from dir_migrate.domain import MovePlan, SourceFiles
from dir_migrate.mcp.storage import LocalMcp
from dir_migrate.agents.executor import apply_one


class TestDirMigrateCleanup(unittest.TestCase):
    def _cfg(self, root: Path, cleanup_enabled: bool = True) -> AppConfig:
        return AppConfig(
            source=StorageConfig(kind="local", ftp=None, local_root=root),
            dest=StorageConfig(kind="local", ftp=None, local_root=root / "dest"),
            paths=PathsConfig(local_cache_dir=root / ".cache"),
            video=VideoConfig(extensions=(".mkv",), min_bytes=0),
            subtitle=SubtitleConfig(extensions=(".srt",)),
            cleanup=CleanupConfig(enabled=cleanup_enabled, protected_dirnames=("torrent.files",), min_confidence=0.85),
            ollama=OllamaConfig(base_url="http://localhost:11434", model="x", timeout_seconds=5, temperature=0.0),
            rules=RulesConfig(
                movie_1080_root="X-Movie",
                movie_4k_root="MOVIE",
                tv_1080_root="X-TV",
                tv_4k_root="TV",
                year_split=2024,
                franchise_map={},
            ),
            execution=ExecutionConfig(dry_run=False, apply=True, limit=None, workers=1, on_conflict="skip"),
        )

    def test_protected_dir_not_removed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            d = root / "A" / "torrent.files"
            d.mkdir(parents=True, exist_ok=True)
            cfg = self._cfg(root)
            storage = LocalMcp(root=root)
            plan = MovePlan(
                source=SourceFiles(video_path="/A/torrent.files/Movie.mkv", subtitle_paths=(), video_size_bytes=None),
                normalized_basename="X",
                dest_dir="/X",
                dest_video_path="/X/X.mkv",
                subtitle_moves=(),
            )
            cleaner.cleanup_source_residual_dirs(cfg, storage, plan)
            self.assertTrue(d.exists())

    def test_empty_dir_removed_when_llm_allows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            d = root / "A" / "MovieFolder"
            d.mkdir(parents=True, exist_ok=True)
            (root / "A").mkdir(parents=True, exist_ok=True)
            (root / "A" / "keep.txt").write_text("x", encoding="utf-8")

            cfg = self._cfg(root)
            storage = LocalMcp(root=root)
            plan = MovePlan(
                source=SourceFiles(video_path="/A/MovieFolder/Movie.mkv", subtitle_paths=(), video_size_bytes=None),
                normalized_basename="X",
                dest_dir="/X",
                dest_video_path="/X/X.mkv",
                subtitle_moves=(),
            )

            old = cleaner._llm_decide_empty_dir
            old_res = cleaner._llm_decide_residual_files
            try:
                cleaner._llm_decide_empty_dir = lambda _cfg, _plan, _dir: cleaner.CleanupDecision(
                    decision="delete", confidence=0.99, reason="test"
                )
                cleaner._llm_decide_residual_files = lambda _cfg, _plan, _dir, _files: cleaner.CleanupDecision(
                    decision="keep", confidence=0.99, reason="test"
                )
                cleaner.cleanup_source_residual_dirs(cfg, storage, plan)
            finally:
                cleaner._llm_decide_empty_dir = old
                cleaner._llm_decide_residual_files = old_res

            self.assertFalse(d.exists())
            self.assertTrue((root / "A").exists())

    def test_residual_files_removed_when_llm_allows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            d = root / "A" / "MovieFolder"
            d.mkdir(parents=True, exist_ok=True)
            (d / "poster.jpg").write_bytes(b"x")
            (d / "info.nfo").write_text("nfo", encoding="utf-8")
            (d / "sample.mkv").write_bytes(b"v")

            cfg = self._cfg(root)
            storage = LocalMcp(root=root)
            plan = MovePlan(
                source=SourceFiles(video_path="/A/MovieFolder/Movie.mkv", subtitle_paths=(), video_size_bytes=None),
                normalized_basename="X",
                dest_dir="/X",
                dest_video_path="/X/X.mkv",
                subtitle_moves=(),
            )

            old_empty = cleaner._llm_decide_empty_dir
            old_res = cleaner._llm_decide_residual_files
            try:
                cleaner._llm_decide_residual_files = lambda _cfg, _plan, _dir, _files: cleaner.CleanupDecision(
                    decision="delete", confidence=0.99, reason="test"
                )
                cleaner._llm_decide_empty_dir = lambda _cfg, _plan, _dir: cleaner.CleanupDecision(
                    decision="delete", confidence=0.99, reason="test"
                )
                cleaner.cleanup_source_residual_dirs(cfg, storage, plan)
            finally:
                cleaner._llm_decide_empty_dir = old_empty
                cleaner._llm_decide_residual_files = old_res

            self.assertFalse(d.exists())

    def test_ai_srt_dedup_when_dest_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            src_root = root / "src"
            dst_root = root / "dst"
            (src_root / "A").mkdir(parents=True, exist_ok=True)
            (dst_root / "X").mkdir(parents=True, exist_ok=True)
            (src_root / "A" / "Movie.mkv").write_bytes(b"v")
            (src_root / "A" / "Movie.ai.srt").write_text("ai", encoding="utf-8")
            (dst_root / "X" / "Movie.ai.srt").write_text("ai-old", encoding="utf-8")

            cfg = self._cfg(src_root, cleanup_enabled=False)
            src_storage = LocalMcp(root=src_root)
            dst_storage = LocalMcp(root=dst_root)
            plan = MovePlan(
                source=SourceFiles(video_path="/A/Movie.mkv", subtitle_paths=("/A/Movie.ai.srt",), video_size_bytes=None),
                normalized_basename="Movie",
                dest_dir="/X",
                dest_video_path="/X/Movie.mkv",
                subtitle_moves=(("/A/Movie.ai.srt", "/X/Movie.ai.srt"),),
            )

            ok, kind, err = apply_one(cfg, src_storage, dst_storage, plan)
            self.assertTrue(ok)
            self.assertIsNone(kind)
            self.assertIsNone(err)
            self.assertFalse((src_root / "A" / "Movie.ai.srt").exists())
            self.assertTrue((dst_root / "X" / "Movie.ai.srt").exists())
