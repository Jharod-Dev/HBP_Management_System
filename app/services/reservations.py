from datetime import datetime, time, timedelta

from ..db import fetch_all
from ..utils.time import now


OPENING_TIME = time(8, 0)
CLOSING_TIME = time(22, 0)
MINIMUM_HOURS = 1
MAXIMUM_HOURS = 3
CANCELLATION_MINUTES = 30
NO_SHOW_GRACE_MINUTES = 5
BLOCKING_STATUSES = ("PENDING", "CONFIRMED")
TRANSITIONS = {
    "PENDING": {"CONFIRMED", "REJECTED", "CANCELLED"},
    "CONFIRMED": {"CANCELLED", "NO_SHOW", "COMPLETED"},
}


class ReservationError(ValueError):
    pass


class ReservationNotFound(ReservationError):
    pass


class ReservationConflict(ReservationError):
    pass


def _validate_schedule(start_at, duration_hours, current):
    if current.weekday() == 6:
        raise ReservationError("Reservations are unavailable on Sundays.")
    if not OPENING_TIME <= current.time() < CLOSING_TIME:
        raise ReservationError("Reservations can only be submitted during operating hours.")
    if start_at.date() != current.date():
        raise ReservationError("Reservations are available for today only.")
    if start_at <= current:
        raise ReservationError("The reservation start time must be in the future.")
    if duration_hours not in (1, 2, 3):
        raise ReservationError("Reservation duration must be 1, 2, or 3 hours.")
    end_at = start_at + timedelta(hours=duration_hours)
    if start_at.time() < OPENING_TIME or end_at.time() > CLOSING_TIME:
        raise ReservationError("Reservations must fit within 8:00 AM to 10:00 PM.")
    return end_at


def _lock_reservable_unit(cursor, unit_id):
    cursor.execute(
        """
        SELECT u.id, u.name, u.description, u.status, u.is_active,
               c.name AS category_name, c.unit_type, c.reservable
        FROM units u
        INNER JOIN unit_categories c ON c.id = u.category_id
        WHERE u.id = %s
        FOR UPDATE
        """,
        (unit_id,),
    )
    unit = cursor.fetchone()
    if unit is None:
        raise ReservationError("The selected unit does not exist.")
    if not unit["is_active"] or unit["status"] == "UNAVAILABLE":
        raise ReservationError("The selected unit is unavailable.")
    if not unit["reservable"]:
        raise ReservationError("The selected unit is not available for online reservations.")
    return unit


def _ensure_no_conflict(cursor, unit_id, start_at, end_at, exclude_id=None):
    reservation_sql = """
        SELECT id
        FROM reservations
        WHERE unit_id = %s
          AND status IN (%s, %s)
          AND start_time < %s
          AND end_time > %s
    """
    params = [unit_id, *BLOCKING_STATUSES, end_at, start_at]
    if exclude_id is not None:
        reservation_sql += " AND id <> %s"
        params.append(exclude_id)
    reservation_sql += " LIMIT 1"
    cursor.execute(reservation_sql, tuple(params))
    if cursor.fetchone() is not None:
        raise ReservationConflict("The selected time overlaps another reservation.")

    cursor.execute(
        """
        SELECT id
        FROM sessions
        WHERE unit_id = %s
          AND status = 'ACTIVE'
          AND started_at < %s
          AND scheduled_end > %s
        LIMIT 1
        """,
        (unit_id, end_at, start_at),
    )
    if cursor.fetchone() is not None:
        raise ReservationConflict("The selected time overlaps an active session.")


def _execute_transaction(operation):
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


def create_reservation(user_id, unit_id, start_at, duration_hours, current=None):
    current = current or now()
    end_at = _validate_schedule(start_at, duration_hours, current)

    def operation(cursor):
        _lock_reservable_unit(cursor, unit_id)
        _ensure_no_conflict(cursor, unit_id, start_at, end_at)
        cursor.execute(
            """
            INSERT INTO reservations
                (user_id, unit_id, start_time, end_time, status)
            VALUES (%s, %s, %s, %s, 'PENDING')
            """,
            (user_id, unit_id, start_at, end_at),
        )
        return cursor.lastrowid

    return _execute_transaction(operation)


