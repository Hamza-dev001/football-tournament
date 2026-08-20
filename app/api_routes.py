from flask import Blueprint, jsonify, request

from .models import (
    Group,
    Season,
    SeasonAssignment,
    Match,
    Player,
    PlayerSeasonRating,
    PlayerCareerRating,
    EloHistory,
    Team,
    get_active_season,
)


api = Blueprint("api", __name__, url_prefix="/api")


# ============================================================
# HELPERS
# ============================================================

def get_requested_season():
    """
    Returns the requested season when ?season_id= is supplied.
    Otherwise returns the currently active season.
    """
    season_id = request.args.get("season_id", type=int)

    if season_id:
        return Season.query.get(season_id)

    return get_active_season()


def assignment_json(assignment):
    if not assignment:
        return None

    return {
        "id": assignment.id,
        "team_id": assignment.team.id if assignment.team else None,
        "team": assignment.team.name if assignment.team else None,
        "logo_url": assignment.team.logo_url if assignment.team else None,
        "player_id": assignment.player.id if assignment.player else None,
        "player": assignment.player.username if assignment.player else None,
        "player_code": (
            assignment.player.player_code
            if assignment.player
            else None
        ),
    }


def match_json(match):
    return {
        "id": match.id,
        "season_id": match.season_id,
        "stage": match.stage,
        "group_id": match.group_id,
        "matchday": match.matchday,

        "home": assignment_json(match.home_assignment),
        "away": assignment_json(match.away_assignment),

        "home_team": (
            match.home_assignment.team.name
            if match.home_assignment and match.home_assignment.team
            else None
        ),
        "home_player": (
            match.home_assignment.player.username
            if match.home_assignment and match.home_assignment.player
            else None
        ),
        "away_team": (
            match.away_assignment.team.name
            if match.away_assignment and match.away_assignment.team
            else None
        ),
        "away_player": (
            match.away_assignment.player.username
            if match.away_assignment and match.away_assignment.player
            else None
        ),

        "home_score": match.home_score,
        "away_score": match.away_score,
        "is_completed": bool(match.is_completed),
        "elo_processed": bool(match.elo_processed),
        "title_awarded": bool(match.title_awarded),
    }


def season_json(season):
    if not season:
        return None

    return {
        "id": season.id,
        "name": season.name,
        "number": season.season_number,
        "is_active": bool(season.is_active),
        "is_completed": bool(season.is_completed),
        "num_groups": season.num_groups,
        "qualifiers_per_group": season.qualifiers_per_group,
        "wildcard_slots": season.wildcard_slots,
    }


# ============================================================
# OVERVIEW
# ============================================================

@api.get("/overview")
def overview():
    season = get_requested_season()

    if not season:
        return jsonify({
            "success": True,
            "season": None,
            "teams": 0,
            "groups": 0,
            "group_matches": 0,
            "matches_per_team": 0,
        })

    assignments = SeasonAssignment.query.filter_by(
        season_id=season.id
    ).all()

    groups = Group.query.filter_by(
        season_id=season.id
    ).all()

    group_matches = Match.query.filter_by(
        season_id=season.id,
        stage="group",
    ).count()

    teams = len(assignments)

    return jsonify({
        "success": True,
        "season": season_json(season),
        "teams": teams,
        "groups": len(groups),
        "group_matches": group_matches,
        "matches_per_team": (
            group_matches * 2 // teams
            if teams
            else 0
        ),
    })


# ============================================================
# GROUPS
# ============================================================

@api.get("/groups")
def groups():
    season = get_requested_season()

    if not season:
        return jsonify({
            "success": True,
            "season": None,
            "groups": [],
        })

    groups_data = []

    groups = (
        Group.query
        .filter_by(season_id=season.id)
        .order_by(Group.name.asc())
        .all()
    )

    for group in groups:
        assignments = (
            SeasonAssignment.query
            .filter_by(
                season_id=season.id,
                group_id=group.id,
            )
            .all()
        )

        teams = []

        for assignment in assignments:
            teams.append(
                assignment_json(assignment)
            )

        groups_data.append({
            "id": group.id,
            "name": group.name,
            "teams": teams,
        })

    return jsonify({
        "success": True,
        "season": season_json(season),
        "groups": groups_data,
    })


# ============================================================
# FIXTURES
# ============================================================

@api.get("/fixtures")
def fixtures():
    season = get_requested_season()

    if not season:
        return jsonify({
            "success": True,
            "season": None,
            "fixtures": [],
        })

    matches = (
        Match.query
        .filter_by(season_id=season.id)
        .order_by(
            Match.stage.asc(),
            Match.matchday.asc(),
            Match.id.asc(),
        )
        .all()
    )

    return jsonify({
        "success": True,
        "season": season_json(season),
        "fixtures": [
            match_json(match)
            for match in matches
        ],
    })


