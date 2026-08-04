from flask import Blueprint, render_template, redirect, url_for, request, session
from flask_login import login_user, login_required, logout_user
from .models import User, Match
from . import db
from datetime import datetime

admin = Blueprint("admin", __name__)

# ==========================================================
# DEADLINE CHECK
# ==========================================================

def deadline_passed():
    # Allow if override is active
    if session.get("override_deadline"):
        return False

    now = datetime.now()
    deadline = now.replace(hour=10, minute=0, second=0, microsecond=0)

    return now >= deadline


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
    session.pop("override_deadline", None)
    logout_user()
    return redirect(url_for("main.home"))


# ==========================================================
# DASHBOARD
# ==========================================================

@admin.route("/dashboard")
@login_required
def dashboard():

    stages = ["group", "r16", "quarter", "semi", "third", "final"]
    data = {}

    for stage in stages:
        matches = Match.query.filter_by(stage=stage).all()
        data[stage] = matches

    return render_template(
        "admin_dashboard.html",
        data=data,
        deadline_locked=deadline_passed(),
        override_active=session.get("override_deadline", False)
    )


# ==========================================================
# BULK SCORE UPDATE
# ==========================================================

@admin.route("/bulk-update", methods=["POST"])
@login_required
def bulk_update():

    if deadline_passed():
        return "❌ Deadline has passed. Score updates are locked."

    matches = Match.query.all()

    for match in matches:
        home_score = request.form.get(f"home_{match.id}")
        away_score = request.form.get(f"away_{match.id}")

        if home_score != "" and away_score != "":
            match.home_score = int(home_score)
            match.away_score = int(away_score)
            match.is_completed = True

    db.session.commit()
    return redirect(url_for("admin.dashboard"))


# ==========================================================
# ADMIN DEADLINE OVERRIDE
# ==========================================================

@admin.route("/override-deadline", methods=["POST"])
@login_required
def override_deadline():
    session["override_deadline"] = True
    return redirect(url_for("admin.dashboard"))