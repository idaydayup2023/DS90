import tempfile
import unittest
from pathlib import Path
import sys

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


class _FakePgsOcr:
    def track_to_srt(self, video_path: Path, stream_index: int, out_srt_path: Path, language_hint: str | None) -> Path:
        out_srt_path.parent.mkdir(parents=True, exist_ok=True)
        out_srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
        return out_srt_path


class TestPgsOcrSelection(unittest.TestCase):
    def test_uses_pgs_ocr_when_no_text_tracks(self):
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
                ftp=_FakeFtp(),
                media=_FakeMedia(tracks),
                pgs_ocr=_FakePgsOcr(),
                cache_dir=cache_dir,
                video_remote_path="/Downloads/Movie.mkv",
                local_video_path=video,
                dry_run=True,
            )
            self.assertIsNotNone(source)
            assert source is not None
            self.assertEqual(source.kind, "emb")
            self.assertTrue(source.meta.get("ocr"))
