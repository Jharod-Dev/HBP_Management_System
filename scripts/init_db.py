from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

from app.config import Config


def run_sql_file(connection, path):
    sql = path.read_text(encoding="utf-8")
    statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
    connection.commit()


def main():
    load_dotenv()
    schema_path = Path(__file__).parent.parent / "sql" / "schema.sql"
    seed_path = Path(__file__).parent.parent / "sql" / "seed.sql"
    if not schema_path.is_file() or not seed_path.is_file():
        raise SystemExit("Required files sql/schema.sql and sql/seed.sql were not found.")

    confirmation = input(
        "This will drop and recreate database tables. Type 'yes' to continue: "
    )
    if confirmation.lower() != "yes":
        print("Database initialization cancelled.")
        return

    connection = mysql.connector.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
    )
    try:
        run_sql_file(connection, schema_path)
        run_sql_file(connection, seed_path)
    finally:
        connection.close()
    print("Database schema and seed data initialized.")


if __name__ == "__main__":
    main()
