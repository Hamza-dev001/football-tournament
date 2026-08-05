from flask import Blueprint, render_template, redirect, url_for, request, session
from flask_login import login_user, login_required, logout_user
from .models import User, Match
from . import db
from datetime import datetime

admin = Blueprint("admin", __name__)

# ✅ TOURNAMENT START DATE (MAKE SURE YEAR IS CORRECT)
TOURNAMENT_START = datetime(2026, 8, 4, 10, 0, 0)


# ==========================================================
# CALCULATE CURRENT MATCHDAY
# ==========================================================

def get_current_matchday():
    now = datetime.now()

    if now < TOURNAMENT_START:
        return 1

    diff = now - TOURNAMENT_START
    days_passed = diff.days

    current_matchday = days_passed + 1

    if current_matchday > 3:
        current_matchday = 3

    return current_matchday


# ==========================================================
# CHECK IF MATCH IS LOCKED
# ==========================================================

def is_match_locked(match):

    # Override bypasses lock
    if session.get("override_deadline"):
        return False

    # Only apply locking for group stage
    if match.stage != "group":
        return False

    current_matchday = get_current_matchday()

    # Lock everything except active matchday
    return match.matchday != current_matchday


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

    current_matchday = get_current_matchday()

    for stage in stages:
        matches = (
            Match.query
            .filter_by(stage=stage)
            .order_by(Match.matchday, Match.id)
            .all()
        )
        data[stage] = matches

    return render_template(
        "admin_dashboard.html",
        data=data,
        current_matchday=current_matchday,
        override_active=session.get("override_deadline", False)
    )


# ==========================================================
# BULK SCORE UPDATE
# ==========================================================

@admin.route("/bulk-update", methods=["POST"])
@login_required
def bulk_update():

    matches = Match.query.order_by(Match.matchday, Match.id).all()

    for match in matches:

        # Skip locked matches
        if is_match_locked(match):
            continue

        home_score = request.form.get(f"home_{match.id}")
        away_score = request.form.get(f"away_{match.id}")

        if home_score != "" and away_score != "":
            match.home_score = int(home_score)
            match.away_score = int(away_score)
            match.is_completed = True

    db.session.commit()
    return redirect(url_for("admin.dashboard"))


# ==========================================================
# DEADLINE OVERRIDE
# ==========================================================

@admin.route("/override-deadline", methods=["POST"])
@login_required
def override_deadline():
    session["override_deadline"] = True
    return redirect(url_for("admin.dashboard"))


# ==========================================================
# ADMIN OVERVIEW (STAGE CONTROL)
# ==========================================================

@admin.route("/overview")
@login_required
def overview():
    return render_template("overview.html")