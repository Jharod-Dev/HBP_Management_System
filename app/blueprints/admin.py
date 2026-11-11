import mysql.connector
from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..services.units import (
    create_unit,
    get_active_categories,
    get_unit,
    get_units_with_availability,
    update_unit,
)
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
    return render_template("admin/dashboard.html")


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
