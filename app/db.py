from contextlib import closing

import mysql.connector
from flask import current_app


def get_connection():
    return mysql.connector.connect(
        host=current_app.config["DB_HOST"],
        port=current_app.config["DB_PORT"],
        user=current_app.config["DB_USER"],
        password=current_app.config["DB_PASSWORD"],
        database=current_app.config["DB_NAME"],
    )


def fetch_one(query, params=()):
    with closing(get_connection()) as connection:
        with closing(connection.cursor(dictionary=True)) as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()


def fetch_all(query, params=()):
    with closing(get_connection()) as connection:
        with closing(connection.cursor(dictionary=True)) as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()


def execute(query, params=()):
    with closing(get_connection()) as connection:
        with closing(connection.cursor()) as cursor:
            cursor.execute(query, params)
            connection.commit()
            return cursor.lastrowid