def get_reservable_units(start_at=None, end_at=None):
    current = now()
    params = [current - timedelta(seconds=30)]
    if start_at is None or end_at is None:
        occupied_condition = """
            EXISTS (
                SELECT 1 FROM sessions s
                WHERE s.unit_id = u.id AND s.status = 'ACTIVE'
            )
        """
        reserved_condition = "0"
    else:
        occupied_condition = """
            EXISTS (
                SELECT 1 FROM sessions s
                WHERE s.unit_id = u.id
                  AND s.status = 'ACTIVE'
                  AND s.started_at < %s
                  AND s.scheduled_end > %s
            )
        """
        reserved_condition = """
            EXISTS (
                SELECT 1 FROM reservations r
                WHERE r.unit_id = u.id
                  AND r.status IN ('PENDING', 'CONFIRMED')
                  AND r.start_time < %s
                  AND r.end_time > %s
            )
        """
        params.extend((end_at, start_at, end_at, start_at))
    query = """
        SELECT
            u.id, u.name, u.description, c.name AS category_name,
            c.unit_type, u.status AS operational_status, u.is_active,
            CASE
                WHEN u.status = 'UNAVAILABLE' OR u.is_active = 0 THEN 'UNAVAILABLE'
                WHEN EXISTS (
                    SELECT 1 FROM sessions s
                    WHERE s.unit_id = u.id
                      AND s.status = 'COMPLETED'
                      AND s.ended_at IS NOT NULL
                      AND s.ended_at > %s
                ) THEN 'PREPARING'
                WHEN {occupied_condition} THEN 'OCCUPIED'
                WHEN {reserved_condition} THEN 'RESERVED'
                ELSE 'AVAILABLE'
            END AS availability_status
        FROM units u
        INNER JOIN unit_categories c ON c.id = u.category_id
        WHERE u.is_active = 1 AND c.reservable = 1
        ORDER BY c.unit_type, c.name, u.name
    """.format(
        occupied_condition=occupied_condition,
        reserved_condition=reserved_condition,
    )
    return fetch_all(query, tuple(params))


def get_customer_reservations(user_id):
    return fetch_all(
        """
        SELECT r.id, r.start_time, r.end_time, r.status, r.created_at,
               u.name AS unit_name, c.name AS category_name, c.unit_type,
               TIMESTAMPDIFF(MINUTE, r.start_time, r.end_time) AS duration_minutes
        FROM reservations r
        INNER JOIN units u ON u.id = r.unit_id
        INNER JOIN unit_categories c ON c.id = u.category_id
        WHERE r.user_id = %s
        ORDER BY r.start_time DESC
        """,
        (user_id,),
    )


def get_admin_reservations(status=None, reservation_date=None):
    clauses = []
    params = []
    if status:
        clauses.append("r.status = %s")
        params.append(status)
    if reservation_date:
        clauses.append("DATE(r.start_time) = %s")
        params.append(reservation_date)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return fetch_all(
        f"""
        SELECT r.id, r.start_time, r.end_time, r.status, r.created_at,
               u.name AS unit_name, c.name AS category_name, c.unit_type,
               usr.first_name, usr.last_name, usr.email,
               r.unit_id, r.user_id,
               TIMESTAMPDIFF(MINUTE, r.start_time, r.end_time) AS duration_minutes
        FROM reservations r
        INNER JOIN units u ON u.id = r.unit_id
        INNER JOIN unit_categories c ON c.id = u.category_id
        INNER JOIN users usr ON usr.id = r.user_id
        {where}
        ORDER BY r.start_time ASC
        """,
        tuple(params),
    )


