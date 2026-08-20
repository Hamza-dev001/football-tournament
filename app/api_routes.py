from flask import Blueprint, jsonify

from .models import Group, SeasonAssignment, Match, get_active_season


api = Blueprint("api", __name__, url_prefix="/api")

@api.get("/overview")
def overview():
    season = get_active_season()

    if not season:
        return jsonify({
            "success": True,
            "season": None,
            "teams": 0,
            "groups": 0,
            "group_matches": 0,
            "matches_per_team": 0
        })

    assignments = SeasonAssignment.query.filter_by(
        season_id=season.id
    ).all()

    groups = (
        Group.query
        .filter_by(season_id=season.id)
        .all()
    )

    group_matches = Match.query.filter_by(
        season_id=season.id,
        stage="group"
    ).count()

    teams = len(assignments)

    return jsonify({
        "success": True,
        "season": {
            "id": season.id,
            "number": season.season_number
        },
        "teams": teams,
        "groups": len(groups),
        "group_matches": group_matches,
        "matches_per_team": (
            group_matches * 2 // teams
            if teams else 0
        )
    })


@api.get("/groups")
def groups():
    season = get_active_season()

    if not season:
        return jsonify({
            "success": True,
            "season": None,
            "groups": []
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
                group_id=group.id
            )
            .all()
        )

        teams = []

        for assignment in assignments:
            teams.append({
                "team_id": assignment.team.id,
                "team": assignment.team.name,
                "player_id": assignment.player.id,
                "player": assignment.player.username
            })

        groups_data.append({
            "id": group.id,
            "name": group.name,
            "teams": teams
        })

    return jsonify({
        "success": True,
        "season": {
            "id": season.id,
            "number": season.season_number
        },
        "groups": groups_data
    })


@api.get("/fixtures")
def fixtures():
    season = get_active_season()

    if not season:
        return jsonify({
            "success": True,
            "season": None,
            "fixtures": []
        })

    matches = (
        Match.query
        .filter_by(season_id=season.id)
        .order_by(
            Match.stage.asc(),
            Match.matchday.asc(),
            Match.id.asc()
        )
        .all()
    )

    fixtures_data = []

    for match in matches:
        fixtures_data.append({
            "id": match.id,
            "stage": match.stage,
            "matchday": match.matchday,
            "home_team": match.home_assignment.team.name,
            "home_player": match.home_assignment.player.username,
            "away_team": match.away_assignment.team.name,
            "away_player": match.away_assignment.player.username,
            "home_score": match.home_score,
            "away_score": match.away_score,
            "is_completed": match.is_completed
        })

    return jsonify({
        "success": True,
        "season": {
            "id": season.id,
            "number": season.season_number
        },
        "fixtures": fixtures_data
    })