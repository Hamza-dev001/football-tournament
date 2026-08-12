from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import db
from ..models import Season, Team, Player, SeasonAssignment, PlayerSeasonRating
from .player_registry import get_or_create_player
from .season_setup import suggest_season_config

LAGOS = ZoneInfo("Africa/Lagos")


def now_lagos():
    return datetime.now(LAGOS).replace(tzinfo=None)


def next_10am_lagos():
    now = now_lagos()
    start = now.replace(hour=10, minute=0, second=0, microsecond=0)
    if now >= start:
        start += timedelta(days=1)
    return start


class SeasonManager:

    @staticmethod
    def create_season(name):
        last = Season.query.order_by(Season.season_number.desc()).first()
        next_number = (last.season_number + 1) if last else 1
        season = Season(name=name, season_number=next_number)
        db.session.add(season)
        db.session.commit()
        return season

    @staticmethod
    def activate_season(season_id):
        Season.query.update({Season.is_active: False})
        season = Season.query.get_or_404(season_id)
        season.is_active = True
        db.session.commit()
        return season

    @staticmethod
    def start_season_clock(season_id, start_at=None):
        season = Season.query.get_or_404(season_id)
        season.started_at = start_at or now_lagos()
        db.session.commit()
        return season

    @staticmethod
    def stop_season_clock(season_id):
        season = Season.query.get_or_404(season_id)
        season.started_at = None
        db.session.commit()
        return season

    @staticmethod
    def complete_season(season_id):
        season = Season.query.get_or_404(season_id)
        season.is_completed = True
        season.is_active = False
        season.completed_at = now_lagos()
        SeasonManager.mark_inactive_players(season_id)
        db.session.commit()
        return season

    @staticmethod
    def assign_player_to_club(season_id, username, team_id):
        player = get_or_create_player(username)

        if SeasonAssignment.query.filter_by(season_id=season_id, player_id=player.id).first():
            raise ValueError(f"{player.username} is already assigned this season.")
        if SeasonAssignment.query.filter_by(season_id=season_id, team_id=team_id).first():
            raise ValueError("This club is already taken this season.")

        assignment = SeasonAssignment(season_id=season_id, player_id=player.id, team_id=team_id)
        db.session.add(assignment)

        if not PlayerSeasonRating.query.filter_by(player_id=player.id, season_id=season_id).first():
            db.session.add(PlayerSeasonRating(player_id=player.id, season_id=season_id))

        player.status = "ACTIVE"
        db.session.commit()
        return assignment

    @staticmethod
    def remove_assignment(assignment_id):
        assignment = SeasonAssignment.query.get_or_404(assignment_id)
        db.session.delete(assignment)
        db.session.commit()

    @staticmethod
    def mark_inactive_players(season_id):
        assigned_ids = {a.player_id for a in SeasonAssignment.query.filter_by(season_id=season_id).all()}
        for player in Player.query.filter(Player.status == "ACTIVE").all():
            if player.id not in assigned_ids:
                player.status = "INACTIVE"
        db.session.commit()

    @staticmethod
    def get_unassigned_clubs(season_id):
        taken_ids = [a.team_id for a in SeasonAssignment.query.filter_by(season_id=season_id).all()]
        query = Team.query.filter(Team.is_active == True)
        if taken_ids:
            query = query.filter(~Team.id.in_(taken_ids))
        return query.order_by(Team.name).all()

    @staticmethod
    def finalize_season_config(season_id, team_count):
        season = Season.query.get_or_404(season_id)
        config = suggest_season_config(team_count)
        season.num_groups = config["num_groups"]
        season.qualifiers_per_group = config["qualifiers_per_group"]
        season.wildcard_slots = config["wildcard_slots"]
        db.session.commit()
        return config