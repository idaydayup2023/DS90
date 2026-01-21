import tempfile
import unittest
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srt_translate.orchestrator import _collect_related_subtitles_for_migration


class TestSrtTranslateMigrateSubtitles(unittest.TestCase):
    class _FsStorage:
        def __init__(self, root: Path):
            self._root = root

        def list_dir(self, path: str):
            base = (self._root / path.strip("/")).resolve()
            if not base.exists():
                return []
            out = []
            for p in base.iterdir():
                rel = "/" + str(p.relative_to(self._root)).replace("\\", "/")
                t = "dir" if p.is_dir() else "file"
                size = p.stat().st_size if p.is_file() else None
                out.append((rel, t, size))
            return out

    def test_collects_language_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / "A").mkdir(parents=True, exist_ok=True)
            (root / "A" / "Movie.mkv").write_bytes(b"")
            (root / "A" / "Movie.en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
            (root / "A" / "Movie.zh.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
            (root / "A" / "Movie.ai.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
            (root / "A" / "Other.en.srt").write_text("x", encoding="utf-8")
            (root / "A" / "Movie2.srt").write_text("x", encoding="utf-8")

            storage = self._FsStorage(root=root)
            subs = _collect_related_subtitles_for_migration(storage, "A/Movie.mkv", (".srt", ".ass", ".vtt"))

            self.assertIn("A/Movie.en.srt", subs)
            self.assertIn("A/Movie.zh.srt", subs)
            self.assertIn("A/Movie.ai.srt", subs)
            self.assertNotIn("A/Other.en.srt", subs)
            self.assertNotIn("A/Movie2.srt", subs)
