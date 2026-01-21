import tempfile
import unittest
from pathlib import Path
import sys
from typing import Any, cast

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srt_translate.mcp.media import SubtitleTrack
from srt_translate.subtitle_acquisition import choose_source_subtitle


class _FakeFtp:
    def exists(self, _path: str) -> bool:
        return False

    def list(self, _path: str):
        return []

    def download(self, _remote_path: str, _local_path: Path):
        raise AssertionError("download should not be called in this test")

    def atomic_write_from_file(self, _remote_path: str, _local_path: Path):
        raise AssertionError("atomic_write_from_file should not be called in dry_run")


class _FakeMedia:
    def __init__(self, tracks):
        self._tracks = tracks

    def probe_subtitles(self, _video_path: Path):
        return list(self._tracks)

    def is_pgs(self, t: SubtitleTrack) -> bool:
        return (t.codec or "").lower() == "hdmv_pgs_subtitle"


class TestPgsOcrSelection(unittest.TestCase):
    def test_choose_source_subtitle_does_not_run_pgs_ocr(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td).resolve()
            video = cache_dir / "v.mkv"
            video.write_bytes(b"")
            tracks = [
                SubtitleTrack(
                    stream_index=2,
                    lang="eng",
                    title="English",
                    codec="hdmv_pgs_subtitle",
                    is_text=False,
                    is_default=False,
                    is_forced=False,
                )
            ]
            source = choose_source_subtitle(
                ftp=cast(Any, _FakeFtp()),
                media=cast(Any, _FakeMedia(tracks)),
                pgs_ocr=object(),
                cache_dir=cache_dir,
                video_remote_path="/Downloads/Movie.mkv",
                local_video_path=video,
                dry_run=True,
            )
            self.assertIsNone(source)
