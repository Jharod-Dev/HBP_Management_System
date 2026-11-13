from datetime import datetime, timedelta
from decimal import Decimal

from ..db import fetch_all
from ..utils.time import now


PREPARATION_SECONDS = 30
MINIMUM_SESSION_HOURS = 1
ACTIVE_SESSION = "ACTIVE"
COMPLETED_SESSION = "COMPLETED"
BLOCKING_RESERVATION_STATUSES = ("PENDING", "CONFIRMED")


class SessionError(ValueError):
    pass


class SessionNotFound(SessionError):
    pass


def _transaction(operation):
    from ..db import get_connection

    connection = get_connection()
    try:
        with connection.cursor(dictionary=True) as cursor:
            result = operation(cursor)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _lock_unit(cursor, unit_id):
    cursor.execute(
        """
        SELECT u.id, u.name, u.status, u.is_active, c.hourly_rate,
               c.min_minutes, c.name AS category_name, c.unit_type
        FROM units u
        INNER JOIN unit_categories c ON c.id = u.category_id
        WHERE u.id = %s
        FOR UPDATE
        """,
        (unit_id,),
    )
    unit = cursor.fetchone()
    if unit is None:
        raise SessionError("The selected unit does not exist.")
    if not unit["is_active"] or unit["status"] == "UNAVAILABLE":
        raise SessionError("The selected unit is unavailable.")
    return unit


def _preparing_until(cursor, unit_id, current):
    cursor.execute(
        """
        SELECT ended_at
        FROM sessions
        WHERE unit_id = %s AND status = 'COMPLETED' AND ended_at IS NOT NULL
        ORDER BY ended_at DESC
        LIMIT 1
        """,
        (unit_id,),
    )
    row = cursor.fetchone()
    if row is None or row["ended_at"] is None:
        return None
    preparation_until = row["ended_at"] + timedelta(seconds=PREPARATION_SECONDS)
    return preparation_until if preparation_until > current else None


def _ensure_no_active_session(cursor, unit_id):
    cursor.execute(
        """
        SELECT id
        FROM sessions
        WHERE unit_id = %s AND status = 'ACTIVE'
        LIMIT 1
        """,
        (unit_id,),
    )
    if cursor.fetchone() is not None:
        raise SessionError("The unit already has an active session.")


def _ensure_no_reservation_conflict(
    cursor, unit_id, start_at, end_at, exclude_reservation_id=None
):
    query = """
        SELECT id
        FROM reservations
        WHERE unit_id = %s
          AND status IN (%s, %s)
          AND start_time < %s
          AND end_time > %s
    """
    params = [unit_id, *BLOCKING_RESERVATION_STATUSES, end_at, start_at]
    if exclude_reservation_id is not None:
        query += " AND id <> %s"
        params.append(exclude_reservation_id)
    query += " LIMIT 1"
    cursor.execute(query, tuple(params))
    if cursor.fetchone() is not None:
        raise SessionError("The session overlaps a pending or confirmed reservation.")


def _lock_reservation(cursor, reservation_id):
    cursor.execute(
        """
        SELECT r.*, u.name AS unit_name, usr.first_name, usr.last_name
        FROM reservations r
        INNER JOIN units u ON u.id = r.unit_id
        INNER JOIN users usr ON usr.id = r.user_id
        WHERE r.id = %s
        FOR UPDATE
        """,
        (reservation_id,),
    )
    reservation = cursor.fetchone()
    if reservation is None:
        raise SessionNotFound("Reservation not found.")
    return reservation


def _ensure_preparation_finished(cursor, unit_id, current):
    preparation_until = _preparing_until(cursor, unit_id, current)
    if preparation_until is not None:
        remaining = int((preparation_until - current).total_seconds())
        raise SessionError(
            f"The unit is preparing. Try again in {max(1, remaining)} seconds."
        )


def _walk_in_window(current):
    return current, current + timedelta(hours=MINIMUM_SESSION_HOURS)


