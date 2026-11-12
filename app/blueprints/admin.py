import mysql.connector
from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from ..services.units import (
    create_unit,
    get_active_categories,
    get_unit,
    get_units_with_availability,
    update_unit,
)
from ..services.reservations import (
    ReservationError,
    ReservationNotFound,
    approve_reservation,
    cancel_reservation,
    get_admin_reservations,
    mark_no_show,
    reject_reservation,
)
from ..services.sessions import (
    SessionError,
    SessionNotFound,
    complete_session,
    extend_session,
    get_admin_sessions,
    search_session_customers,
    get_startable_units,
    start_session,
)
from ..utils.email import send_reservation_decision
from ..utils.auth import role_required
from ..utils.units import UNIT_STATUSES, validate_unit_form

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _render_unit_form(template, unit=None, errors=None, form=None):
    return render_template(
        template,
        unit=unit,
        categories=get_active_categories(),
        statuses=UNIT_STATUSES,
        errors=errors or {},
        form=form or {},
    )


@admin_bp.get("/dashboard")
@role_required("admin")
def dashboard():
    try:
        units = get_units_with_availability()
        sessions = get_admin_sessions()
        pending_reservations = get_admin_reservations("PENDING")
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load the operational overview. Please try again.", "danger")
        units, sessions, pending_reservations = [], [], []

    active_units = [unit for unit in units if unit["is_active"]]
    stats = {
        "active_units": len(active_units),
        "available_units": sum(
            unit["availability_status"] == "AVAILABLE" for unit in active_units
        ),
        "occupied_units": sum(
            unit["availability_status"] == "OCCUPIED" for unit in active_units
        ),
        "preparing_units": sum(
            unit["availability_status"] == "PREPARING" for unit in active_units
        ),
        "active_sessions": sum(item["status"] == "ACTIVE" for item in sessions),
        "expired_sessions": sum(
            item["status"] == "ACTIVE" and item["time_expired"] for item in sessions
        ),
        "pending_reservations": len(pending_reservations),
    }
    return render_template("admin/dashboard.html", stats=stats)


@admin_bp.get("/units")
@role_required("admin")
def units():
    try:
        unit_list = get_units_with_availability()
        categories = get_active_categories()
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load unit information. Please try again.", "danger")
        unit_list, categories = [], []
    return render_template(
        "admin/units.html", units=unit_list, categories=categories
    )


@admin_bp.route("/units/new", methods=("GET", "POST"))
@role_required("admin")
def new_unit():
    if request.method == "POST":
        categories = get_active_categories()
        errors, form = validate_unit_form(request.form, categories)
        if not errors:
            try:
                create_unit(form["name"], form["category_id"], form["description"])
            except (mysql.connector.Error, RuntimeError) as error:
                if isinstance(error, mysql.connector.Error) and error.errno == 1062:
                    errors["name"] = "A unit with that name already exists."
                else:
                    flash("We could not add the unit. Please try again.", "danger")
            else:
                flash("Unit added successfully.", "success")
                return redirect(url_for("admin.units"))
        return _render_unit_form(
            "admin/unit_form.html", errors=errors, form=request.form
        ), 400
    return _render_unit_form("admin/unit_form.html")


@admin_bp.route("/units/<int:unit_id>/edit", methods=("GET", "POST"))
@role_required("admin")
def edit_unit(unit_id):
    try:
        unit = get_unit(unit_id)
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load the unit. Please try again.", "danger")
        return redirect(url_for("admin.units"))
    if unit is None:
        return render_template("errors/404.html"), 404

    if request.method == "POST":
        categories = get_active_categories()
        errors, form = validate_unit_form(request.form, categories)
        if not errors:
            try:
                update_unit(
                    unit_id,
                    form["name"],
                    form["category_id"],
                    form["description"],
                    form["status"],
                    1 if request.form.get("is_active") == "1" else 0,
                )
            except (mysql.connector.Error, RuntimeError) as error:
                if isinstance(error, mysql.connector.Error) and error.errno == 1062:
                    errors["name"] = "A unit with that name already exists."
                else:
                    flash("We could not update the unit. Please try again.", "danger")
            else:
                flash("Unit updated successfully.", "success")
                return redirect(url_for("admin.units"))
        return _render_unit_form(
            "admin/unit_form.html", unit=unit, errors=errors, form=request.form
        ), 400

    return _render_unit_form("admin/unit_form.html", unit=unit)


@admin_bp.post("/units/<int:unit_id>/deactivate")
@role_required("admin")
def deactivate_unit(unit_id):
    try:
        unit = get_unit(unit_id)
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load the unit. Please try again.", "danger")
        return redirect(url_for("admin.units"))
    if unit is None:
        return render_template("errors/404.html"), 404
    try:
        update_unit(
            unit_id,
            unit["name"],
            unit["category_id"],
            unit["description"],
            "UNAVAILABLE",
            0,
        )
    except (mysql.connector.Error, RuntimeError):
        flash("We could not deactivate the unit. Please try again.", "danger")
    else:
        flash("Unit deactivated. Existing records remain intact.", "success")
    return redirect(url_for("admin.units"))