def _get_locked_reservation(cursor, reservation_id):
    cursor.execute(
        """
        SELECT r.*, u.name AS unit_name, usr.first_name, usr.last_name, usr.email
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
        raise ReservationNotFound("Reservation not found.")
    return reservation


def _get_reservation(cursor, reservation_id):
    cursor.execute(
        """
        SELECT r.*, u.name AS unit_name, usr.first_name, usr.last_name, usr.email
        FROM reservations r
        INNER JOIN units u ON u.id = r.unit_id
        INNER JOIN users usr ON usr.id = r.user_id
        WHERE r.id = %s
        """,
        (reservation_id,),
    )
    reservation = cursor.fetchone()
    if reservation is None:
        raise ReservationNotFound("Reservation not found.")
    return reservation


def _change_status(
    reservation_id,
    target_status,
    require_grace=False,
    decided_by=None,
    current=None,
):
    current = current or now()

    def operation(cursor):
        reservation = (
            _get_reservation(cursor, reservation_id)
            if target_status == "CONFIRMED"
            else _get_locked_reservation(cursor, reservation_id)
        )
        current_status = reservation["status"]
        if target_status not in TRANSITIONS.get(current_status, set()):
            raise ReservationError(
                f"Cannot change a {current_status} reservation to {target_status}."
            )
        if require_grace:
            validate_no_show_time(reservation["start_time"], current)
        if target_status == "CONFIRMED":
            _lock_reservable_unit(cursor, reservation["unit_id"])
            reservation = _get_locked_reservation(cursor, reservation_id)
            if reservation["status"] != "PENDING":
                raise ReservationError(
                    f"Cannot change a {reservation['status']} reservation to CONFIRMED."
                )
            _ensure_no_conflict(
                cursor,
                reservation["unit_id"],
                reservation["start_time"],
                reservation["end_time"],
                exclude_id=reservation_id,
            )
        if decided_by is None:
            cursor.execute(
                "UPDATE reservations SET status = %s WHERE id = %s",
                (target_status, reservation_id),
            )
        else:
            cursor.execute(
                """
                UPDATE reservations
                SET status = %s, decided_by = %s, decided_at = %s
                WHERE id = %s
                """,
                (target_status, decided_by, current, reservation_id),
            )
        reservation["status"] = target_status
        return reservation

    return _execute_transaction(operation)


def approve_reservation(reservation_id, decided_by=None):
    return _change_status(reservation_id, "CONFIRMED", decided_by=decided_by)


def reject_reservation(reservation_id, decided_by=None):
    return _change_status(reservation_id, "REJECTED", decided_by=decided_by)


def cancel_reservation(reservation_id, decided_by=None):
    return _change_status(reservation_id, "CANCELLED", decided_by=decided_by)


def cancel_customer_reservation(user_id, reservation_id, current=None):
    current = current or now()

    def operation(cursor):
        reservation = _get_locked_reservation(cursor, reservation_id)
        if reservation["user_id"] != user_id:
            raise ReservationNotFound("Reservation not found.")
        if reservation["status"] not in {"PENDING", "CONFIRMED"}:
            raise ReservationError("This reservation cannot be cancelled.")
        if reservation["start_time"] - current < timedelta(
            minutes=CANCELLATION_MINUTES
        ):
            raise ReservationError(
                "Reservations can only be cancelled at least 30 minutes before start."
            )
        cursor.execute(
            "UPDATE reservations SET status = 'CANCELLED' WHERE id = %s",
            (reservation_id,),
        )
        reservation["status"] = "CANCELLED"
        return reservation

    return _execute_transaction(operation)


def validate_no_show_time(start_time, current):
    if current < start_time + timedelta(minutes=NO_SHOW_GRACE_MINUTES):
        raise ReservationError("The five-minute no-show grace period has not expired.")


def mark_no_show(reservation_id, decided_by=None, current=None):
    return _change_status(
        reservation_id,
        "NO_SHOW",
        require_grace=True,
        decided_by=decided_by,
        current=current,
    )
