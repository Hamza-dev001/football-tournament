import random
from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import or_
from .models import Group, Team, Match
from . import db

main = Blueprint("main", __name__)

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
# GLOBAL STAGE CONTEXT (VISIBLE EVERYWHERE)
# ==========================================================

@main.app_context_processor
def inject_stage_status():

    if stage_exists("final") and stage_complete("final"):
        current_stage = "🏆 Tournament Completed"
    elif stage_exists("final"):
        current_stage = "🔴 Final"
    elif stage_exists("semi"):
        current_stage = "🟠 Semifinal"
    elif stage_exists("quarter"):
        current_stage = "🟣 Quarterfinal"
    elif stage_exists("r16"):
        current_stage = "🔵 Round of 16"
    else:
        current_stage = "🟡 Group Stage"

    group_matches = Match.query.filter_by(stage="group").all()
    remaining_group_matches = sum(
        1 for m in group_matches if not m.is_completed
    )

    group_stage_complete = stage_complete("group")

    return {
        "r16_exists": stage_exists("r16"),
        "quarter_exists": stage_exists("quarter"),
        "semi_exists": stage_exists("semi"),
        "third_exists": stage_exists("third"),
        "final_exists": stage_exists("final"),
        "current_stage": current_stage,
        "remaining_group_matches": remaining_group_matches,
        "group_stage_complete": group_stage_complete
    }

# ==========================================================
# HOME
# ==========================================================

@main.route("/")
def home():
    groups = Group.query.all()
    return render_template("home.html", groups=groups)

# ==========================================================
# RULES
# ==========================================================

@main.route("/rules")
def rules():
    return render_template("rules.html")

# ==========================================================
# GROUP FIXTURES (PROGRESSIVE MATCHDAYS)
# ==========================================================

@main.route("/group-fixtures")
def group_fixtures():

    groups = Group.query.all()
    data = []

    for group in groups:
        matches = (
            Match.query
            .filter_by(stage="group", group_id=group.id)
            .order_by(Match.matchday, Match.id)
            .all()
        )

        matchdays = {}

        for match in matches:
            matchdays.setdefault(match.matchday, []).append(match)

        visible_matchdays = {}

        for matchday in sorted(matchdays.keys()):
            matches_in_day = matchdays[matchday]
            visible_matchdays[matchday] = matches_in_day

            if not all(m.is_completed for m in matches_in_day):
                break

        data.append({
            "group": group,
            "matchdays": visible_matchdays
        })

    return render_template("group_fixtures.html", data=data)

# ==========================================================
# STANDINGS (UPDATED WITH QUALIFICATION STATUS)
# ==========================================================

@main.route("/standings")
def standings():

    groups = Group.query.all()
    standings_data = []

    for group in groups:
        table = []

        for team in group.teams:

            played = wins = draws = losses = points = 0
            gf = ga = 0

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

                played += 1

                if m.home_team_id == team.id:
                    gf += m.home_score
                    ga += m.away_score
                    if m.home_score > m.away_score:
                        wins += 1
                        points += 3
                    elif m.home_score == m.away_score:
                        draws += 1
                        points += 1
                    else:
                        losses += 1
                else:
                    gf += m.away_score
                    ga += m.home_score
                    if m.away_score > m.home_score:
                        wins += 1
                        points += 3
                    elif m.away_score == m.home_score:
                        draws += 1
                        points += 1
                    else:
                        losses += 1

            table.append({
                "team": team,
                "played": played,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "gf": gf,
                "ga": ga,
                "gd": gf - ga,
                "points": points
            })

        table.sort(key=lambda x: (x["points"], x["gd"], x["gf"]), reverse=True)

        # ✅ Assign qualification status
        for index, team_data in enumerate(table):
            if index < 3:
                team_data["status"] = "qualified"
            elif index == 3:
                team_data["status"] = "fourth"
            else:
                team_data["status"] = "eliminated"

        standings_data.append({
            "group": group,
            "table": table
        })

    # ✅ Stats
    all_teams = []
    for group in standings_data:
        for team in group["table"]:
            all_teams.append(team)

    top_scoring_team = max(all_teams, key=lambda x: x["gf"]) if all_teams else None
    best_defense_team = min(all_teams, key=lambda x: x["ga"]) if all_teams else None

    return render_template(
        "group_standings.html",
        standings_data=standings_data,
        top_scoring_team=top_scoring_team,
        best_defense_team=best_defense_team
    )

# ==========================================================
# SETUP
# ==========================================================

@main.route("/setup")
@login_required
def setup():

    if stage_exists("group"):
        return "❌ Tournament already started."

    Match.query.delete()
    Team.query.delete()
    Group.query.delete()
    db.session.commit()

    group_names = ["Group A", "Group B", "Group C", "Group D", "Group E"]
    groups = []

    for name in group_names:
        group = Group(name=name)
        db.session.add(group)
        db.session.flush()
        groups.append(group)

    teams = [
        "TrippleA Bayern","67MERLIN Santos FC","Don Wizziy Dortmund",
        "Titanboot Liverpool","Blaze Barcelona","Yhomide Real Madrid",
        "Adegel Chelsea","Babson AC Milan","Qulialau Internet Miami",
        "Asmev Manchester United","Ariyo Kashim Alters",
        "Diceyguy Newcastle","Oyee Man City","Obamz Sheffield",
        "Stay Motivated PSG","Sufas Al Nassr","Danify Arsenal",
        "Khalil Inter Miami","Wylie Botafogo","Drex Juventus"
    ]

    random.shuffle(teams)

    index = 0
    for group in groups:
        for _ in range(4):
            db.session.add(Team(name=teams[index], group=group))
            index += 1

    db.session.commit()

    return "✅ Groups Created Successfully!"

# ==========================================================
# GENERATE GROUP FIXTURES
# ==========================================================

@main.route("/generate-group-fixtures")
@login_required
def generate_group_fixtures():

    if stage_exists("group"):
        return "❌ Group fixtures already generated."

    groups = Group.query.all()

    for group in groups:
        teams = group.teams
        n = len(teams)
        rotation = teams[:]

        for round_num in range(n - 1):
            for i in range(n // 2):
                t1 = rotation[i]
                t2 = rotation[n - 1 - i]

                db.session.add(Match(
                    home_team_id=t1.id,
                    away_team_id=t2.id,
                    stage="group",
                    group_id=group.id,
                    matchday=round_num + 1
                ))

                db.session.add(Match(
                    home_team_id=t2.id,
                    away_team_id=t1.id,
                    stage="group",
                    group_id=group.id,
                    matchday=round_num + 1
                ))

            rotation = [rotation[0]] + [rotation[-1]] + rotation[1:-1]

    db.session.commit()

    return "✅ Group Fixtures Generated!"

# ==========================================================
# PUBLIC STAGE ROUTES
# ==========================================================

@main.route("/r16")
def r16():
    matches = Match.query.filter_by(stage="r16").all()
    return render_template("r16.html", matches=matches)

@main.route("/quarterfinal")
def quarterfinal():
    matches = Match.query.filter_by(stage="quarter").all()
    return render_template("quarterfinal.html", matches=matches)

@main.route("/semifinal")
def semifinal():
    matches = Match.query.filter_by(stage="semi").all()
    return render_template("knockout_stage.html", matches=matches)

@main.route("/third-place")
def third_place():
    matches = Match.query.filter_by(stage="third").all()
    return render_template("knockout_single.html", matches=matches)

@main.route("/final")
def final():
    matches = Match.query.filter_by(stage="final").all()
    return render_template("final_celebration.html", matches=matches)

@main.route("/bracket")
def bracket():
    return render_template("bracket.html")