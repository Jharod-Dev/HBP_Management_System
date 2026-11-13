import unittest
from unittest.mock import patch

from werkzeug.security import check_password_hash, generate_password_hash

from app import create_app


class AuthRoutesTestCase(unittest.TestCase):
    def setUp(self):
        class TestConfig:
            SECRET_KEY = "test-secret"
            WTF_CSRF_ENABLED = False
            TESTING = True

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    @staticmethod
    def registration_form():
        return {
            "first_name": "Ana",
            "last_name": "Santos",
            "email": "ana@example.test",
            "password": "secret",
            "confirm_password": "secret",
        }

    @staticmethod
    def account(role, is_verified=None):
        account = {
            "id": 41,
            "first_name": "Ana",
            "last_name": "Santos",
            "email": "ana@example.test",
            "password_hash": generate_password_hash("secret"),
            "role": role,
        }
        if is_verified is not None:
            account["is_verified"] = is_verified
        return account

    @patch("app.blueprints.auth.execute", return_value=41)
    @patch("app.blueprints.auth.fetch_one", return_value=None)
    def test_registration_creates_customer_without_otp_and_redirects_to_login(
        self, fetch_one, execute
    ):
        response = self.client.post(
            "/auth/register",
            data=self.registration_form(),
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/auth/login"))
        fetch_one.assert_called_once_with(
            "SELECT id FROM users WHERE email = %s", ("ana@example.test",)
        )
        execute.assert_called_once()
        query, params = execute.call_args.args
        self.assertIn("INSERT INTO users", query)
        self.assertNotIn("email_tokens", query)
        self.assertNotIn("is_verified", query)
        self.assertTrue(check_password_hash(params[3], "secret"))

    @patch("app.blueprints.auth.fetch_one")
    def test_existing_unverified_customer_can_log_in_immediately(self, fetch_one):
        fetch_one.return_value = self.account("customer", is_verified=0)
        response = self.client.post(
            "/auth/login",
            data={"email": "ana@example.test", "password": "secret"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/customer/dashboard"))
        query = fetch_one.call_args.args[0]
        self.assertNotIn("is_verified", query)
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], 41)
            self.assertEqual(session["role"], "customer")
            self.assertNotIn("pending_verification_user_id", session)

    @patch("app.blueprints.auth.fetch_one")
    def test_verified_customer_can_log_in(self, fetch_one):
        fetch_one.return_value = self.account("customer", is_verified=1)
        response = self.client.post(
            "/auth/login",
            data={"email": "ana@example.test", "password": "secret"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/customer/dashboard"))

    @patch("app.blueprints.auth.fetch_one")
    def test_admin_login_does_not_depend_on_verification(self, fetch_one):
        fetch_one.return_value = self.account("admin", is_verified=0)
        response = self.client.post(
            "/auth/login",
            data={"email": "ana@example.test", "password": "secret"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/admin/dashboard"))
        self.assertNotIn("is_verified", fetch_one.call_args.args[0])

    def test_verification_endpoints_are_removed(self):
        self.assertEqual(self.client.get("/auth/verify-email").status_code, 404)
        self.assertEqual(
            self.client.post("/auth/resend-verification").status_code, 404
        )

    def test_logout_clears_session(self):
        with self.client.session_transaction() as session:
            session.update(user_id=41, role="customer", first_name="Ana")
        response = self.client.post("/auth/logout")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)
            self.assertNotIn("role", session)

    def test_registration_still_requires_csrf_token(self):
        class CsrfConfig:
            SECRET_KEY = "test-secret"
            TESTING = True
            WTF_CSRF_ENABLED = True

        client = create_app(CsrfConfig).test_client()
        response = client.post("/auth/register", data=self.registration_form())
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
