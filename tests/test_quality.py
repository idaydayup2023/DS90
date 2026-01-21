import unittest
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srt_translate.subtitle_quality import score_srt_content


class TestQuality(unittest.TestCase):
    def test_quality_scores_higher_for_healthy_english(self):
        good = (
            "1\n00:00:01,000 --> 00:00:02,000\nHello there.\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\nHow are you?\n\n"
        )
        bad = (
            "1\n00:00:02,000 --> 00:00:01,000\n\uFFFD\uFFFD\uFFFD\n\n"
            "2\n00:00:01,500 --> 00:00:01,900\n♪ [MUSIC] ♪\n\n"
        )
        q_good = score_srt_content(good)
        q_bad = score_srt_content(bad)
        self.assertGreater(q_good.score, q_bad.score)
