from pathlib import Path
import re
import sys

import mysql.connector


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Config


SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
SEED_PATH = PROJECT_ROOT / "sql" / "seed.sql"
TARGET_DATABASE = "hbp_management_system"
EXPECTED_TABLE_COUNT = 12
EXPECTED_TABLES = {
    "unit_categories",
    "units",
    "users",
    "email_tokens",
    "reservations",
    "sessions",
    "session_extensions",
    "products",
    "orders",
    "order_items",
    "loyalty_redemptions",
    "waitlist",
}


def _read_statements(path):
    sql = path.read_text(encoding="utf-8")
    statements = []
    current = []
    quote = None
    index = 0

    while index < len(sql):
        character = sql[index]
        next_character = sql[index + 1] if index + 1 < len(sql) else ""

        if quote:
            current.append(character)
            if character == "\\" and next_character:
                current.append(next_character)
                index += 2
                continue
            if character == quote:
                if next_character == quote:
                    current.append(next_character)
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if character in ("'", '"', "`"):
            quote = character
            current.append(character)
            index += 1
        elif character == "/" and next_character == "*":
            index += 2
            comment_closed = False
            while index < len(sql):
                if sql[index] == "*" and index + 1 < len(sql) and sql[index + 1] == "/":
                    index += 2
                    comment_closed = True
                    break
                if sql[index] in "\r\n":
                    current.append(sql[index])
                index += 1
            current.append(" ")
            if not comment_closed:
                raise RuntimeError(f"Unterminated SQL comment in {path.name}.")
        elif character == "#" or (
            character == "-"
            and next_character == "-"
            and index + 2 < len(sql)
            and sql[index + 2].isspace()
        ):
            index += 1 if character == "#" else 2
            while index < len(sql) and sql[index] not in "\r\n":
                index += 1
        elif character == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
        else:
            current.append(character)
            index += 1

    if quote:
        raise RuntimeError(f"Unterminated SQL quote in {path.name}.")

    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def _table_creation_statements(statements):
    create_statements = []
    table_names = []
    allowed_non_table = re.compile(
        r"^\s*(CREATE\s+DATABASE|USE|SET)\b", re.IGNORECASE
    )
    destructive = re.compile(
        r"^\s*(DROP|TRUNCATE|DELETE|ALTER|UPDATE)\b", re.IGNORECASE
    )

    for statement in statements:
        if destructive.match(statement):
            continue
        table_match = re.match(
            r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([A-Za-z0-9_]+)`?",
            statement,
            re.IGNORECASE,
        )
        if table_match:
            create_statements.append(statement)
            table_names.append(table_match.group(1))
        elif not allowed_non_table.match(statement):
            raise RuntimeError(
                f"Unexpected non-table SQL in {SCHEMA_PATH.name}; refusing to continue."
            )

    if len(create_statements) != EXPECTED_TABLE_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_TABLE_COUNT} CREATE TABLE statements, "
            f"found {len(create_statements)}."
        )
    if set(table_names) != EXPECTED_TABLES:
        missing_tables = sorted(EXPECTED_TABLES - set(table_names))
        unexpected_tables = sorted(set(table_names) - EXPECTED_TABLES)
        raise RuntimeError(
            "Schema table definitions do not match the expected project tables. "
            f"Missing: {missing_tables or 'none'}; "
            f"unexpected: {unexpected_tables or 'none'}."
        )
    return create_statements


def _seed_statements(statements):
    inserts = []
    allowed_non_insert = re.compile(r"^\s*USE\b", re.IGNORECASE)
    destructive = re.compile(
        r"^\s*(DROP|TRUNCATE|DELETE|ALTER|UPDATE)\b", re.IGNORECASE
    )

    for statement in statements:
        if destructive.match(statement):
            raise RuntimeError(
                f"Refusing to execute destructive SQL from {SEED_PATH.name}."
            )
        if re.match(r"^\s*INSERT\s+INTO\b", statement, re.IGNORECASE):
            inserts.append(statement)
        elif not allowed_non_insert.match(statement):
            raise RuntimeError(
                f"Seed SQL must contain only INSERT INTO statements: {SEED_PATH.name}."
            )
    return inserts


def _connect():
    if Config.DB_NAME != TARGET_DATABASE:
        raise RuntimeError(
            f"Refusing initialization: DB_NAME must be {TARGET_DATABASE!r}."
        )
    try:
        return mysql.connector.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME,
        )
    except mysql.connector.Error as error:
        raise RuntimeError(
            "Unable to connect to the configured MySQL database. "
            "Check the database settings in .env."
        ) from error


def main():
    """Initialize an empty database for first-time development setup only."""
    print(
        "WARNING: This script is for first-time initialization only. "
        "It refuses to run when any table already exists."
    )

    if not SCHEMA_PATH.is_file() or not SEED_PATH.is_file():
        raise SystemExit("Required schema.sql and seed.sql files were not found.")

    create_statements = _table_creation_statements(
        _read_statements(SCHEMA_PATH)
    )
    seed_statements = _seed_statements(_read_statements(SEED_PATH))

    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE()")
            selected_database = cursor.fetchone()[0]
            if selected_database != TARGET_DATABASE:
                raise RuntimeError(
                    f"Refusing initialization: selected database is "
                    f"{selected_database!r}, not {TARGET_DATABASE!r}."
                )

            cursor.execute("SHOW TABLES")
            existing_tables = cursor.fetchall()
            if existing_tables:
                raise RuntimeError(
                    "Refusing initialization because the target database is not empty."
                )

            for statement in create_statements:
                cursor.execute(statement)
            connection.commit()

            try:
                for statement in seed_statements:
                    cursor.execute(statement)
                connection.commit()
            except mysql.connector.Error as error:
                connection.rollback()
                raise RuntimeError(
                    "Seed insertion failed. The seed transaction was rolled "
                    "back; DDL may already be committed."
                ) from error
    except mysql.connector.Error as error:
        raise RuntimeError(
            "Database initialization failed. DDL may have been committed "
            "before the failure; inspect the database before retrying."
        ) from error
    finally:
        connection.close()

    print(
        f"Created {len(create_statements)} tables and applied "
        f"{len(seed_statements)} seed statements."
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
