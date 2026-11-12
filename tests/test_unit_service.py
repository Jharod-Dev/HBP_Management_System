import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app.services.units import get_units_with_availability


class UnitAvailabilityServiceTestCase(unittest.TestCase):
    @patch("app.services.units.fetch_all", return_value=[])
    @patch("app.services.units.now", return_value=datetime(2026, 11, 12, 4, 0))
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
            (
                datetime(2026, 11, 12, 3, 59, 30),
                datetime(2026, 11, 12, 4, 0),
                datetime(2026, 11, 12, 4, 0),
            ),
        )
        current_time.assert_called_once_with()

    @patch(
        "app.services.units.fetch_all",
        return_value=[
            {
                "id": 1,
                "availability_status": "OCCUPIED",
                "active_scheduled_end": datetime(2026, 11, 12, 5, 0),
                "latest_ended_at": None,
            },
            {
                "id": 2,
                "availability_status": "PREPARING",
                "active_scheduled_end": None,
                "latest_ended_at": datetime(2026, 11, 12, 4, 59, 15),
            },
        ],
    )
    @patch("app.services.units.now", return_value=datetime(2026, 11, 12, 4, 59, 30))
    def test_active_and_preparation_timing_are_independent(
        self, current_time, fetch_all
    ):
        units = get_units_with_availability()
        self.assertEqual(units[0]["active_remaining_seconds"], 30)
        self.assertEqual(units[0]["preparation_remaining_seconds"], 0)
        self.assertEqual(units[1]["active_remaining_seconds"], 0)
        self.assertEqual(units[1]["preparation_remaining_seconds"], 15)
