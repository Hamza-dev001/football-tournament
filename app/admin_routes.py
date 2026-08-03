from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_user, login_required, logout_user
from .models import User, Match
from . import db

admin = Blueprint("admin", __name__)


# ==========================================================
# LOGIN
# ==========================================================
@admin.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("admin.dashboard"))

        return "❌ Invalid Credentials"

    return render_template("admin_login.html")


# ==========================================================
# LOGOUT
# ==========================================================
@admin.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.home"))


# ==========================================================
# DASHBOARD (BULK SCORE ENTRY)
# ==========================================================
@admin.route("/dashboard")
@login_required
def dashboard():

    stages = ["group", "r16", "quarter", "semi", "final", "third"]

    data = {}

    for stage in stages:
        matches = Match.query.filter_by(stage=stage).all()
        data[stage] = matches

    return render_template("admin_dashboard.html", data=data)


# ==========================================================
# BULK SCORE UPDATE
# ==========================================================
@admin.route("/bulk-update", methods=["POST"])
@login_required
def bulk_update():

    matches = Match.query.all()

    for match in matches:

        home_score = request.form.get(f"home_{match.id}")
        away_score = request.form.get(f"away_{match.id}")

        if home_score and away_score:
            match.home_score = int(home_score)
            match.away_score = int(away_score)
            match.is_completed = True

    db.session.commit()
    return redirect(url_for("admin.dashboard"))