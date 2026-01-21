import unittest
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dir_migrate.mcp.imdb import ImdbMcp


class TestImdbLdJsonParse(unittest.TestCase):
    def test_parse_ld_json_extracts_rating(self):
        html = '''
        <html><head>
        <script type="application/ld+json">
        {"@context":"http://schema.org","@type":"Movie","name":"The Rip","datePublished":"2026-01-01",
         "aggregateRating":{"@type":"AggregateRating","ratingValue":"6.8","ratingCount":"12345"}}
        </script>
        </head></html>
        '''
        imdb = ImdbMcp(cache_dir=Path("/tmp"), auto_install=False, ttl_days=0)
        obj = imdb._parse_ld_json(html)
        self.assertIsNotNone(obj)
        self.assertEqual(obj.get("name"), "The Rip")
