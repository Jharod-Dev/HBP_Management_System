import unittest
from datetime import datetime
from unittest.mock import patch

from app import create_app
from app.utils.email import send_reservation_decision


class ReservationRoutesTestCase(unittest.TestCase):
    def setUp(self):
        class TestConfig:
            SECRET_KEY = "test-secret"
            WTF_CSRF_ENABLED = False
            TESTING = True

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def set_session(self, role="customer"):
        with self.client.session_transaction() as session:
            session["user_id"] = 4
            session["role"] = role

    def test_protected_reservation_routes_redirect(self):
        self.assertEqual(self.client.get("/customer/reservations").status_code, 302)
        self.assertEqual(self.client.get("/customer/reservations/new").status_code, 302)
        self.assertEqual(self.client.get("/admin/reservations").status_code, 302)

    @patch("app.blueprints.customer.get_customer_reservations", return_value=[])
    def test_customer_can_view_reservations(self, get_reservations):
        self.set_session()
        response = self.client.get("/customer/reservations")
        self.assertEqual(response.status_code, 200)
        get_reservations.assert_called_once_with(4)

    @patch("app.blueprints.customer.create_reservation", return_value=22)
    @patch("app.blueprints.customer.get_reservable_units", return_value=[])
    def test_customer_submission_creates_pending_request(
        self, get_units, create_reservation
    ):
        self.set_session()
        response = self.client.post(
            "/customer/reservations/new",
            data={
                "unit_id": "7",
                "start_time": "2026-03-10T14:00",
                "duration": "2",
            },
        )
        self.assertEqual(response.status_code, 302)
        create_reservation.assert_called_once()
        self.assertEqual(create_reservation.call_args.args[:2], (4, 7))
        self.assertEqual(create_reservation.call_args.args[3], 2)

    @patch("app.blueprints.customer.cancel_customer_reservation")
    def test_customer_can_cancel_own_reservation(self, cancel):
        self.set_session()
        response = self.client.post("/customer/reservations/22/cancel")
        self.assertEqual(response.status_code, 302)
        cancel.assert_called_once()
        self.assertEqual(cancel.call_args.args[:2], (4, 22))

    def test_customer_cannot_access_admin_actions(self):
        self.set_session("customer")
        self.assertEqual(self.client.get("/admin/reservations").status_code, 403)
        self.assertEqual(
            self.client.post("/admin/reservations/22/approve").status_code, 403
        )

    @patch("app.blueprints.admin.get_admin_reservations", return_value=[])
    def test_admin_can_view_reservations(self, get_reservations):
        self.set_session("admin")
        response = self.client.get("/admin/reservations")
        self.assertEqual(response.status_code, 200)
        get_reservations.assert_called_once_with(None, None)

    @patch(
        "app.blueprints.admin.approve_reservation",
        return_value={
            "status": "CONFIRMED",
            "email": "customer@example.test",
            "first_name": "Test",
            "last_name": "Customer",
            "unit_name": "VIP 1",
            "start_time": datetime(2026, 3, 10, 14),
            "end_time": datetime(2026, 3, 10, 16),
        },
    )
    @patch("app.blueprints.admin.send_reservation_decision", return_value=True)
    def test_admin_can_approve_and_notify(self, send_email, approve):
        self.set_session("admin")
        response = self.client.post("/admin/reservations/22/approve")
        self.assertEqual(response.status_code, 302)
        approve.assert_called_once_with(22, 4)
        send_email.assert_called_once()

    def test_email_failure_does_not_raise(self):
        class FailingMail:
            def send(self, message):
                raise RuntimeError("SMTP unavailable")

        reservation = {
            "status": "CONFIRMED",
            "email": "customer@example.test",
            "first_name": "Test",
            "last_name": "Customer",
            "unit_name": "VIP 1",
            "start_time": datetime(2026, 3, 10, 14),
            "end_time": datetime(2026, 3, 10, 16),
        }
        with self.app.app_context():
            self.app.config["MAIL_DEFAULT_SENDER"] = "noreply@example.test"
            self.app.extensions["mail"] = FailingMail()
            self.assertFalse(send_reservation_decision(reservation))


if __name__ == "__main__":
    unittest.main()
