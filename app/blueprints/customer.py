import mysql.connector
from flask import Blueprint, flash, render_template

from ..services.units import get_units_with_availability
from ..utils.auth import login_required

customer_bp = Blueprint("customer", __name__, url_prefix="/customer")


@customer_bp.get("/dashboard")
@login_required
def dashboard():
    return render_template("customer/dashboard.html")


@customer_bp.get("/units")
@login_required
def units():
    try:
        unit_list = get_units_with_availability()
    except (mysql.connector.Error, RuntimeError):
        flash("We could not load unit availability. Please try again.", "danger")
        unit_list = []
    return render_template("customer/units.html", units=unit_list)
