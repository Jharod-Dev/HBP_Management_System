import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from app.services.sessions import (
    PREPARATION_SECONDS,
    SessionError,
    _calculate_cost,
    _ensure_preparation_finished,
    get_admin_sessions,
    _walk_in_window,
    start_session,
)


class CursorStub:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.executed = []
        self.lastrowid = 41

    def execute(self, query, params=()):
        self.executed.append((query, params))

    def fetchone(self):
        return next(self.rows, None)


class SessionServiceTestCase(unittest.TestCase):
    CURRENT = datetime(2026, 11, 12, 14, 0)

    def test_pricing_uses_elapsed_server_time(self):
        cost = _calculate_cost(
            Decimal("600"), self.CURRENT, self.CURRENT + timedelta(hours=2)
        )
        self.assertEqual(cost, Decimal("1200.00"))

    def test_walk_in_uses_current_timestamp_and_one_hour(self):
        started_at, scheduled_end = _walk_in_window(self.CURRENT)
        self.assertEqual(started_at, self.CURRENT)
        self.assertEqual(scheduled_end, self.CURRENT + timedelta(hours=1))

    def test_preparation_blocks_before_thirty_seconds(self):
        cursor = CursorStub(
            [{"ended_at": self.CURRENT - timedelta(seconds=29)}]
        )
        with self.assertRaisesRegex(SessionError, "preparing"):
            _ensure_preparation_finished(cursor, 3, self.CURRENT)

    def test_preparation_expires_after_thirty_seconds(self):
        cursor = CursorStub(
            [{"ended_at": self.CURRENT - timedelta(seconds=PREPARATION_SECONDS)}]
        )
        _ensure_preparation_finished(cursor, 3, self.CURRENT)

    @patch("app.services.sessions.complete_expired_sessions")
    @patch(
        "app.services.sessions.fetch_all",
        return_value=[
            {
                "status": "ACTIVE",
                "scheduled_end": datetime(2026, 11, 12, 13, 59),
                "ended_at": None,
            }
        ],
    )
    def test_expired_session_stays_active_and_unbilled(self, fetch_all, complete):
        sessions = get_admin_sessions(current=self.CURRENT)
        self.assertEqual(sessions[0]["status"], "ACTIVE")
        self.assertTrue(sessions[0]["time_expired"])
        self.assertEqual(sessions[0]["remaining_seconds"], 0)
        complete.assert_not_called()

    @patch("app.services.sessions.fetch_all", return_value=[])
    def test_sessions_order_active_then_newest_completed(self, fetch_all):
        get_admin_sessions(current=self.CURRENT)
        query = fetch_all.call_args.args[0]
        self.assertIn("WHEN 'ACTIVE' THEN 0", query)
        self.assertIn("WHEN 'COMPLETED' THEN 1", query)
        self.assertIn("CASE WHEN s.status = 'COMPLETED' THEN s.ended_at END DESC", query)

    @patch("app.services.sessions._transaction", return_value=41)
    def test_start_requires_walk_in_name(self, transaction):
        with self.assertRaisesRegex(SessionError, "customer"):
            start_session(3, 9, current=self.CURRENT)
        transaction.assert_not_called()

    @patch("app.services.sessions._transaction", return_value=41)
    def test_start_requires_one_hour(self, transaction):
        with self.assertRaisesRegex(SessionError, "customer"):
            start_session(3, 9, current=self.CURRENT)
        transaction.assert_not_called()

if __name__ == "__main__":
    unittest.main()
