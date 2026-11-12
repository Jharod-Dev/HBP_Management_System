from flask import Blueprint, redirect, render_template, session, url_for

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def landing():
    if session.get("role") == "admin":
        return redirect(url_for("admin.dashboard"))
    if session.get("user_id"):
        return redirect(url_for("customer.dashboard"))
    return render_template("landing.html")
