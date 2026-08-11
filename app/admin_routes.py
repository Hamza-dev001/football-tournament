from .seed_teams import seed_teams
from flask import Blueprint, render_template, redirect, url_for, request, session
from flask_login import login_user, login_required, logout_user
from sqlalchemy import or_
from datetime import datetime
import random

from .models import User, Match, Group, Season, Team, SeasonAssignment, get_active_season
from . import db
from .routes import stage_exists, stage_complete
from .services.elo_engine import EloEngine
from .services.season_manager import SeasonManager
from .services.season_setup import suggest_season_config, MIN_TEAMS_PER_SEASON

admin = Blueprint("admin", __name__)


# ==========================================================
# MATCHDAY CALCULATION (per active season now, not hardcoded)
# ==========================================================

def get_current_matchday():
    season = get_active_season()
    if not season or not season.started_at:
        return 1
    now = datetime.now()
    if now < season.started_at:
        return 1
    diff = now - season.started_at
    return min(diff.days + 1, 3)


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
        user = User.query.filter_by(username=request.form.get("username")).first()
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
    season = get_active_season()
    stages = ["group", "r16", "quarter", "semi", "third", "final"]
    data = {}

    if season:
        for stage in stages:
            data[stage] = (
                Match.query
                .filter_by(stage=stage, season_id=season.id)
                .order_by(Match.matchday, Match.id)
                .all()
            )

    return render_template(
        "admin_dashboard.html",
        data=data,
        season=season,
        current_matchday=get_current_matchday(),
        override_active=session.get("override_deadline", False)
    )


# ==========================================================
# BULK SCORE UPDATE — now triggers dual ELO processing
# ==========================================================

@admin.route("/bulk-update", methods=["POST"])
@login_required
def bulk_update():
    season = get_active_season()
    matches = Match.query.filter_by(season_id=season.id).all()
    touched = []

    for match in matches:
        if is_match_locked(match):
            continue

        home_score = request.form.get(f"home_{match.id}")
        away_score = request.form.get(f"away_{match.id}")

        if home_score != "" and away_score != "":
            match.home_score = int(home_score)
            match.away_score = int(away_score)
            match.is_completed = True
            touched.append(match)

    db.session.commit()

    for match in touched:
        EloEngine.process_match(match)

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
# SEASON MANAGEMENT
# ==========================================================

@admin.route("/seasons")
@login_required
def list_seasons():
    seasons = Season.query.order_by(Season.season_number.desc()).all()
    return render_template("admin_seasons.html", seasons=seasons)


@admin.route("/seasons/create", methods=["POST"])
@login_required
def create_season():
    name = request.form.get("name")
    SeasonManager.create_season(name)
    return redirect(url_for("admin.list_seasons"))


@admin.route("/seasons/<int:season_id>/activate")
@login_required
def activate_season(season_id):
    SeasonManager.activate_season(season_id)
    return redirect(url_for("admin.list_seasons"))


@admin.route("/seasons/<int:season_id>/complete")
@login_required
def complete_season(season_id):
    SeasonManager.complete_season(season_id)
    return redirect(url_for("admin.list_seasons"))


# ==========================================================
# SEASON ASSIGNMENT SCREEN — "assign username to club"
# ==========================================================

@admin.route("/season-entries", methods=["GET", "POST"])
@login_required
def season_entries():
    season = get_active_season()
    if not season:
        return "❌ No active season."

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        team_id = request.form.get("team_id")
        try:
            SeasonManager.assign_player_to_club(season.id, username, int(team_id))
        except ValueError as e:
            return f"❌ {e}"
        return redirect(url_for("admin.season_entries"))

    entries = SeasonAssignment.query.filter_by(season_id=season.id).all()
    available_clubs = SeasonManager.get_unassigned_clubs(season.id)

    suggested = None
    if len(entries) >= MIN_TEAMS_PER_SEASON:
        suggested = suggest_season_config(len(entries))

    return render_template(
        "admin_season_entries.html",
        season=season, entries=entries,
        available_clubs=available_clubs, suggested=suggested,
        min_teams=MIN_TEAMS_PER_SEASON
    )


