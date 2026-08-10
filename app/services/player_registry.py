from .. import db
from ..models import Player, PlayerCareerRating

STARTING_ELO = 1500.0


def register_player(username):
    username = username.strip()
    existing = Player.query.filter_by(username=username).first()
    if existing:
        raise ValueError(f"Username '{username}' already belongs to {existing.player_code}.")

    player = Player(
        player_code=Player.generate_next_code(),
        username=username,
        status="ACTIVE"
    )
    db.session.add(player)
    db.session.flush()

    career = PlayerCareerRating(
        player_id=player.id,
        starting_elo=STARTING_ELO,
        current_elo=STARTING_ELO,
        peak_elo=STARTING_ELO
    )
    db.session.add(career)
    db.session.commit()
    return player


def get_or_create_player(username):
    """Used by admin quick-assign — reuses existing player if username matches."""
    username = username.strip()
    player = Player.query.filter_by(username=username).first()
    if player:
        return player
    return register_player(username)