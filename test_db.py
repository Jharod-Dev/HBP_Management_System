import os

import mysql.connector
from dotenv import load_dotenv

load_dotenv()

required_settings = ("DB_HOST", "DB_PORT", "DB_USER", "DB_NAME")
missing_settings = [name for name in required_settings if not os.getenv(name)]
if missing_settings:
    raise SystemExit(
        "Missing database settings in .env: " + ", ".join(missing_settings)
    )

try:
    connection = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME"),
    )

    if connection.is_connected():
        print("Database connection successful!")
        print("Connected to:", connection.database)

    connection.close()

except mysql.connector.Error as error:
    raise SystemExit(
        "Database connection failed. Make sure XAMPP MySQL is running and "
        "the configured database exists.\n"
        f"Details: {error}"
    ) from error
