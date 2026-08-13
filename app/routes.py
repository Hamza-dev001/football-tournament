from datetime import timedelta
from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import or_

from .models import (
    Group, Team, Match, Season, Player, SeasonAssignment,
    get_active_season
)
from . import db
from .services.analytics_service import AnalyticsService
from .services.season_setup import (
    distribute_ids_into_groups, generate_round_robin, MIN_TEAMS_PER_SEASON
)
from .services.season_manager import now_lagos

main = Blueprint("main", __name__)


# ==========================================================
# STAGE UTILITIES
# ==========================================================

STAGE_ORDER = ["group", "r16", "quarter", "semi", "third", "final"]


def stage_exists(stage_name, season_id=None):
    season = get_active_season()
    season_id = season_id or (season.id if season else None)
    if not season_id:
        return False
    return Match.query.filter_by(stage=stage_name, season_id=season_id).count() > 0


def stage_complete(stage_name, season_id=None):
    season = get_active_season()
    season_id = season_id or (season.id if season else None)
    if not season_id:
        return False
    matches = Match.query.filter_by(stage=stage_name, season_id=season_id).all()
    if not matches:
        return False
    return all(m.is_completed for m in matches)


def tournament_finished():
    return stage_complete("final")


# ==========================================================
# GLOBAL STAGE CONTEXT
# ==========================================================

@main.app_context_processor
def inject_stage_status():
    season = get_active_season()

    season_started = False
    countdown_label = "Season has not started"
    countdown_target = ""

    if not season:
        return {
            "r16_exists": False, "quarter_exists": False, "semi_exists": False,
            "third_exists": False, "final_exists": False,
            "current_stage": "âšª No Active Season", "remaining_group_matches": 0,
            "group_stage_complete": False, "group_done": False, "r16_done": False,
            "quarter_done": False, "semi_done": False, "final_done": False,
            "active_season": None,
            "season_started": False,
            "countdown_label": countdown_label,
            "countdown_target": countdown_target
        }

    if season.started_at:
        now = now_lagos()
        if now < season.started_at:
            countdown_target = season.started_at.isoformat()
            countdown_label = "Season starts in"
            season_started = False
        else:
            season_started = True
            matchday = min((now - season.started_at).days + 1, 3)
            countdown_target = (season.started_at + timedelta(days=matchday)).isoformat()
            countdown_label = f"Matchday {matchday} ends in"

    if stage_exists("final") and stage_complete("final"):
        current_stage = "ðŸ† Tournament Completed"
    elif stage_exists("final"):
        current_stage = "ðŸ”´ Final"
    elif stage_exists("semi"):
        current_stage = "ðŸŸ  Semifinal"
    elif stage_exists("quarter"):
        current_stage = "ðŸŸ£ Quarterfinal"
    elif stage_exists("r16"):
        current_stage = "ðŸ”µ Round of 16"
    else:
        current_stage = "ðŸŸ¡ Group Stage"

    group_matches = Match.query.filter_by(stage="group", season_id=season.id).all()
    remaining_group_matches = sum(1 for m in group_matches if not m.is_completed)

    return {
        "r16_exists": stage_exists("r16"),
        "quarter_exists": stage_exists("quarter"),
        "semi_exists": stage_exists("semi"),
        "third_exists": stage_exists("third"),
        "final_exists": stage_exists("final"),
        "current_stage": current_stage,
        "remaining_group_matches": remaining_group_matches,
        "group_stage_complete": stage_complete("group"),
        "group_done": stage_complete("group"),
        "r16_done": stage_complete("r16"),
        "quarter_done": stage_complete("quarter"),
        "semi_done": stage_complete("semi"),
        "final_done": stage_complete("final"),
        "active_season": season,
        "season_started": season_started,
        "countdown_label": countdown_label,
        "countdown_target": countdown_target
    }


# ==========================================================
# HOME
# ==========================================================

@main.route("/")
def home():
    season = get_active_season()
    groups = Group.query.filter_by(season_id=season.id).all() if season else []
    return render_template("home.html", groups=groups, season=season)


@main.route("/rules")
def rules():
    return render_template("rules.html")


# ==========================================================
# SEASON ARCHIVE
# ==========================================================

@main.route("/seasons")
def season_archive():
    seasons = Season.query.order_by(Season.season_number.desc()).all()
    return render_template("season_archive.html", seasons=seasons)


# ==========================================================
# GROUP FIXTURES
# ==========================================================

