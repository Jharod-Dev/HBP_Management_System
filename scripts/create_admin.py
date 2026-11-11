import getpass

from werkzeug.security import generate_password_hash

from app.config import Config
from app.db import execute


def main():
    name = input("Name: ").strip()
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    if not name or not email or not password:
        raise SystemExit("Name, email, and password are required.")

    execute(
        """
        INSERT INTO users (name, email, password_hash, role, is_verified)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (name, email, generate_password_hash(password), "admin", 1),
    )
    print(f"Admin account created for {email}.")


if __name__ == "__main__":
    from app import create_app

    with create_app(Config).app_context():
        main()
