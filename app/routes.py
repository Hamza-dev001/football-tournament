import random
import os
from flask import Blueprint, render_template
from sqlalchemy import or_
from .models import Group, Team, Match
from . import db

main = Blueprint("main", __name__)

# ==========================================================
# HOME
# ==========================================================
@main.route("/")
def home():
    groups = Group.query.all()
    return render_template("home.html", groups=groups)

# ==========================================================
# GROUP FIXTURES (WITH MATCHDAYS)
# ==========================================================
@main.route("/group-fixtures")
def group_fixtures():

    groups = Group.query.all()
    data = []

    for group in groups:
        matches = Match.query.filter_by(
            stage="group",
            group_id=group.id
        ).all()

        matchdays = {}
        for match in matches:
            matchdays.setdefault(match.matchday, []).append(match)

        data.append({
            "group": group,
            "matchdays": matchdays
        })

    return render_template("group_fixtures.html", data=data)

# ==========================================================
# STANDINGS
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
                        wins += 1; points += 3
                    elif m.home_score == m.away_score:
                        draws += 1; points += 1
                    else:
                        losses += 1
                else:
                    gf += m.away_score
                    ga += m.home_score

                    if m.away_score > m.home_score:
                        wins += 1; points += 3
                    elif m.away_score == m.home_score:
                        draws += 1; points += 1
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

        table.sort(
            key=lambda x: (x["points"], x["gd"], x["gf"]),
            reverse=True
        )

        standings_data.append({
            "group": group,
            "table": table
        })

    return render_template(
        "group_standings.html",
        standings_data=standings_data
    )

# ==========================================================
# OVERVIEW (MATCH STATUS)
# ==========================================================
@main.route("/overview")
def overview():

    stages = ["group", "r16", "quarter", "semi", "third", "final"]
    status = {}

    for stage in stages:
        matches = Match.query.filter_by(stage=stage).all()
        total = len(matches)
        completed = len([m for m in matches if m.is_completed])
        status[stage.capitalize()] = (completed, total)

    return render_template("overview.html", status=status)

# ==========================================================
# GENERATE SEMI
# ==========================================================
@main.route("/generate-semi")
def generate_semi():

    quarter_matches = Match.query.filter_by(stage="quarter").all()

    if not quarter_matches:
        return "❌ Quarter not generated."

    if any(not m.is_completed for m in quarter_matches):
        return "❌ Complete all Quarter matches first."

    winners = []

    for m in quarter_matches:
        if m.home_score == m.away_score:
            return f"❌ Draw detected between {m.home_team.name} and {m.away_team.name}. Replay required."

        winner = m.home_team if m.home_score > m.away_score else m.away_team
        winners.append(winner)

    if len(winners) != 4:
        return "❌ Quarter winner calculation error."

    Match.query.filter_by(stage="semi").delete()
    db.session.commit()

    random.shuffle(winners)

    for i in range(0, 4, 2):
        db.session.add(Match(
            home_team_id=winners[i].id,
            away_team_id=winners[i+1].id,
            stage="semi"
        ))

    db.session.commit()

    return "✅ Semi Generated Successfully!"

# ==========================================================
# GENERATE FINAL + THIRD PLACE
# ==========================================================
@main.route("/generate-final")
def generate_final():

    semi_matches = Match.query.filter_by(stage="semi").all()

    if not semi_matches:
        return "❌ Semi not generated."

    if any(not m.is_completed for m in semi_matches):
        return "❌ Complete all Semi matches first."

    final_teams = []
    third_teams = []

    for m in semi_matches:

        if m.home_score == m.away_score:
            return f"❌ Draw detected between {m.home_team.name} and {m.away_team.name}. Replay required."

        if m.home_score > m.away_score:
            final_teams.append(m.home_team)
            third_teams.append(m.away_team)
        else:
            final_teams.append(m.away_team)
            third_teams.append(m.home_team)

    Match.query.filter_by(stage="final").delete()
    Match.query.filter_by(stage="third").delete()
    db.session.commit()

    db.session.add(Match(
        home_team_id=final_teams[0].id,
        away_team_id=final_teams[1].id,
        stage="final"
    ))

    db.session.add(Match(
        home_team_id=third_teams[0].id,
        away_team_id=third_teams[1].id,
        stage="third"
    ))

    db.session.commit()

    return "✅ Final and Third Place Generated Successfully!"

# ==========================================================
# SIMPLE PAGE ROUTES (FOR NAVBAR STABILITY)
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

# ==========================================================
# BRACKET (FULL DATA PASSED)
# ==========================================================
@main.route("/bracket")
def bracket():

    r16_matches = Match.query.filter_by(stage="r16").all()
    quarter_matches = Match.query.filter_by(stage="quarter").all()
    semi_matches = Match.query.filter_by(stage="semi").all()
    final_matches = Match.query.filter_by(stage="final").all()
    third_matches = Match.query.filter_by(stage="third").all()

    return render_template(
        "bracket.html",
        r16_matches=r16_matches,
        quarter_matches=quarter_matches,
        semi_matches=semi_matches,
        final_matches=final_matches,
        third_matches=third_matches
    )