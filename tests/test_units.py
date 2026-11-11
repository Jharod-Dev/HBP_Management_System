import unittest
from unittest.mock import patch

from app import create_app


class UnitRoutesTestCase(unittest.TestCase):
    def setUp(self):
        class TestConfig:
            SECRET_KEY = "test-secret"
            WTF_CSRF_ENABLED = False
            TESTING = True

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def set_session(self, role):
        with self.client.session_transaction() as session:
            session["user_id"] = 1
            session["role"] = role

    def test_unauthenticated_unit_routes_redirect(self):
        self.assertEqual(self.client.get("/customer/units").status_code, 302)
        self.assertEqual(self.client.get("/admin/units").status_code, 302)

    @patch("app.blueprints.customer.get_units_with_availability", return_value=[])
    def test_customer_can_view_availability(self, get_units):
        self.set_session("customer")
        response = self.client.get("/customer/units")
        self.assertEqual(response.status_code, 200)
        get_units.assert_called_once_with()

    @patch("app.blueprints.admin.get_units_with_availability", return_value=[])
    @patch(
        "app.blueprints.admin.get_active_categories",
        return_value=[],
    )
    def test_admin_can_view_units(self, get_categories, get_units):
        self.set_session("admin")
        response = self.client.get("/admin/units")
        self.assertEqual(response.status_code, 200)
        get_units.assert_called_once_with()
        get_categories.assert_called_once_with()

    def test_customer_cannot_manage_units(self):
        self.set_session("customer")
        self.assertEqual(self.client.get("/admin/units").status_code, 403)
        self.assertEqual(self.client.post("/admin/units/new").status_code, 403)

    @patch("app.blueprints.admin.get_active_categories", return_value=[{"id": 1}])
    @patch("app.blueprints.admin.create_unit", return_value=10)
    def test_admin_can_add_unit(self, create_unit, get_categories):
        self.set_session("admin")
        response = self.client.post(
            "/admin/units/new",
            data={
                "name": "VIP Table 4",
                "category_id": "1",
                "description": "New table",
            },
        )
        self.assertEqual(response.status_code, 302)
        create_unit.assert_called_once_with("VIP Table 4", 1, "New table")
        get_categories.assert_called_once_with()

    @patch(
        "app.blueprints.admin.get_active_categories",
        return_value=[{"id": 1}],
    )
    @patch("app.blueprints.admin.update_unit", return_value=10)
    @patch(
        "app.blueprints.admin.get_unit",
        return_value={
            "id": 10,
            "name": "VIP Table 1",
            "description": "Old description",
            "category_id": 1,
            "status": "AVAILABLE",
            "is_active": 1,
        },
    )
    def test_admin_can_edit_and_manage_status(
        self, get_unit, update_unit, get_categories
    ):
        self.set_session("admin")
        response = self.client.post(
            "/admin/units/10/edit",
            data={
                "name": "VIP Table 1",
                "category_id": "1",
                "description": "Updated description",
                "status": "UNAVAILABLE",
                "is_active": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        update_unit.assert_called_once_with(
            10, "VIP Table 1", 1, "Updated description", "UNAVAILABLE", 1
        )

        get_unit.reset_mock()
        update_unit.reset_mock()
        response = self.client.post("/admin/units/10/deactivate")
        self.assertEqual(response.status_code, 302)
        update_unit.assert_called_once_with(
            10, "VIP Table 1", 1, "Old description", "UNAVAILABLE", 0
        )

    @patch("app.blueprints.admin.get_unit", return_value=None)
    def test_edit_unknown_unit_returns_404(self, get_unit):
        self.set_session("admin")
        self.assertEqual(self.client.get("/admin/units/99/edit").status_code, 404)
        get_unit.assert_called_once_with(99)
