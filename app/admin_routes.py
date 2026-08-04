from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_user, login_required, logout_user
from .models import User, Match
from . import db
import random

admin = Blueprint("admin", __name__)

# ==========================================================
# STAGE UTILITIES
# ==========================================================

def stage_exists(stage_name):
    return Match.query.filter_by(stage=stage_name).count() > 0

def stage_complete(stage_name):
    matches = Match.query.filter_by(stage=stage_name).all()
    if not matches:
        return False
    return all(m.is_completed for m in matches)

def tournament_finished():
    return stage_complete("final")


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
# ADMIN DASHBOARD (SCORE ENTRY)
# ==========================================================

@admin.route("/dashboard")
@login_required
def dashboard():

    stages = ["group", "r16", "quarter", "semi", "third", "final"]
    data = {}

    for stage in stages:
        matches = Match.query.filter_by(stage=stage).all()
        data[stage] = matches

    return render_template("admin_dashboard.html", data=data)


# ==========================================================
# ADMIN OVERVIEW (STAGE CONTROL)
# ==========================================================

@admin.route("/overview")
@login_required
def overview():

    context = {
        "group_complete": stage_complete("group"),
        "r16_exists": stage_exists("r16"),
        "r16_complete": stage_complete("r16"),
        "quarter_exists": stage_exists("quarter"),
        "quarter_complete": stage_complete("quarter"),
        "semi_exists": stage_exists("semi"),
        "semi_complete": stage_complete("semi"),
        "final_exists": stage_exists("final"),
        "tournament_finished": tournament_finished()
    }

    return render_template("overview.html", context=context)


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

        if home_score != "" and away_score != "":
            match.home_score = int(home_score)
            match.away_score = int(away_score)
            match.is_completed = True

    db.session.commit()
    return redirect(url_for("admin.dashboard"))