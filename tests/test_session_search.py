import unittest
from unittest.mock import patch

from app.services.sessions import search_session_customers


class SessionCustomerSearchTestCase(unittest.TestCase):
    @patch("app.services.sessions.fetch_all", return_value=[])
    def test_search_requires_two_characters(self, fetch_all):
        self.assertEqual(search_session_customers("a"), [])
        fetch_all.assert_not_called()

    @patch("app.services.sessions.fetch_all", return_value=[])
    def test_search_uses_parameterized_limit_and_patterns(self, fetch_all):
        search_session_customers("A_%", limit=10)
        query, params = fetch_all.call_args.args
        self.assertIn("LIMIT %s", query)
        self.assertIn("ESCAPE", query)
        self.assertEqual(params[-1], 10)
        self.assertNotIn("A_%", params[:3])

