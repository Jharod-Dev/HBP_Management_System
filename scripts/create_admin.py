import getpass

from werkzeug.security import generate_password_hash

from app.config import Config
from app.db import execute


def main():
    first_name = input("First name: ").strip()
    last_name = input("Last name: ").strip()
    email = input("Email: ").strip().lower()
    password = getpass.getpass("Password: ")
    if not first_name or not last_name or not email or not password:
        raise SystemExit("First name, last name, email, and password are required.")

    execute(
        """
        INSERT INTO users
            (first_name, last_name, email, password_hash, role, is_verified)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            first_name,
            last_name,
            email,
            generate_password_hash(password),
            "admin",
            1,
        ),
    )
    print(f"Admin account created for {email}.")


if __name__ == "__main__":
    from app import create_app

    with create_app(Config).app_context():
        main()