# ============================================================
# STANDINGS
# ============================================================

@api.get("/standings")
def standings():
    season = get_requested_season()

    if not season:
        return jsonify({
            "success": True,
            "season": None,
            "standings": [],
        })

    groups = (
        Group.query
        .filter_by(season_id=season.id)
        .order_by(Group.name.asc())
        .all()
    )

    result = []

    for group in groups:
        assignments = (
            SeasonAssignment.query
            .filter_by(
                season_id=season.id,
                group_id=group.id,
            )
            .all()
        )

        table = []

        for assignment in assignments:
            rating = (
                PlayerSeasonRating.query
                .filter_by(
                    player_id=assignment.player_id,
                    season_id=season.id,
                )
                .first()
            )

            if rating:
                table.append({
                    "assignment_id": assignment.id,
                    "team_id": assignment.team.id,
                    "team": assignment.team.name,
                    "logo_url": assignment.team.logo_url,
                    "player_id": assignment.player.id,
                    "player": assignment.player.username,
                    "player_code": assignment.player.player_code,

                    "played": rating.matches_played,
                    "wins": rating.wins,
                    "draws": rating.draws,
                    "losses": rating.losses,
                    "goals_scored": rating.goals_scored,
                    "goals_conceded": rating.goals_conceded,
                    "goal_difference": (
                        rating.goals_scored
                        - rating.goals_conceded
                    ),
                    "points": (
                        rating.wins * 3
                        + rating.draws
                    ),
                    "elo": round(
                        rating.current_elo,
                        1,
                    ),
                })
            else:
                table.append({
                    "assignment_id": assignment.id,
                    "team_id": assignment.team.id,
                    "team": assignment.team.name,
                    "logo_url": assignment.team.logo_url,
                    "player_id": assignment.player.id,
                    "player": assignment.player.username,
                    "player_code": assignment.player.player_code,

                    "played": 0,
                    "wins": 0,
                    "draws": 0,
                    "losses": 0,
                    "goals_scored": 0,
                    "goals_conceded": 0,
                    "goal_difference": 0,
                    "points": 0,
                    "elo": 1500,
                })

        table.sort(
            key=lambda x: (
                -x["points"],
                -x["goal_difference"],
                -x["goals_scored"],
            )
        )

        for index, row in enumerate(table, start=1):
            row["position"] = index

        result.append({
            "group": group.name,
            "group_id": group.id,
            "table": table,
        })

    return jsonify({
        "success": True,
        "season": season_json(season),
        "standings": result,
    })


# ============================================================
# PLAYER REGISTRY
# ============================================================

@api.get("/players")
def players():
    players = (
        Player.query
        .filter_by(status="ACTIVE")
        .order_by(Player.username.asc())
        .all()
    )

    result = []

    for player in players:
        career = (
            PlayerCareerRating.query
            .filter_by(player_id=player.id)
            .first()
        )

        assignments = (
            SeasonAssignment.query
            .filter_by(player_id=player.id)
            .all()
        )

        seasons = []

        for assignment in assignments:
            seasons.append({
                "season_id": assignment.season_id,
                "season_number": (
                    assignment.season.season_number
                    if assignment.season
                    else None
                ),
                "team": (
                    assignment.team.name
                    if assignment.team
                    else None
                ),
                "logo_url": (
                    assignment.team.logo_url
                    if assignment.team
                    else None
                ),
                "group": (
                    assignment.group.name
                    if assignment.group
                    else None
                ),
            })

        result.append({
            "id": player.id,
            "player_code": player.player_code,
            "username": player.username,
            "titles_won": player.titles_won,

            "career": {
                "starting_elo": (
                    round(career.starting_elo, 1)
                    if career
                    else 1500
                ),
                "current_elo": (
                    round(career.current_elo, 1)
                    if career
                    else 1500
                ),
                "peak_elo": (
                    round(career.peak_elo, 1)
                    if career
                    else 1500
                ),
                "matches_played": (
                    career.matches_played
                    if career
                    else 0
                ),
                "wins": (
                    career.wins
                    if career
                    else 0
                ),
                "draws": (
                    career.draws
                    if career
                    else 0
                ),
                "losses": (
                    career.losses
                    if career
                    else 0
                ),
                "goals_scored": (
                    career.goals_scored
                    if career
                    else 0
                ),
                "goals_conceded": (
                    career.goals_conceded
                    if career
                    else 0
                ),
            },

            "seasons": seasons,
        })

    return jsonify({
        "success": True,
        "players": result,
    })


