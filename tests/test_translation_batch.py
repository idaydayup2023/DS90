import unittest
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srt_translate.translation import _parse_batch_output


class TestTranslationBatch(unittest.TestCase):
    def test_parse_batch_output(self):
        text = "<<<SRT_LINE:1>>>\n你好\n<<<SRT_LINE:2>>>\n再见\n"
        got = _parse_batch_output(text)
        self.assertEqual(got, {1: "你好", 2: "再见"})

    def test_parse_batch_output_rejects_noise(self):
        text = "note\n<<<SRT_LINE:1>>>\n你好\n"
        got = _parse_batch_output(text)
        self.assertIsNone(got)
