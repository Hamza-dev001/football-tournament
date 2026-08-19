from flask import Blueprint, jsonify

from .models import Group, SeasonAssignment, get_active_season


api = Blueprint("api", __name__, url_prefix="/api")


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