@main.route("/group-fixtures")
def group_fixtures():
    all_seasons = Season.query.order_by(Season.season_number).all()
    requested_season_id = request.args.get("season_id", type=int)

    if requested_season_id:
        season = Season.query.get(requested_season_id)
    else:
        season = get_active_season()

    if not season:
        return render_template(
            "group_fixtures.html", data=[],
            all_seasons=all_seasons, selected_season=None
        )

    is_archived = requested_season_id is not None and not season.is_active
    groups = Group.query.filter_by(season_id=season.id).all()
    data = []

    for group in groups:
        matches = (
            Match.query
            .filter_by(stage="group", group_id=group.id, season_id=season.id)
            .order_by(Match.matchday, Match.id)
            .all()
        )
        matchdays = {}
        for match in matches:
            matchdays.setdefault(match.matchday, []).append(match)

        if is_archived:
            visible_matchdays = matchdays
        else:
            visible_matchdays = {}
            for matchday in sorted(matchdays.keys()):
                matches_in_day = matchdays[matchday]
                visible_matchdays[matchday] = matches_in_day
                if not all(m.is_completed for m in matches_in_day):
                    break

        data.append({"group": group, "matchdays": visible_matchdays})

    return render_template(
        "group_fixtures.html", data=data, season=season,
        all_seasons=all_seasons, selected_season=season
    )


# ==========================================================
# STANDINGS
# ==========================================================

def _build_group_table(group, season_id):
    table = []
    for assignment in group.assignments:
        played = wins = draws = losses = points = 0
        gf = ga = 0

        matches = Match.query.filter(
            Match.stage == "group",
            Match.season_id == season_id,
            or_(
                Match.home_assignment_id == assignment.id,
                Match.away_assignment_id == assignment.id
            )
        ).all()

        for m in matches:
            if m.home_score is None:
                continue
            played += 1
            if m.home_assignment_id == assignment.id:
                gf += m.home_score; ga += m.away_score
                if m.home_score > m.away_score: wins += 1; points += 3
                elif m.home_score == m.away_score: draws += 1; points += 1
                else: losses += 1
            else:
                gf += m.away_score; ga += m.home_score
                if m.away_score > m.home_score: wins += 1; points += 3
                elif m.away_score == m.home_score: draws += 1; points += 1
                else: losses += 1

        table.append({
            "assignment": assignment, "played": played, "wins": wins,
            "draws": draws, "losses": losses, "gf": gf, "ga": ga,
            "gd": gf - ga, "points": points
        })

    table.sort(key=lambda x: (x["points"], x["gd"], x["gf"]), reverse=True)
    return table


@main.route("/standings")
def standings():
    all_seasons = Season.query.order_by(Season.season_number).all()
    requested_season_id = request.args.get("season_id", type=int)

    if requested_season_id:
        season = Season.query.get(requested_season_id)
    else:
        season = get_active_season()

    if not season:
        return render_template(
            "group_standings.html", standings_data=[],
            all_seasons=all_seasons, selected_season=None
        )

    groups = Group.query.filter_by(season_id=season.id).all()
    standings_data = []

    for group in groups:
        table = _build_group_table(group, season.id)
        qualifiers_n = season.qualifiers_per_group or 3

        for index, row in enumerate(table):
            if index < qualifiers_n:
                row["status"] = "qualified"
            elif index == qualifiers_n:
                row["status"] = "fourth"
            else:
                row["status"] = "eliminated"

        standings_data.append({"group": group, "table": table})

    all_rows = [row for g in standings_data for row in g["table"]]
    top_scoring_team = max(all_rows, key=lambda x: x["gf"]) if all_rows else None
    best_defense_team = min(all_rows, key=lambda x: x["ga"]) if all_rows else None

    return render_template(
        "group_standings.html",
        standings_data=standings_data,
        top_scoring_team=top_scoring_team,
        best_defense_team=best_defense_team,
        season=season,
        all_seasons=all_seasons,
        selected_season=season
    )


# ==========================================================
# MATCH HISTORY
# ==========================================================

