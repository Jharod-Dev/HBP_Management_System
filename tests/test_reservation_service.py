import unittest
from datetime import datetime
from unittest.mock import patch

from app.services.reservations import (
    ReservationError,
    _validate_schedule,
    create_reservation,
    validate_no_show_time,
)


class ReservationValidationTestCase(unittest.TestCase):
    CURRENT = datetime(2026, 3, 10, 12, 0)

    def test_valid_same_day_schedule(self):
        end = _validate_schedule(datetime(2026, 3, 10, 14, 0), 2, self.CURRENT)
        self.assertEqual(end, datetime(2026, 3, 10, 16, 0))

    def test_rejects_invalid_duration(self):
        with self.assertRaisesRegex(ReservationError, "1, 2, or 3"):
            _validate_schedule(datetime(2026, 3, 10, 14, 0), 4, self.CURRENT)

    def test_rejects_sunday_and_future_dates(self):
        with self.assertRaisesRegex(ReservationError, "Sundays"):
            _validate_schedule(
                datetime(2026, 3, 15, 14, 0), 1, datetime(2026, 3, 15, 10, 0)
            )
        with self.assertRaisesRegex(ReservationError, "today only"):
            _validate_schedule(datetime(2026, 3, 11, 14, 0), 1, self.CURRENT)

    def test_rejects_schedule_outside_operating_hours(self):
        with self.assertRaises(ReservationError):
            _validate_schedule(datetime(2026, 3, 10, 7, 0), 1, self.CURRENT)
        with self.assertRaises(ReservationError):
            _validate_schedule(datetime(2026, 3, 10, 21, 30), 1, self.CURRENT)

    def test_no_show_requires_complete_five_minute_grace_period(self):
        start = datetime(2026, 3, 10, 14, 0)
        with self.assertRaisesRegex(ReservationError, "five-minute"):
            validate_no_show_time(start, datetime(2026, 3, 10, 14, 4, 59))
        validate_no_show_time(start, datetime(2026, 3, 10, 14, 5))

    @patch("app.services.reservations._execute_transaction", return_value=15)
    def test_create_calculates_end_and_delegates_transaction(self, execute):
        result = create_reservation(
            4, 7, datetime(2026, 3, 10, 14, 0), 2, current=self.CURRENT
        )
        self.assertEqual(result, 15)
        execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
