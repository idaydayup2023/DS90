import unittest
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srt_translate.srt import format_srt, parse_srt


class TestSrt(unittest.TestCase):
    def test_parse_and_format_roundtrip(self):
        src = (
            "1\n"
            "00:00:01,000 --> 00:00:02,500\n"
            "Hello.\n"
            "\n"
            "2\n"
            "00:00:03,000 --> 00:00:04,000\n"
            "Line1\n"
            "Line2\n"
            "\n"
        )
        cues = parse_srt(src)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].start_ms, 1000)
        self.assertEqual(cues[0].end_ms, 2500)
        out = format_srt(cues)
        cues2 = parse_srt(out)
        self.assertEqual([c.start_ms for c in cues2], [1000, 3000])
        self.assertEqual([c.end_ms for c in cues2], [2500, 4000])
