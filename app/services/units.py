from ..db import execute, fetch_all, fetch_one
from ..utils.time import now


AVAILABILITY_SQL = """
    SELECT
        u.id,
        u.name,
        u.description,
        u.status AS operational_status,
        u.is_active,
        c.id AS category_id,
        c.name AS category_name,
        c.unit_type,
        c.hourly_rate,
        CASE
            WHEN u.is_active = 0 OR u.status = 'UNAVAILABLE'
                THEN 'UNAVAILABLE'
            WHEN EXISTS (
                SELECT 1
                FROM sessions s
                WHERE s.unit_id = u.id
                  AND s.status = 'ACTIVE'
            )
                THEN 'OCCUPIED'
            WHEN EXISTS (
                SELECT 1
                FROM reservations r
                WHERE r.unit_id = u.id
                  AND r.status = 'CONFIRMED'
                  AND r.start_time <= %s
                  AND r.end_time > %s
            )
                THEN 'RESERVED'
            ELSE 'AVAILABLE'
        END AS availability_status
    FROM units u
    INNER JOIN unit_categories c ON c.id = u.category_id
    ORDER BY c.unit_type, c.name, u.name
"""


def get_units_with_availability():
    current_time = now()
    return fetch_all(AVAILABILITY_SQL, (current_time, current_time))


def get_unit(unit_id):
    return fetch_one(
        """
        SELECT u.id, u.name, u.description, u.status, u.is_active,
               u.category_id, c.name AS category_name, c.unit_type
        FROM units u
        INNER JOIN unit_categories c ON c.id = u.category_id
        WHERE u.id = %s
        """,
        (unit_id,),
    )


def get_active_categories():
    return fetch_all(
        """
        SELECT id, name, unit_type
        FROM unit_categories
        WHERE is_active = 1
        ORDER BY unit_type, name
        """
    )


def create_unit(name, category_id, description):
    return execute(
        """
        INSERT INTO units (category_id, name, description, status, is_active)
        VALUES (%s, %s, %s, 'AVAILABLE', 1)
        """,
        (category_id, name, description or None),
    )


def update_unit(unit_id, name, category_id, description, status, is_active):
    return execute(
        """
        UPDATE units
        SET name = %s,
            category_id = %s,
            description = %s,
            status = %s,
            is_active = %s
        WHERE id = %s
        """,
        (name, category_id, description or None, status, is_active, unit_id),
    )