@admin.route("/season-entries/<int:assignment_id>/remove")
@login_required
def remove_season_entry(assignment_id):
    SeasonManager.remove_assignment(assignment_id)
    return redirect(url_for("admin.season_entries"))


@admin.route("/season-entries/finalize", methods=["POST"])
@login_required
def finalize_season_entries():
    season = get_active_season()
    entries = SeasonAssignment.query.filter_by(season_id=season.id).all()

    if len(entries) < MIN_TEAMS_PER_SEASON:
        return f"❌ Need at least {MIN_TEAMS_PER_SEASON} teams assigned. Currently: {len(entries)}."

    SeasonManager.finalize_season_config(season.id, len(entries))
    return redirect(url_for("admin.season_entries"))


# ==========================================================
# HELPER: BUILD QUALIFIERS (TOP N + WILDCARDS)
# ==========================================================

def build_group_qualifiers():
    season = get_active_season()
    groups = Group.query.filter_by(season_id=season.id).all()

    qualified = []
    leftovers = []
    qualifiers_n = season.qualifiers_per_group or 3
    wildcards_n = season.wildcard_slots or 0

    for group in groups:
        table = []
        for assignment in group.assignments:
            points = gf = ga = 0
            matches = Match.query.filter(
                Match.stage == "group", Match.season_id == season.id,
                or_(
                    Match.home_assignment_id == assignment.id,
                    Match.away_assignment_id == assignment.id
                )
            ).all()

            for m in matches:
                if m.home_score is None:
                    continue
                if m.home_assignment_id == assignment.id:
                    gf += m.home_score; ga += m.away_score
                    if m.home_score > m.away_score: points += 3
                    elif m.home_score == m.away_score: points += 1
                else:
                    gf += m.away_score; ga += m.home_score
                    if m.away_score > m.home_score: points += 3
                    elif m.away_score == m.home_score: points += 1

            table.append({
                "assignment": assignment, "group": group.name,
                "points": points, "gd": gf - ga, "gf": gf
            })

        table.sort(key=lambda x: (x["points"], x["gd"], x["gf"]), reverse=True)
        qualified.extend(table[:qualifiers_n])
        leftovers.extend(table[qualifiers_n:])

    if wildcards_n > 0 and leftovers:
        leftovers.sort(key=lambda x: (x["points"], x["gd"], x["gf"]), reverse=True)
        qualified.extend(leftovers[:wildcards_n])

    return qualified


# ==========================================================
# ADMIN OVERVIEW
# ==========================================================

@admin.route("/overview")
@login_required
def overview():
    context = {
        "qualified_teams": build_group_qualifiers(),
        "group_complete": stage_complete("group"),
        "r16_exists": stage_exists("r16")
    }
    return render_template("overview.html", context=context)


# ==========================================================
# GENERATE R16
# ==========================================================

@admin.route("/generate-r16")
@login_required
def generate_r16():
    season = get_active_season()

    if stage_exists("r16", season.id):
        return "❌ Round of 16 already generated."
    if not stage_complete("group", season.id):
        return "❌ Complete group stage first."

    qualified = build_group_qualifiers()

    bracket_size = len(qualified)
    if bracket_size not in (4, 8, 16, 32):
        return f"❌ {bracket_size} qualifiers is not a clean bracket size. Adjust qualifiers/wildcards in Season Entries."

    random.shuffle(qualified)
    pairings = []

    while len(qualified) >= 2:
        team1 = qualified.pop(0)
        opponent_index = next(
            (i for i, t in enumerate(qualified) if t["group"] != team1["group"]), 0
        )
        opponent = qualified.pop(opponent_index)
        pairings.append((team1["assignment"], opponent["assignment"]))

    for a1, a2 in pairings:
        db.session.add(Match(
            home_assignment_id=a1.id, away_assignment_id=a2.id,
            stage="r16", matchday=1, is_completed=False, season_id=season.id
        ))

    db.session.commit()
    return redirect(url_for("admin.dashboard"))


