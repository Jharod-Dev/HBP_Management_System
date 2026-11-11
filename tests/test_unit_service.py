import unittest
from unittest.mock import patch

from app.services.units import get_units_with_availability


class UnitAvailabilityServiceTestCase(unittest.TestCase):
    @patch("app.services.units.fetch_all", return_value=[])
    @patch("app.services.units.now", return_value="2026-11-12 04:00:00")
    def test_availability_query_uses_one_consistent_current_time(
        self, current_time, fetch_all
    ):
        self.assertEqual(get_units_with_availability(), [])
        fetch_all.assert_called_once()
        query, params = fetch_all.call_args.args
        self.assertIn("WHEN u.is_active = 0 OR u.status = 'UNAVAILABLE'", query)
        self.assertIn("s.status = 'ACTIVE'", query)
        self.assertIn("r.status = 'CONFIRMED'", query)
        self.assertEqual(
            params,
            ("2026-11-12 04:00:00", "2026-11-12 04:00:00"),
        )
        current_time.assert_called_once_with()