def start_session(
    unit_id,
    admin_id,
    reservation_id=None,
    user_id=None,
    current=None,
):
    current = current or now()
    if user_id is None:
        raise SessionError("Select a customer for the session.")

    def operation(cursor):
        selected_user_id = user_id
        unit = _lock_unit(cursor, unit_id)
        _ensure_preparation_finished(cursor, unit_id, current)
        _ensure_no_active_session(cursor, unit_id)

        if reservation_id is not None:
            reservation = _lock_reservation(cursor, reservation_id)
            if reservation["unit_id"] != unit_id:
                raise SessionError("The reservation does not belong to this unit.")
            if reservation["status"] != "CONFIRMED":
                raise SessionError("Only confirmed reservations can start a session.")
            if selected_user_id is not None and reservation["user_id"] != selected_user_id:
                raise SessionError("The reservation belongs to another customer.")
            selected_user_id = reservation["user_id"]
            customer_name = (
                f"{reservation['first_name']} {reservation['last_name']}"
            )
            if current < reservation["start_time"]:
                raise SessionError("The reservation start time has not arrived.")
            if current >= reservation["end_time"]:
                raise SessionError("The reservation has already ended.")
            started_at = current
            scheduled_end = reservation["end_time"]
            if scheduled_end <= started_at:
                raise SessionError("The reservation has no remaining session time.")
            _ensure_no_reservation_conflict(
                cursor,
                unit_id,
                started_at,
                scheduled_end,
                exclude_reservation_id=reservation_id,
            )
        else:
            started_at, scheduled_end = _walk_in_window(current)
            _ensure_no_reservation_conflict(
                cursor, unit_id, started_at, scheduled_end
            )
            cursor.execute(
                """
                SELECT id, first_name, last_name
                FROM users
                WHERE id = %s AND role = 'customer'
                FOR UPDATE
                """,
                (user_id,),
            )
            customer = cursor.fetchone()
            if customer is None:
                raise SessionError("The selected customer does not exist.")
            customer_name = f"{customer['first_name']} {customer['last_name']}"

        cursor.execute(
            """
            INSERT INTO sessions
                (unit_id, user_id, customer_name, reservation_id,
                 started_at, scheduled_end, status, hourly_rate_applied,
                 total_cost, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, 'ACTIVE', %s, 0, %s)
            """,
            (
                unit_id,
                selected_user_id,
                customer_name,
                reservation_id,
                started_at,
                scheduled_end,
                unit["hourly_rate"],
                admin_id,
            ),
        )
        session_id = cursor.lastrowid
        cursor.execute(
            "UPDATE units SET status = 'OCCUPIED' WHERE id = %s",
            (unit_id,),
        )
        if reservation_id is not None:
            cursor.execute(
                """
                UPDATE reservations
                SET status = 'ACTIVE', decided_at = %s
                WHERE id = %s
                """,
                (current, reservation_id),
            )
        return session_id

    return _transaction(operation)


