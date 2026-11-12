import unittest
from unittest.mock import patch

from app import create_app


class SessionRoutesTestCase(unittest.TestCase):
    def setUp(self):
        class TestConfig:
            SECRET_KEY = "test-secret"
            WTF_CSRF_ENABLED = False
            TESTING = True

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def set_session(self, role="customer"):
        with self.client.session_transaction() as session:
            session["user_id"] = 9
            session["role"] = role

    def test_unauthenticated_and_customer_cannot_manage_sessions(self):
        self.assertEqual(self.client.get("/admin/sessions").status_code, 302)
        self.set_session()
        self.assertEqual(self.client.get("/admin/sessions").status_code, 403)
        self.assertEqual(self.client.post("/admin/sessions/start").status_code, 403)

    @patch("app.blueprints.admin.search_session_customers", return_value=[])
    def test_admin_customer_search_requires_two_characters(self, search):
        self.set_session("admin")
        response = self.client.get("/admin/sessions/customers/search?q=a")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        search.assert_not_called()

    @patch(
        "app.blueprints.admin.search_session_customers",
        return_value=[
            {"id": 12, "first_name": "Ana", "last_name": "Santos", "email": "ana@example.test"}
        ],
    )
    def test_admin_customer_search_returns_selected_customer_data(self, search):
        self.set_session("admin")
        response = self.client.get("/admin/sessions/customers/search?q=Ana")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()[0]["id"], 12)
        search.assert_called_once_with("Ana")

    def test_customer_cannot_search_customers(self):
        self.set_session("customer")
        self.assertEqual(
            self.client.get("/admin/sessions/customers/search?q=Ana").status_code,
            403,
        )

    def test_customer_cannot_access_admin_availability(self):
        self.set_session("customer")
        self.assertEqual(
            self.client.get("/admin/sessions/units/availability").status_code,
            403,
        )

    @patch("app.blueprints.admin.get_units_with_availability", return_value=[])
    def test_admin_availability_endpoint_returns_latest_snapshot(self, get_units):
        self.set_session("admin")
        response = self.client.get("/admin/sessions/units/availability")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])
        get_units.assert_called_once_with()

    @patch("app.blueprints.admin.get_startable_units", return_value=[])
    @patch("app.blueprints.admin.get_admin_sessions", return_value=[])
    def test_admin_can_view_sessions(
        self, get_sessions, get_units
    ):
        self.set_session("admin")
        response = self.client.get("/admin/sessions")
        self.assertEqual(response.status_code, 200)
        get_sessions.assert_called_once_with()
        get_units.assert_called_once_with()

    @patch("app.blueprints.admin.start_session", return_value=11)
    def test_admin_can_start_walk_in(self, start_session):
        self.set_session("admin")
        response = self.client.post(
            "/admin/sessions/start",
            data={
                "unit_id": "3",
                "customer_id": "12",
            },
        )
        self.assertEqual(response.status_code, 302)
        start_session.assert_called_once()
        self.assertEqual(start_session.call_args.kwargs["unit_id"], 3)
        self.assertEqual(start_session.call_args.kwargs["admin_id"], 9)
        self.assertEqual(start_session.call_args.kwargs["user_id"], 12)
        self.assertNotIn("duration_hours", start_session.call_args.kwargs)
        self.assertNotIn("customer_name", start_session.call_args.kwargs)

    @patch("app.blueprints.admin.extend_session")
    def test_admin_can_extend_session(self, extend_session):
        self.set_session("admin")
        response = self.client.post(
            "/admin/sessions/11/extend", data={"minutes": "30"}
        )
        self.assertEqual(response.status_code, 302)
        extend_session.assert_called_once_with(11, 9, 30)

    @patch("app.blueprints.admin.complete_session")
    def test_admin_can_complete_session(self, complete_session):
        self.set_session("admin")
        response = self.client.post("/admin/sessions/11/complete")
        self.assertEqual(response.status_code, 302)
        complete_session.assert_called_once_with(11)


if __name__ == "__main__":
    unittest.main()
