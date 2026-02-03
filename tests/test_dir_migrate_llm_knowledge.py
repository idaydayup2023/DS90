
import unittest
from unittest.mock import MagicMock, patch
from dir_migrate.mcp.llm import LlmMcp
from dir_migrate.domain import ImdbKnowledge
from srt_translate.mcp.llm_mcp import LlmMcp as BaseLlmMcp

class TestLlmKnowledge(unittest.TestCase):
    def test_query_imdb(self):
        mock_llm = MagicMock(spec=BaseLlmMcp)
        mock_llm.generate.return_value.text = """
        {
          "title": "Joe Dirt 2: Beautiful Loser",
          "year": 2015,
          "imdb_rating": 5.7,
          "imdb_votes": 1234,
          "imdb_id": "tt1234567",
          "related_movies": [
            {
              "title": "Joe Dirt",
              "year": 2001,
              "imdb_rating": 7.0
            }
          ]
        }
        """
        llm = LlmMcp(llm=mock_llm, model="test", temperature=0)
        know = llm.query_imdb("Joe Dirt 2", 2015)
        
        self.assertEqual(know.title, "Joe Dirt 2: Beautiful Loser")
        self.assertEqual(know.year, 2015)
        self.assertEqual(know.imdb_rating, 5.7)
        self.assertEqual(know.imdb_votes, 1234)
        self.assertEqual(know.imdb_id, "tt1234567")
        self.assertEqual(len(know.related_movies), 1)
        self.assertEqual(know.related_movies[0].title, "Joe Dirt")
        self.assertEqual(know.related_movies[0].year, 2001)
        self.assertEqual(know.related_movies[0].imdb_rating, 7.0)

    def test_query_imdb_empty_response(self):
        mock_llm = MagicMock(spec=BaseLlmMcp)
        mock_llm.generate.return_value.text = "{}"
        llm = LlmMcp(llm=mock_llm, model="test", temperature=0)
        know = llm.query_imdb("Foo", 2000)
        self.assertIsNone(know.title)
        self.assertIsNone(know.imdb_rating)
        self.assertEqual(len(know.related_movies), 0)

