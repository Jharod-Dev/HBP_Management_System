import unittest
from unittest.mock import patch

from app import create_app
from app.services.pos import (
    POSValidationError,
    _parse_items,
    create_order,
    update_order_status,
)


class FakeCursor:
    def __init__(self, mode):
        self.mode = mode
        self.lastrowid = 41
        self.rowcount = 1
        self.statements = []
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=()):
        self.statements.append((query, params))
        if "FROM sessions" in query:
            self._result = {"id": 8}
        elif "FROM products" in query and "FOR UPDATE" in query:
            self._result = {
                "id": 3,
                "name": "Soda",
                "price": "45.50",
                "stock_qty": 5,
                "is_active": 1,
            }
        elif "FROM orders" in query:
            self._result = {
                "id": 41,
                "ordered_by": 7,
                "status": (
                    "CANCELLED" if self.mode == "already-cancelled" else "PENDING"
                ),
            }
        elif "FROM order_items" in query:
            self._result = [{"product_id": 3, "quantity": 2}]
        else:
            self._result = None

    def fetchone(self):
        result, self._result = self._result, None
        return result

    def fetchall(self):
        result, self._result = self._result or [], None
        return result


class FakeConnection:
    def __init__(self, mode):
        self.cursor_instance = FakeCursor(mode)
        self.committed = False
        self.rolled_back = False

    def cursor(self, dictionary=False):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class POSRoutesTestCase(unittest.TestCase):
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

    def test_pos_pages_require_authentication_and_role(self):
        self.assertEqual(self.client.get("/admin/products").status_code, 302)
        self.assertEqual(self.client.get("/customer/shop").status_code, 302)
        self.set_session("customer")
        self.assertEqual(self.client.get("/admin/products").status_code, 403)
        self.assertEqual(self.client.get("/admin/orders").status_code, 403)
        self.set_session("admin")
        with patch(
            "app.blueprints.customer.get_products", return_value=[]
        ), patch(
            "app.blueprints.customer.get_customer_active_sessions", return_value=[]
        ):
            self.assertEqual(self.client.get("/customer/shop").status_code, 200)

    @patch("app.blueprints.admin.get_products", return_value=[])
    def test_admin_can_view_products(self, get_products):
        self.set_session("admin")
        response = self.client.get("/admin/products")
        self.assertEqual(response.status_code, 200)
        get_products.assert_called_once_with(include_inactive=True)

    @patch("app.blueprints.admin.create_product", return_value=4)
    def test_admin_can_create_product(self, create_product):
        self.set_session("admin")
        response = self.client.post(
            "/admin/products/new",
            data={"name": "Soda", "price": "45.50", "stock_qty": "12"},
        )
        self.assertEqual(response.status_code, 302)
        create_product.assert_called_once_with("Soda", 45.50, 12)

    @patch(
        "app.blueprints.admin.create_product",
        side_effect=RuntimeError("database unavailable"),
    )
    def test_product_creation_error_is_handled_without_name_error(self, create_product):
        self.set_session("admin")
        response = self.client.post(
            "/admin/products/new",
            data={"name": "Soda", "price": "45.50", "stock_qty": "12"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"We could not add the product. Please try again.", response.data)
        create_product.assert_called_once_with("Soda", 45.50, 12)

    @patch("app.blueprints.customer.get_customer_active_sessions", return_value=[])
    @patch(
        "app.blueprints.customer.get_products",
        return_value=[
            {"id": 3, "name": "Soda", "price": 45, "stock_qty": 4, "is_active": 1},
            {"id": 4, "name": "Chips", "price": 60, "stock_qty": 0, "is_active": 1},
        ],
    )
    def test_customer_can_view_catalog_without_active_session(
        self, get_products, get_sessions
    ):
        self.set_session("customer", user_id=7)
        response = self.client.get("/customer/shop")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Soda", response.data)
        self.assertIn(b"45.00", response.data)
        self.assertIn(b"4 available", response.data)
        self.assertIn(b"Chips", response.data)
        self.assertIn(b"Out of stock", response.data)
        self.assertIn(b"Start an active session before submitting an order.", response.data)
        get_products.assert_called_once_with()
        get_sessions.assert_called_once_with(7)

    @patch(
        "app.blueprints.customer.get_customer_active_sessions",
        return_value=[{"id": 8, "unit_name": "VIP Table 1", "scheduled_end": __import__("datetime").datetime(2026, 11, 13, 5, 0)}],
    )
    @patch(
        "app.blueprints.customer.get_products",
        return_value=[{"id": 3, "name": "Soda", "price": 45, "stock_qty": 4, "is_active": 1}],
    )
    def test_customer_shop_renders_catalog_with_active_order_controls(
        self, get_products, get_sessions
    ):
        self.set_session("customer", user_id=7)
        response = self.client.get("/customer/shop")
        self.assertIn(b"quantity_3", response.data)
        self.assertIn(b"Review and submit order", response.data)

    @patch("app.blueprints.customer.get_customer_active_sessions", return_value=[])
    @patch("app.blueprints.customer.get_products", return_value=[])
    def test_customer_shop_shows_empty_catalog_state(
        self, get_products, get_sessions
    ):
        self.set_session("customer", user_id=7)
        response = self.client.get("/customer/shop")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No snacks or drinks are available", response.data)
        get_products.assert_called_once_with()
        get_sessions.assert_called_once_with(7)

    @patch("app.blueprints.customer.create_order", return_value=9)
    def test_customer_submits_order_with_server_validation_service(
        self, create_order
    ):
        self.set_session("customer", user_id=7)
        response = self.client.post(
            "/customer/orders",
            data={"session_id": "3", "quantity_11": "2"},
        )
        self.assertEqual(response.status_code, 302)
        create_order.assert_called_once_with(7, 3, [("11", "2")])

    @patch("app.blueprints.customer.update_order_status")
    def test_customer_can_cancel_own_order(self, update_status):
        self.set_session("customer", user_id=7)
        response = self.client.post("/customer/orders/9/cancel")
        self.assertEqual(response.status_code, 302)
        update_status.assert_called_once_with(9, "CANCELLED", user_id=7)

    def test_invalid_quantities_are_rejected(self):
        with self.assertRaises(POSValidationError):
            _parse_items([("1", "0")])
        with self.assertRaises(POSValidationError):
            _parse_items([("1", "-2")])
        with self.assertRaises(POSValidationError):
            _parse_items([])

    @patch("app.db.get_connection")
    def test_order_transaction_locks_stock_and_snapshots_price(self, get_connection):
        connection = FakeConnection("create")
        get_connection.return_value = connection
        order_id = create_order(7, 8, [("3", "2")])
        self.assertEqual(order_id, 41)
        self.assertTrue(connection.committed)
        statements = connection.cursor_instance.statements
        item_insert = next(query for query, _ in statements if "INSERT INTO order_items" in query)
        stock_update = next(query for query, _ in statements if "SET stock_qty = stock_qty -" in query)
        self.assertIn("unit_price", item_insert)
        self.assertIn("stock_qty = stock_qty -", stock_update)

    @patch("app.db.get_connection")
    def test_cancellation_restores_stock_once(self, get_connection):
        connection = FakeConnection("cancel")
        get_connection.return_value = connection
        update_order_status(41, "CANCELLED", user_id=7)
        statements = connection.cursor_instance.statements
        restore_count = sum(
            "SET stock_qty = stock_qty +" in query for query, _ in statements
        )
        self.assertEqual(restore_count, 1)

    @patch("app.db.get_connection")
    def test_repeated_cancelled_status_does_not_restore_again(self, get_connection):
        connection = FakeConnection("already-cancelled")
        connection.cursor_instance._result = {
            "id": 41,
            "ordered_by": 7,
            "status": "CANCELLED",
        }
        get_connection.return_value = connection
        update_order_status(41, "CANCELLED", user_id=7)
        self.assertFalse(
            any(
                "stock_qty = stock_qty +" in query
                for query, _ in connection.cursor_instance.statements
            )
        )