@admin_bp.get("/reservations")
@role_required("admin")
def reservations():
    status = request.args.get("status", "").strip().upper() or None
    reservation_date = request.args.get("date", "").strip() or None
    try:
        reservation_list = get_admin_reservations(status, reservation_date)
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load reservation information. Please try again.", "danger")
        reservation_list = []
    return render_template(
        "admin/reservations.html",
        reservations=reservation_list,
        selected_status=status or "",
        selected_date=reservation_date or "",
    )


def _reservation_action(action, reservation_id):
    try:
        reservation = action(reservation_id, session["user_id"])
    except ReservationNotFound:
        flash("Reservation not found.", "danger")
    except ReservationError as error:
        flash(str(error), "danger")
    except (mysql.connector.Error, RuntimeError):
        flash("We could not update the reservation. Please try again.", "danger")
    else:
        if reservation["status"] in {"CONFIRMED", "REJECTED"}:
            send_reservation_decision(reservation)
        flash(f"Reservation {reservation['status'].lower()}.", "success")
    return redirect(url_for("admin.reservations"))


@admin_bp.post("/reservations/<int:reservation_id>/approve")
@role_required("admin")
def approve(reservation_id):
    return _reservation_action(approve_reservation, reservation_id)


@admin_bp.post("/reservations/<int:reservation_id>/reject")
@role_required("admin")
def reject(reservation_id):
    return _reservation_action(reject_reservation, reservation_id)


@admin_bp.post("/reservations/<int:reservation_id>/cancel")
@role_required("admin")
def cancel(reservation_id):
    return _reservation_action(cancel_reservation, reservation_id)


@admin_bp.post("/reservations/<int:reservation_id>/no-show")
@role_required("admin")
def no_show(reservation_id):
    return _reservation_action(mark_no_show, reservation_id)


@admin_bp.get("/sessions")
@role_required("admin")
def sessions():
    try:
        session_list = get_admin_sessions()
        startable_units = get_startable_units()
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load session information. Please try again.", "danger")
        session_list, startable_units = [], []
    return render_template(
        "admin/sessions.html",
        sessions=session_list,
        startable_units=startable_units,
    )


@admin_bp.get("/sessions/units/availability")
@role_required("admin")
def session_unit_availability():
    try:
        unit_list = get_units_with_availability()
    except (mysql.connector.Error, RuntimeError):
        return jsonify({"error": "Unit availability is unavailable."}), 503
    return jsonify(
        [
            {
                "id": unit["id"],
                "availability_status": unit["availability_status"],
                "preparation_remaining_seconds": unit[
                    "preparation_remaining_seconds"
                ],
            }
            for unit in unit_list
        ]
    )


@admin_bp.get("/sessions/customers/search")
@role_required("admin")
def search_customers():
    query = request.args.get("q", "")
    if len(query.strip()) < 2:
        return jsonify([])
    try:
        customers = search_session_customers(query)
    except (mysql.connector.Error, RuntimeError):
        return jsonify({"error": "Customer search is unavailable."}), 503
    return jsonify(
        [
            {
                "id": customer["id"],
                "name": f"{customer['first_name']} {customer['last_name']}",
                "email": customer["email"],
            }
            for customer in customers
        ]
    )


@admin_bp.post("/sessions/start")
@role_required("admin")
def start():
    try:
        unit_id = int(request.form.get("unit_id", ""))
        reservation_value = request.form.get("reservation_id", "").strip()
        reservation_id = int(reservation_value) if reservation_value else None
        user_id = int(request.form.get("customer_id", ""))
        start_session(
            unit_id=unit_id,
            admin_id=session["user_id"],
            reservation_id=reservation_id,
            user_id=user_id,
        )
    except (TypeError, ValueError):
        flash("Enter valid session details.", "danger")
    except (SessionError, mysql.connector.Error, RuntimeError) as error:
        flash(
            str(error)
            if isinstance(error, SessionError)
            else "We could not start the session. Please try again.",
            "danger",
        )
    else:
        flash("Session started.", "success")
    return redirect(url_for("admin.sessions"))


@admin_bp.post("/sessions/<int:session_id>/extend")
@role_required("admin")
def extend(session_id):
    try:
        minutes = int(request.form.get("minutes", ""))
        extend_session(session_id, session["user_id"], minutes)
    except (TypeError, ValueError):
        flash("Enter a valid extension duration.", "danger")
    except (SessionError, mysql.connector.Error, RuntimeError) as error:
        flash(
            str(error)
            if isinstance(error, SessionError)
            else "We could not extend the session. Please try again.",
            "danger",
        )
    else:
        flash("Session extended.", "success")
    return redirect(url_for("admin.sessions"))


@admin_bp.post("/sessions/<int:session_id>/complete")
@role_required("admin")
def complete(session_id):
    try:
        complete_session(session_id)
    except SessionNotFound:
        flash("Session not found.", "danger")
    except (SessionError, mysql.connector.Error, RuntimeError) as error:
        flash(
            str(error)
            if isinstance(error, SessionError)
            else "We could not complete the session. Please try again.",
            "danger",
        )
    else:
        flash("Session completed. The unit is preparing for 30 seconds.", "success")
    return redirect(url_for("admin.sessions"))
