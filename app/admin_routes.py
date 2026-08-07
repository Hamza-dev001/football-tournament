from flask import Blueprint, render_template, redirect, url_for, request, session
from flask_login import login_user, login_required, logout_user
from sqlalchemy import or_
from datetime import datetime
import random

from .models import User, Match, Group
from . import db
from .routes import stage_exists, stage_complete

admin = Blueprint("admin", __name__)

TOURNAMENT_START = datetime(2026, 8, 4, 10, 0, 0)

# ==========================================================
# MATCHDAY CALCULATION
# ==========================================================

def get_current_matchday():
    now = datetime.now()
    if now < TOURNAMENT_START:
        return 1
    diff = now - TOURNAMENT_START
    matchday = diff.days + 1
    return min(matchday, 3)

# ==========================================================
# MATCH LOCK
# ==========================================================

def is_match_locked(match):

    if session.get("override_deadline"):
        return False

    if match.stage != "group":
        return False

    current_matchday = get_current_matchday()

    if match.matchday > current_matchday:
        return True

    if match.matchday < current_matchday and match.is_completed:
        return True

    return False

# ==========================================================
# LOGIN / LOGOUT
# ==========================================================

@admin.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(
            username=request.form.get("username")
        ).first()

        if user and user.check_password(request.form.get("password")):
            login_user(user)
            return redirect(url_for("admin.dashboard"))

        return "❌ Invalid Credentials"

    return render_template("admin_login.html")

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
        data[stage] = (
            Match.query
            .filter_by(stage=stage)
            .order_by(Match.matchday, Match.id)
            .all()
        )

    return render_template(
        "admin_dashboard.html",
        data=data,
        current_matchday=get_current_matchday(),
        override_active=session.get("override_deadline", False)
    )

# ==========================================================
# BULK UPDATE
# ==========================================================

@admin.route("/bulk-update", methods=["POST"])
@login_required
def bulk_update():

    matches = Match.query.all()

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
# HELPER: GET GROUP QUALIFIERS
# ==========================================================

def get_group_qualifiers():

    groups = Group.query.all()
    qualified = []

    for group in groups:
        table = []

        for team in group.teams:
            points = gf = ga = 0

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
                "group": group.name,
                "points": points,
                "gd": gf - ga,
                "gf": gf
            })

        table.sort(key=lambda x: (x["points"], x["gd"], x["gf"]), reverse=True)

        qualified.extend(table[:3])

    return qualified

# ==========================================================
# GENERATE ROUND OF 16
# ==========================================================

@admin.route("/generate-r16")
@login_required
def generate_r16():

    if stage_exists("r16"):
        return "❌ R16 already generated."

    if not stage_complete("group"):
        return "❌ Complete group stage first."

    qualified = get_group_qualifiers()
    random.shuffle(qualified)

    while len(qualified) >= 2:
        team1 = qualified.pop(0)
        for i, opponent in enumerate(qualified):
            if opponent["group"] != team1["group"]:
                db.session.add(Match(
                    home_team_id=team1["team"].id,
                    away_team_id=opponent["team"].id,
                    stage="r16",
                    matchday=1
                ))
                qualified.pop(i)
                break

    db.session.commit()
    return redirect(url_for("admin.dashboard"))

# ==========================================================
# GENERATE NEXT KNOCKOUT STAGE
# ==========================================================

def generate_next_stage(current_stage, next_stage):

    if stage_exists(next_stage):
        return f"❌ {next_stage} already generated."

    if not stage_complete(current_stage):
        return f"❌ Complete {current_stage} first."

    matches = Match.query.filter_by(stage=current_stage).all()

    winners = []

    for m in matches:
        if m.home_score > m.away_score:
            winners.append(m.home_team_id)
        else:
            winners.append(m.away_team_id)

    for i in range(0, len(winners), 2):
        db.session.add(Match(
            home_team_id=winners[i],
            away_team_id=winners[i+1],
            stage=next_stage,
            matchday=1
        ))

    db.session.commit()
    return redirect(url_for("admin.dashboard"))

@admin.route("/generate-quarter")
@login_required
def generate_quarter():
    return generate_next_stage("r16", "quarter")

@admin.route("/generate-semi")
@login_required
def generate_semi():
    return generate_next_stage("quarter", "semi")

@admin.route("/generate-final")
@login_required
def generate_final():
    return generate_next_stage("semi", "final")

@admin.route("/generate-third")
@login_required
def generate_third():
    return generate_next_stage("semi", "third")