# ==========================================================
# GENERATE NEXT STAGE (generic — quarter/semi/final/third)
# ==========================================================

def generate_next_stage(current_stage, next_stage):
    season = get_active_season()

    if stage_exists(next_stage, season.id):
        return f"❌ {next_stage} already generated."
    if not stage_complete(current_stage, season.id):
        return f"❌ Complete {current_stage} first."

    matches = Match.query.filter_by(stage=current_stage, season_id=season.id).all()
    winners = []

    for m in matches:
        if m.home_score is None:
            return f"❌ Some matches in {current_stage} are incomplete."
        if m.home_score > m.away_score:
            winners.append(m.home_assignment_id)
        else:
            winners.append(m.away_assignment_id)

    if len(winners) % 2 != 0:
        return "❌ Uneven winners — cannot generate next stage."

    for i in range(0, len(winners), 2):
        db.session.add(Match(
            home_assignment_id=winners[i], away_assignment_id=winners[i+1],
            stage=next_stage, matchday=1, is_completed=False, season_id=season.id
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
    result = generate_next_stage("semi", "final")
    return result

@admin.route("/generate-third")
@login_required
def generate_third():
    return generate_next_stage("semi", "third")


# ==========================================================
# AWARD TITLE (call after Final is scored)
# ==========================================================

@admin.route("/award-title/<int:match_id>")
@login_required
def award_title(match_id):
    match = Match.query.get_or_404(match_id)
    if match.stage != "final" or match.home_score is None:
        return "❌ Final not completed yet."

    winner_player = (
        match.home_assignment.player if match.home_score > match.away_score
        else match.away_assignment.player
    )
    winner_player.titles_won += 1
    db.session.commit()
    return f"🏆 Title awarded to {winner_player.username}!"


# ==========================================================
# RESET R16 + QUARTER
# ==========================================================

@admin.route("/reset-r16-and-quarter")
@login_required
def reset_r16_and_quarter():
    season = get_active_season()
    Match.query.filter_by(stage="quarter", season_id=season.id).delete()

    r16_matches = Match.query.filter_by(stage="r16", season_id=season.id).all()
    for match in r16_matches:
        if match.elo_processed:
            EloEngine.revert_match(match)
        match.home_score = None
        match.away_score = None
        match.is_completed = False
        match.elo_processed = False

    db.session.commit()
    return "✅ R16 and Quarterfinal successfully reset."

# ==========================================================
# TEMPORARY: SOFT RESET AFTER TESTING — DELETE AFTER USE
# ==========================================================

@admin.route("/dangerous-soft-reset/<secret_key>")
def dangerous_soft_reset(secret_key):
    RESET_KEY = "Hamza123456"

    if secret_key != RESET_KEY:
        return "❌ Invalid key.", 403

    season = get_active_season()
    if not season:
        return "❌ No active season."

    try:
        from ..models import EloHistory, Match, Group, SeasonAssignment, PlayerSeasonRating

        match_ids = [m.id for m in Match.query.filter_by(season_id=season.id).all()]
        EloHistory.query.filter(EloHistory.match_id.in_(match_ids)).delete(synchronize_session=False)

        Match.query.filter_by(season_id=season.id).delete()
        Group.query.filter_by(season_id=season.id).delete()
        SeasonAssignment.query.filter_by(season_id=season.id).delete()
        PlayerSeasonRating.query.filter_by(season_id=season.id).delete()

        season.num_groups = None
        season.qualifiers_per_group = 3
        season.wildcard_slots = 1

        db.session.commit()
        return "✅ SOFT RESET COMPLETE — Season 1 cleared. Player registry untouched."

    except Exception as e:
        db.session.rollback()
        return f"❌ SOFT RESET FAILED: {str(e)}", 500