# ============================================================
# TOP SCORERS
# ============================================================

@api.get("/top-scorers")
def top_scorers():
    season = get_requested_season()

    if not season:
        return jsonify({
            "success": True,
            "season": None,
            "top_scorers": [],
        })

    ratings = (
        PlayerSeasonRating.query
        .filter_by(season_id=season.id)
        .order_by(
            PlayerSeasonRating.goals_scored.desc(),
            PlayerSeasonRating.matches_played.asc(),
        )
        .all()
    )

    result = []

    for rating in ratings:
        assignment = (
            SeasonAssignment.query
            .filter_by(
                season_id=season.id,
                player_id=rating.player_id,
            )
            .first()
        )

        if not assignment:
            continue

        result.append({
            "position": len(result) + 1,
            "player_id": rating.player_id,
            "player": assignment.player.username,
            "player_code": assignment.player.player_code,
            "team": assignment.team.name,
            "goals": rating.goals_scored,
            "matches": rating.matches_played,
            "assists": 0,
        })

    return jsonify({
        "success": True,
        "season": season_json(season),
        "top_scorers": result,
    })


# ============================================================
# MATCH HISTORY
# ============================================================

@api.get("/match-history")
def match_history():
    season = get_requested_season()

    if not season:
        return jsonify({
            "success": True,
            "season": None,
            "matches": [],
        })

    matches = (
        Match.query
        .filter(
            Match.season_id == season.id,
            Match.is_completed.is_(True),
        )
        .order_by(Match.id.desc())
        .all()
    )

    return jsonify({
        "success": True,
        "season": season_json(season),
        "matches": [
            match_json(match)
            for match in matches
        ],
    })


# ============================================================
# ANALYTICS
# ============================================================

@api.get("/analytics")
def analytics():
    season = get_requested_season()

    if not season:
        return jsonify({
            "success": True,
            "season": None,
            "analytics": {},
        })

    ratings = (
        PlayerSeasonRating.query
        .filter_by(season_id=season.id)
        .all()
    )

    total_matches = Match.query.filter_by(
        season_id=season.id,
        is_completed=True,
    ).count()

    total_goals = sum(
        rating.goals_scored
        for rating in ratings
    )

    total_clean_sheets = sum(
        rating.clean_sheets
        for rating in ratings
    )

    highest_elo = None

    if ratings:
        highest_elo_rating = max(
            ratings,
            key=lambda r: r.current_elo,
        )

        assignment = (
            SeasonAssignment.query
            .filter_by(
                season_id=season.id,
                player_id=highest_elo_rating.player_id,
            )
            .first()
        )

        if assignment:
            highest_elo = {
                "player": assignment.player.username,
                "player_code": assignment.player.player_code,
                "team": assignment.team.name,
                "elo": round(
                    highest_elo_rating.current_elo,
                    1,
                ),
            }

    return jsonify({
        "success": True,
        "season": season_json(season),
        "analytics": {
            "completed_matches": total_matches,
            "total_goals": total_goals,
            "clean_sheets": total_clean_sheets,
            "average_goals_per_match": (
                round(
                    total_goals / total_matches,
                    2,
                )
                if total_matches
                else 0
            ),
            "highest_elo": highest_elo,
        },
    })


# ============================================================
# SEASON ARCHIVE
# ============================================================

@api.get("/seasons")
def seasons():
    all_seasons = (
        Season.query
        .order_by(Season.season_number.desc())
        .all()
    )

    return jsonify({
        "success": True,
        "active_season_id": (
            get_active_season().id
            if get_active_season()
            else None
        ),
        "seasons": [
            season_json(season)
            for season in all_seasons
        ],
    })


# ============================================================
# SINGLE SEASON
# ============================================================

@api.get("/seasons/<int:season_id>")
def season_details(season_id):
    season = Season.query.get(season_id)

    if not season:
        return jsonify({
            "success": False,
            "error": "Season not found.",
        }), 404

    return jsonify({
        "success": True,
        "season": season_json(season),
    })


# ============================================================
# RULES
# ============================================================

@api.get("/rules")
def rules():
    return jsonify({
        "success": True,
        "rules": {
            "name": "Titan Football League",
            "format": "League Tournament",
            "group_stage": {
                "home_and_away": True,
            },
            "points": {
                "win": 3,
                "draw": 1,
                "loss": 0,
            },
            "knockout": {
                "extra_time": True,
                "penalties": True,
            },
        },
    })