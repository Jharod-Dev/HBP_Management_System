import re

import mysql.connector
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import execute, fetch_one

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _registration_errors(form):
    errors = {}
    required_fields = ("first_name", "last_name", "email", "password", "confirm_password")
    for field in required_fields:
        if not form.get(field, "").strip():
            errors[field] = "This field is required."

    email = form.get("email", "").strip()
    if email and not EMAIL_PATTERN.fullmatch(email):
        errors["email"] = "Enter a valid email address."

    password = form.get("password", "")
    if password and password != form.get("confirm_password", ""):
        errors["confirm_password"] = "Passwords do not match."
    return errors


@auth_bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        form = request.form
        errors = _registration_errors(form)
        if not errors:
            email = form["email"].strip().lower()
            try:
                if fetch_one("SELECT id FROM users WHERE email = %s", (email,)):
                    errors["email"] = "An account with that email already exists."
                else:
                    execute(
                        """
                        INSERT INTO users
                            (first_name, last_name, email, password_hash, role)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            form["first_name"].strip(),
                            form["last_name"].strip(),
                            email,
                            generate_password_hash(form["password"]),
                            "customer",
                        ),
                    )
            except (mysql.connector.Error, RuntimeError) as error:
                if isinstance(error, mysql.connector.Error) and error.errno == 1062:
                    errors["email"] = "An account with that email already exists."
                else:
                    flash("We could not create your account. Please try again.", "danger")
            else:
                if not errors:
                    flash("Your account has been created. Please log in.", "success")
                    return redirect(url_for("auth.login"))

        return render_template("auth/register.html", errors=errors, form=form), 400

    return render_template("auth/register.html", errors={}, form={})


@auth_bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = None
        if email and password:
            try:
                user = fetch_one(
                    """
                    SELECT id, first_name, last_name, email, password_hash, role
                    FROM users
                    WHERE email = %s
                    """,
                    (email,),
                )
            except (mysql.connector.Error, RuntimeError):
                user = None

        try:
            password_matches = user is not None and check_password_hash(
                user["password_hash"], password
            )
        except (TypeError, ValueError):
            password_matches = False

        if not password_matches:
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html", form={"email": email}), 401

        session.clear()
        session.update(
            user_id=user["id"],
            role=user["role"],
            first_name=user["first_name"],
            last_name=user["last_name"],
        )
        if user["role"] == "admin":
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("customer.dashboard"))

    return render_template("auth/login.html", form={})


@auth_bp.post("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.landing"))