@main.route("/match-history")
def match_history():
    all_seasons = Season.query.order_by(Season.season_number).all()
    requested_season_id = request.args.get("season_id", type=int)

    if requested_season_id:
        season = Season.query.get(requested_season_id)
    else:
        season = get_active_season()

    if not season:
        return render_template(
            "match_history.html", matches=[],
            all_seasons=all_seasons, selected_season=None
        )

    completed_matches = (
        Match.query
        .filter(Match.home_score.isnot(None), Match.season_id == season.id)
        .order_by(Match.matchday, Match.id)
        .all()
    )

    completed_matches.sort(
        key=lambda m: STAGE_ORDER.index(m.stage) if m.stage in STAGE_ORDER else len(STAGE_ORDER)
    )

    return render_template(
        "match_history.html",
        matches=completed_matches,
        season=season,
        all_seasons=all_seasons,
        selected_season=season
    )


# ==========================================================
# TEAM STATS
# ==========================================================

@main.route("/team-stats")
def team_stats():
    season = get_active_season()
    if not season:
        return render_template("team_stats.html", most_goals=[], best_defense=[],
                                most_wins=[], most_clean_sheets=[])

    assignments = SeasonAssignment.query.filter_by(season_id=season.id).all()
    stats = []

    for assignment in assignments:
        matches = Match.query.filter(
            Match.season_id == season.id,
            or_(
                Match.home_assignment_id == assignment.id,
                Match.away_assignment_id == assignment.id
            )
        ).all()

        wins = goals_scored = goals_conceded = clean_sheets = 0
        for m in matches:
            if m.home_score is None:
                continue
            if m.home_assignment_id == assignment.id:
                goals_scored += m.home_score; goals_conceded += m.away_score
                if m.home_score > m.away_score: wins += 1
                if m.away_score == 0: clean_sheets += 1
            else:
                goals_scored += m.away_score; goals_conceded += m.home_score
                if m.away_score > m.home_score: wins += 1
                if m.home_score == 0: clean_sheets += 1

        stats.append({
            "assignment": assignment, "wins": wins,
            "goals_scored": goals_scored, "goals_conceded": goals_conceded,
            "clean_sheets": clean_sheets
        })

    return render_template(
        "team_stats.html",
        most_goals=sorted(stats, key=lambda x: x["goals_scored"], reverse=True),
        best_defense=sorted(stats, key=lambda x: x["goals_conceded"]),
        most_wins=sorted(stats, key=lambda x: x["wins"], reverse=True),
        most_clean_sheets=sorted(stats, key=lambda x: x["clean_sheets"], reverse=True),
        season=season
    )


# ==========================================================
# PLAYER REGISTRY
# ==========================================================

@main.route("/players")
def player_registry():
    rows = AnalyticsService.get_career_leaderboard()
    return render_template("player_registry.html", rows=rows)


@main.route("/players/<player_code>")
def player_profile(player_code):
    player = Player.query.filter_by(player_code=player_code).first_or_404()
    all_seasons = Season.query.order_by(Season.season_number).all()

    history = []
    for season in all_seasons:
        assignment = SeasonAssignment.query.filter_by(
            season_id=season.id, player_id=player.id
        ).first()
        history.append({
            "season": season.name,
            "club": assignment.team.name if assignment else "Did Not Participate"
        })

    from .services.elo_engine import EloEngine
    career = EloEngine.get_career_rating(player.id)

    return render_template(
        "player_profile.html", player=player, history=history, career=career
    )


# ==========================================================
# SETUP
# ==========================================================

@main.route("/setup")
@login_required
def setup():
    season = get_active_season()
    if not season:
        return "âŒ No active season. Create and activate one first."

    if stage_exists("group", season.id):
        return "âŒ Groups already generated for this season."

    assignments = SeasonAssignment.query.filter_by(season_id=season.id).all()
    if len(assignments) < MIN_TEAMS_PER_SEASON:
        return f"âŒ Need at least {MIN_TEAMS_PER_SEASON} assigned teams. Currently: {len(assignments)}."

    if not season.num_groups:
        return "âŒ Season config missing. Finalize team selection in admin first."

    Group.query.filter_by(season_id=season.id).delete()
    db.session.commit()

    group_names = [f"Group {chr(65+i)}" for i in range(season.num_groups)]
    groups = []
    for name in group_names:
        g = Group(name=name, season_id=season.id)
        db.session.add(g)
        db.session.flush()
        groups.append(g)

    assignment_ids = [a.id for a in assignments]
    distributed = distribute_ids_into_groups(assignment_ids, season.num_groups)

    for group, id_list in zip(groups, distributed):
        for assignment_id in id_list:
            SeasonAssignment.query.get(assignment_id).group_id = group.id

    db.session.commit()
    return f"âœ… {len(assignments)} teams split into {season.num_groups} groups!"


# ==========================================================
# GENERATE GROUP FIXTURES
# ==========================================================