def _calculate_cost(hourly_rate, started_at, ended_at):
    elapsed_minutes = max(
        0, int((ended_at - started_at).total_seconds() // 60)
    )
    return (Decimal(str(hourly_rate)) * Decimal(elapsed_minutes) / Decimal(60)).quantize(
        Decimal("0.01")
    )


def complete_session(session_id, current=None):
    current = current or now()

    def operation(cursor):
        cursor.execute(
            """
            SELECT s.*, u.status AS unit_status
            FROM sessions s
            INNER JOIN units u ON u.id = s.unit_id
            WHERE s.id = %s
            FOR UPDATE
            """,
            (session_id,),
        )
        session = cursor.fetchone()
        if session is None:
            raise SessionNotFound("Session not found.")
        if session["status"] == COMPLETED_SESSION:
            return session

        total_cost = _calculate_cost(
            session["hourly_rate_applied"], session["started_at"], current
        )
        cursor.execute(
            """
            UPDATE sessions
            SET status = 'COMPLETED', ended_at = %s, total_cost = %s
            WHERE id = %s AND status = 'ACTIVE'
            """,
            (current, total_cost, session_id),
        )
        cursor.execute(
            "UPDATE units SET status = 'AVAILABLE' WHERE id = %s",
            (session["unit_id"],),
        )
        if session["reservation_id"] is not None:
            cursor.execute(
                """
                UPDATE reservations
                SET status = 'COMPLETED', decided_at = %s
                WHERE id = %s AND status = 'ACTIVE'
                """,
                (current, session["reservation_id"]),
            )
        session.update(
            status=COMPLETED_SESSION,
            ended_at=current,
            total_cost=total_cost,
        )
        return session

    return _transaction(operation)


def complete_expired_sessions(current=None):
    current = current or now()
    expired = fetch_all(
        """
        SELECT id
        FROM sessions
        WHERE status = 'ACTIVE' AND scheduled_end <= %s
        """,
        (current,),
    )
    completed = []
    for session in expired:
        completed.append(complete_session(session["id"], current=current))
    return completed


def extend_session(session_id, admin_id, minutes, current=None):
    current = current or now()
    if minutes <= 0 or minutes % 30 != 0:
        raise SessionError("Extensions must use positive 30-minute increments.")

    def operation(cursor):
        cursor.execute(
            """
            SELECT s.*, c.hourly_rate, c.min_minutes
                   , r.end_time AS reservation_end
            FROM sessions s
            INNER JOIN units u ON u.id = s.unit_id
            INNER JOIN unit_categories c ON c.id = u.category_id
            LEFT JOIN reservations r ON r.id = s.reservation_id
            WHERE s.id = %s
            FOR UPDATE
            """,
            (session_id,),
        )
        session = cursor.fetchone()
        if session is None:
            raise SessionNotFound("Session not found.")
        if session["status"] != ACTIVE_SESSION:
            raise SessionError("Only active sessions can be extended.")
        if minutes < session["min_minutes"]:
            raise SessionError(
                f"The minimum extension is {session['min_minutes']} minutes."
            )
        new_end = session["scheduled_end"] + timedelta(minutes=minutes)
        if (
            session["reservation_id"] is not None
            and session["reservation_end"] is not None
            and new_end > session["reservation_end"]
        ):
            raise SessionError("A reservation-backed session cannot exceed its reservation.")
        _ensure_no_reservation_conflict(
            cursor,
            session["unit_id"],
            session["scheduled_end"],
            new_end,
            exclude_reservation_id=session["reservation_id"],
        )
        extension_cost = (
            Decimal(str(session["hourly_rate"])) * Decimal(minutes) / Decimal(60)
        ).quantize(Decimal("0.01"))
        cursor.execute(
            """
            INSERT INTO session_extensions
                (session_id, minutes, cost, created_by)
            VALUES (%s, %s, %s, %s)
            """,
            (session_id, minutes, extension_cost, admin_id),
        )
        cursor.execute(
            """
            UPDATE sessions
            SET scheduled_end = %s
            WHERE id = %s AND status = 'ACTIVE'
            """,
            (new_end, session_id),
        )
        session["scheduled_end"] = new_end
        return session

    return _transaction(operation)


def get_admin_sessions(current=None):
    current = current or now()
    rows = fetch_all(
        """
        SELECT s.id, s.unit_id, s.user_id, s.customer_name, s.reservation_id,
               s.started_at, s.scheduled_end, s.ended_at, s.status,
               s.hourly_rate_applied, s.total_cost,
               u.name AS unit_name,
               c.name AS category_name, c.unit_type
        FROM sessions s
        INNER JOIN units u ON u.id = s.unit_id
        INNER JOIN unit_categories c ON c.id = u.category_id
        ORDER BY
            CASE s.status
                WHEN 'ACTIVE' THEN 0
                WHEN 'COMPLETED' THEN 1
                ELSE 2
            END,
            CASE WHEN s.status = 'ACTIVE' THEN s.scheduled_end END ASC,
            CASE WHEN s.status = 'COMPLETED' THEN s.ended_at END DESC,
            s.id DESC
        """
    )
    for row in rows:
        row["time_expired"] = (
            row["status"] == ACTIVE_SESSION and current >= row["scheduled_end"]
        )
        row["remaining_seconds"] = (
            max(0, int((row["scheduled_end"] - current).total_seconds()))
            if row["status"] == ACTIVE_SESSION and not row["time_expired"]
            else 0
        )
        row["preparation_until"] = (
            row["ended_at"] + timedelta(seconds=PREPARATION_SECONDS)
            if row["ended_at"] is not None
            else None
        )
        row["is_preparing"] = bool(
            row["preparation_until"] and row["preparation_until"] > current
        )
        row["preparation_remaining_seconds"] = (
            max(0, int((row["preparation_until"] - current).total_seconds()))
            if row["is_preparing"]
            else 0
        )
    return rows


def get_session_customers():
    return fetch_all(
        """
        SELECT id, first_name, last_name, email
        FROM users
        WHERE role = 'customer'
        ORDER BY last_name, first_name, id
        """
    )


def search_session_customers(query, limit=10):
    normalized = query.strip()
    if len(normalized) < 2:
        return []
    escaped = (
        normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    contains = f"%{escaped}%"
    begins = f"{escaped}%"
    exact = normalized.lower()
    return fetch_all(
        """
        SELECT id, first_name, last_name, email
        FROM users
        WHERE role = 'customer'
          AND (
              CONCAT(first_name, ' ', last_name) LIKE %s ESCAPE '\\\\'
              OR email LIKE %s ESCAPE '\\\\'
              OR CAST(id AS CHAR) LIKE %s ESCAPE '\\\\'
          )
        ORDER BY
            CASE
                WHEN LOWER(CONCAT(first_name, ' ', last_name)) = %s THEN 0
                WHEN LOWER(CONCAT(first_name, ' ', last_name)) LIKE %s ESCAPE '\\\\' THEN 1
                WHEN LOWER(CONCAT(first_name, ' ', last_name)) LIKE %s ESCAPE '\\\\' THEN 2
                ELSE 3
            END,
            LOWER(last_name), LOWER(first_name), id
        LIMIT %s
        """,
        (contains, contains, contains, exact, begins.lower(), contains.lower(), limit),
    )


def get_startable_units(current=None):
    current = current or now()
    return fetch_all(
        """
        SELECT u.id, u.name, c.name AS category_name, c.unit_type
        FROM units u
        INNER JOIN unit_categories c ON c.id = u.category_id
        WHERE u.is_active = 1
          AND u.status = 'AVAILABLE'
          AND NOT EXISTS (
              SELECT 1
              FROM sessions s
              WHERE s.unit_id = u.id
                AND s.status = 'ACTIVE'
          )
          AND NOT EXISTS (
              SELECT 1
              FROM sessions s
              WHERE s.unit_id = u.id
                AND s.status = 'COMPLETED'
                AND s.ended_at > %s
          )
        ORDER BY c.unit_type, c.name, u.name
        """,
        (current - timedelta(seconds=PREPARATION_SECONDS),),
    )
