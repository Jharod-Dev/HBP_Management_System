import mysql.connector
from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from ..services.reservations import (
    ReservationError,
    ReservationNotFound,
    cancel_customer_reservation,
    create_reservation,
    get_customer_reservations,
    get_reservable_units,
)
from ..utils.auth import login_required
from ..utils.time import now
from ..services.units import get_units_with_availability
from ..services.pos import (
    POSNotFound,
    POSValidationError,
    create_order,
    get_customer_active_sessions,
    get_customer_orders,
    get_products,
    update_order_status,
)

customer_bp = Blueprint("customer", __name__, url_prefix="/customer")


@customer_bp.get("/dashboard")
@login_required
def dashboard():
    try:
        reservations = get_customer_reservations(session["user_id"])
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load your reservation activity. Please try again.", "danger")
        reservations = []
    try:
        products = get_products()
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load the snacks and drinks catalog. Please try again.", "danger")
        products = []
    return render_template(
        "customer/dashboard.html",
        reservations=reservations,
        current_reservations=[
            item
            for item in reservations
            if item["status"] in {"PENDING", "CONFIRMED", "ACTIVE"}
        ],
        customer_name=session.get("first_name") or "there",
        dashboard_products=products[:3],
        product_count=len(products),
    )


@customer_bp.get("/shop")
@login_required
def shop():
    try:
        products = get_products()
        active_sessions = get_customer_active_sessions(session["user_id"])
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load the product catalog. Please try again.", "danger")
        products, active_sessions = [], []
    return render_template(
        "customer/shop.html", products=products, active_sessions=active_sessions
    )


@customer_bp.post("/orders")
@login_required
def create_customer_order():
    items = [
        (key[len("quantity_"):], value)
        for key, value in request.form.items()
        if key.startswith("quantity_") and value
    ]
    try:
        session_id = int(request.form.get("session_id", ""))
        order_id = create_order(session["user_id"], session_id, items)
    except (TypeError, ValueError):
        flash("Select an active session and at least one product.", "danger")
        return redirect(url_for("customer.shop"))
    except POSValidationError as error:
        flash(str(error), "danger")
        return redirect(url_for("customer.shop"))
    except (mysql.connector.Error, RuntimeError):
        flash("We could not submit your order. Please try again.", "danger")
        return redirect(url_for("customer.shop"))
    flash(f"Order #{order_id} submitted for preparation.", "success")
    return redirect(url_for("customer.orders"))


@customer_bp.get("/orders")
@login_required
def orders():
    try:
        order_list = get_customer_orders(session["user_id"])
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load your order history. Please try again.", "danger")
        order_list = []
    return render_template("customer/orders.html", orders=order_list)


@customer_bp.post("/orders/<int:order_id>/cancel")
@login_required
def cancel_order(order_id):
    try:
        update_order_status(order_id, "CANCELLED", user_id=session["user_id"])
    except POSNotFound:
        flash("Order not found.", "danger")
    except POSValidationError as error:
        flash(str(error), "danger")
    except (mysql.connector.Error, RuntimeError):
        flash("We could not cancel the order. Please try again.", "danger")
    else:
        flash("Order cancelled and stock restored.", "success")
    return redirect(url_for("customer.orders"))


@customer_bp.get("/units")
@login_required
def units():
    try:
        unit_list = get_units_with_availability()
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load unit availability. Please try again.", "danger")
        unit_list = []
    return render_template("customer/units.html", units=unit_list)


@customer_bp.get("/units/availability")
@login_required
def unit_availability():
    try:
        unit_list = get_units_with_availability()
    except (mysql.connector.Error, RuntimeError):
        return jsonify({"error": "Unit availability is unavailable."}), 503
    return jsonify(
        [
            {
                "id": unit["id"],
                "availability_status": unit["availability_status"],
                "scheduled_end": (
                    unit["active_scheduled_end"].isoformat()
                    if unit["active_scheduled_end"] is not None
                    else None
                ),
                "remaining_seconds": unit["active_remaining_seconds"],
                "preparation_remaining_seconds": unit[
                    "preparation_remaining_seconds"
                ],
            }
            for unit in unit_list
        ]
    )


@customer_bp.get("/reservations")
@login_required
def reservations():
    try:
        reservation_list = get_customer_reservations(session["user_id"])
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load your reservations. Please try again.", "danger")
        reservation_list = []
    return render_template("customer/reservations.html", reservations=reservation_list)


@customer_bp.route("/reservations/new", methods=("GET", "POST"))
@login_required
def new_reservation():
    form = request.form if request.method == "POST" else {}
    errors = {}
    selected_start = None
    selected_end = None
    try:
        if form.get("start_time") and form.get("duration"):
            selected_start = datetime.fromisoformat(form["start_time"])
            selected_end = selected_start + timedelta(hours=int(form["duration"]))
    except (TypeError, ValueError):
        selected_start = selected_end = None
    try:
        units = get_reservable_units(selected_start, selected_end)
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load reservable units. Please try again.", "danger")
        units = []

    if request.method == "POST":
        try:
            unit_id = int(form.get("unit_id", ""))
            duration = int(form.get("duration", ""))
            start_at = datetime.fromisoformat(form.get("start_time", ""))
            reservation_id = create_reservation(
                session["user_id"], unit_id, start_at, duration, current=now()
            )
        except (TypeError, ValueError):
            errors["form"] = "Select a valid unit, start time, and duration."
        except (ReservationError, mysql.connector.Error, RuntimeError) as error:
            errors["form"] = str(error) if isinstance(error, ReservationError) else (
                "We could not create the reservation. Please try again."
            )
        else:
            flash(
                "Reservation request submitted and is waiting for administrator approval.",
                "success",
            )
            return redirect(url_for("customer.reservations"))

    return render_template(
        "customer/reservation_form.html",
        units=units,
        errors=errors,
        form=form,
    ), 400 if errors else 200


@customer_bp.post("/reservations/<int:reservation_id>/cancel")
@login_required
def cancel_reservation(reservation_id):
    try:
        cancel_customer_reservation(session["user_id"], reservation_id, current=now())
    except ReservationNotFound:
        flash("Reservation not found.", "danger")
    except ReservationError as error:
        flash(str(error), "danger")
    except (mysql.connector.Error, RuntimeError):
        flash("We could not cancel the reservation. Please try again.", "danger")
    else:
        flash("Reservation cancelled.", "success")
    return redirect(url_for("customer.reservations"))