@main.route("/generate-group-fixtures")
@login_required
def generate_group_fixtures():
    season = get_active_season()
    if not season:
        return "âŒ No active season."
    if stage_exists("group", season.id):
        return "âŒ Group fixtures already generated."

    groups = Group.query.filter_by(season_id=season.id).all()

    for group in groups:
        assignment_ids = [a.id for a in group.assignments]
        rounds = generate_round_robin(assignment_ids)

        for matchday_num, pairs in enumerate(rounds, start=1):
            for home_id, away_id in pairs:
                db.session.add(Match(
                    home_assignment_id=home_id, away_assignment_id=away_id,
                    stage="group", group_id=group.id,
                    matchday=matchday_num, season_id=season.id
                ))
                db.session.add(Match(
                    home_assignment_id=away_id, away_assignment_id=home_id,
                    stage="group", group_id=group.id,
                    matchday=matchday_num, season_id=season.id
                ))

    db.session.commit()
    return "âœ… Group Fixtures Generated!"


# ==========================================================
# PUBLIC STAGE ROUTES
# ==========================================================

@main.route("/r16")
def r16():
    season = get_active_season()
    matches = Match.query.filter_by(stage="r16", season_id=season.id).all() if season else []
    return render_template("r16.html", matches=matches)


@main.route("/quarterfinal")
def quarterfinal():
    season = get_active_season()
    matches = Match.query.filter_by(stage="quarter", season_id=season.id).all() if season else []
    return render_template("quarterfinal.html", matches=matches)


@main.route("/semifinal")
def semifinal():
    season = get_active_season()
    matches = Match.query.filter_by(stage="semi", season_id=season.id).all() if season else []
    return render_template("knockout_stage.html", matches=matches)


@main.route("/third-place")
def third_place():
    season = get_active_season()
    matches = Match.query.filter_by(stage="third", season_id=season.id).all() if season else []
    return render_template("knockout_single.html", matches=matches)


@main.route("/final")
def final():
    season = get_active_season()
    matches = Match.query.filter_by(stage="final", season_id=season.id).all() if season else []
    return render_template("final_celebration.html", matches=matches)


@main.route("/bracket")
def bracket():
    season = get_active_season()

    if not season:
        return render_template(
            "bracket.html",
            r16_matches=[], quarter_matches=[], semi_matches=[],
            final_matches=[], third_matches=[]
        )

    r16_matches = Match.query.filter_by(stage="r16", season_id=season.id).all()
    quarter_matches = Match.query.filter_by(stage="quarter", season_id=season.id).all()
    semi_matches = Match.query.filter_by(stage="semi", season_id=season.id).all()
    final_matches = Match.query.filter_by(stage="final", season_id=season.id).all()
    third_matches = Match.query.filter_by(stage="third", season_id=season.id).all()

    return render_template(
        "bracket.html",
        r16_matches=r16_matches,
        quarter_matches=quarter_matches,
        semi_matches=semi_matches,
        final_matches=final_matches,
        third_matches=third_matches,
        season=season
    )


# ==========================================================
# ANALYTICS
# ==========================================================

@main.route("/analytics")
def analytics():
    rankings = AnalyticsService.get_power_rankings()
    return render_template("analytics.html", rankings=rankings)


@main.route("/leaderboard")
def leaderboard():
    rows = AnalyticsService.get_career_leaderboard()
    return render_template("leaderboard.html", rows=rows)


@main.route("/top-scorers")
def top_scorers():
    rows = AnalyticsService.get_top_scorers()
    return render_template("top_scorers.html", rows=rows)


# ==========================================================
# PREDICT
# ==========================================================

@main.route("/predict", methods=["GET", "POST"])
def predict():
    season = get_active_season()
    players = []
    if season:
        assigned_ids = [a.player_id for a in SeasonAssignment.query.filter_by(season_id=season.id).all()]
        if assigned_ids:
            players = Player.query.filter(Player.id.in_(assigned_ids)).all()

    prediction = None
    player_a = player_b = None

    if request.method == "POST":
        a_id = request.form.get("team_a")
        b_id = request.form.get("team_b")
        if a_id and b_id and a_id != b_id:
            player_a = Player.query.get(int(a_id))
            player_b = Player.query.get(int(b_id))
            prediction = AnalyticsService.predict_match(player_a, player_b)

    return render_template(
        "predict.html", teams=players, prediction=prediction,
        team_a=player_a, team_b=player_b
    )