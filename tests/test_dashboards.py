import unittest
from datetime import datetime
from unittest.mock import patch

from app import create_app


class DashboardRoutesTestCase(unittest.TestCase):
    def setUp(self):
        class TestConfig:
            SECRET_KEY = "test-secret"
            WTF_CSRF_ENABLED = False
            TESTING = True

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def set_session(self, role, user_id=1):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["role"] = role
            session["first_name"] = "Alex"

    def test_guest_sees_public_landing_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Create an account", response.data)

    def test_authenticated_root_redirects_by_role(self):
        self.set_session("customer")
        self.assertEqual(self.client.get("/").headers["Location"], "/customer/dashboard")
        self.set_session("admin")
        self.assertEqual(self.client.get("/").headers["Location"], "/admin/dashboard")

    @patch("app.blueprints.admin.get_admin_reservations", return_value=[{"id": 4}])
    @patch(
        "app.blueprints.admin.get_admin_sessions",
        return_value=[
            {"status": "ACTIVE", "time_expired": True},
            {"status": "ACTIVE", "time_expired": False},
            {"status": "COMPLETED", "time_expired": False},
        ],
    )
    @patch(
        "app.blueprints.admin.get_units_with_availability",
        return_value=[
            {"is_active": 1, "availability_status": "AVAILABLE"},
            {"is_active": 1, "availability_status": "OCCUPIED"},
            {"is_active": 1, "availability_status": "PREPARING"},
            {"is_active": 0, "availability_status": "UNAVAILABLE"},
        ],
    )
    def test_admin_dashboard_uses_operational_records(
        self, get_units, get_sessions, get_reservations
    ):
        self.set_session("admin")
        response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b">3<", response.data)
        self.assertIn(b">1<", response.data)
        get_units.assert_called_once_with()
        get_sessions.assert_called_once_with()
        get_reservations.assert_called_once_with("PENDING")

    @patch(
        "app.blueprints.customer.get_customer_reservations",
        return_value=[
            {
                "unit_name": "VIP Table 1",
                "status": "CONFIRMED",
                "start_time": datetime(2026, 11, 13, 18, 0),
                "end_time": datetime(2026, 11, 13, 19, 0),
            }
        ],
    )
    def test_customer_dashboard_uses_only_current_customer_records(self, get_reservations):
        self.set_session("customer", user_id=9)
        response = self.client.get("/customer/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Hello, Alex.", response.data)
        self.assertIn(b"VIP Table 1", response.data)
        get_reservations.assert_called_once_with(9)

    def test_logout_clears_session_and_returns_public_landing(self):
        self.set_session("customer")
        response = self.client.post("/auth/logout")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)
            self.assertNotIn("role", session)
