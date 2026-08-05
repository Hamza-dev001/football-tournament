from flask import Blueprint, render_template, redirect, url_for, request, session
from flask_login import login_user, login_required, logout_user
from .models import User, Match, Group
from . import db
from datetime import datetime
from sqlalchemy import or_

# ✅ Import stage utility functions from routes
from .routes import stage_exists, stage_complete

admin = Blueprint("admin", __name__)

# ✅ TOURNAMENT START DATE
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

    if session.get("override_deadline"):
        return False

    if match.stage != "group":
        return False

    current_matchday = get_current_matchday()

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
# ADMIN OVERVIEW (STAGE CONTROL + QUALIFICATION PREVIEW)
# ==========================================================

@admin.route("/overview")
@login_required
def overview():

    groups = Group.query.all()
    qualified_teams = []
    fourth_placed = []

    for group in groups:

        table = []

        for team in group.teams:

            points = 0
            gf = 0
            ga = 0

            matches = Match.query.filter(
                Match.stage == "group",
                or_(
                    Match.home_team_id == team.id,
                    Match.away_team_id == team.id
                )
            ).all()

            for m in matches:
                if m.home_score is None:
                    continue

                if m.home_team_id == team.id:
                    gf += m.home_score
                    ga += m.away_score
                    if m.home_score > m.away_score:
                        points += 3
                    elif m.home_score == m.away_score:
                        points += 1
                else:
                    gf += m.away_score
                    ga += m.home_score
                    if m.away_score > m.home_score:
                        points += 3
                    elif m.away_score == m.home_score:
                        points += 1

            table.append({
                "team": team,
                "points": points,
                "gd": gf - ga,
                "gf": gf
            })

        table.sort(key=lambda x: (x["points"], x["gd"], x["gf"]), reverse=True)

        qualified_teams.extend(table[:3])

        if len(table) > 3:
            fourth_placed.append(table[3])

    fourth_placed.sort(key=lambda x: (x["points"], x["gd"], x["gf"]), reverse=True)

    best_fourth = fourth_placed[0] if fourth_placed else None

    if best_fourth:
        qualified_teams.append(best_fourth)

    context = {
        "group_exists": stage_exists("group"),
        "group_complete": stage_complete("group"),
        "r16_exists": stage_exists("r16"),
        "qualified_teams": qualified_teams,
        "best_fourth": best_fourth
    }

    return render_template("overview.html", context=context)