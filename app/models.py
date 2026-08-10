from datetime import datetime
from . import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# =========================
# SEASON
# =========================
class Season(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    season_number = db.Column(db.Integer, nullable=False, unique=True)

    is_active = db.Column(db.Boolean, default=False, nullable=False)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)

    num_groups = db.Column(db.Integer, nullable=True)
    qualifiers_per_group = db.Column(db.Integer, default=3)
    wildcard_slots = db.Column(db.Integer, default=1)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    groups = db.relationship("Group", backref="season", lazy=True)
    matches = db.relationship("Match", backref="season", lazy=True)
    assignments = db.relationship("SeasonAssignment", backref="season", lazy=True)

    def __repr__(self):
        return f"<Season {self.season_number}: {self.name}>"


# =========================
# CLUB / TEAM SLOT — STATIC 20, PERMANENT, NO ELO
# =========================
class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    logo_url = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Team {self.name}>"


# =========================
# SHARED STATS MIXIN (used by both Season & Career ratings)
# =========================
class StatsMixin:
    wins = db.Column(db.Integer, default=0)
    draws = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)
    goals_scored = db.Column(db.Integer, default=0)
    goals_conceded = db.Column(db.Integer, default=0)
    clean_sheets = db.Column(db.Integer, default=0)
    matches_played = db.Column(db.Integer, default=0)

    def record_result(self, gf, ga):
        self.matches_played += 1
        self.goals_scored += gf
        self.goals_conceded += ga
        if gf > ga:
            self.wins += 1
        elif gf == ga:
            self.draws += 1
        else:
            self.losses += 1
        if ga == 0:
            self.clean_sheets += 1


# =========================
# PLAYER — PERMANENT IDENTITY
# =========================
class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_code = db.Column(db.String(20), nullable=False, unique=True)   # "TFL-001"
    username = db.Column(db.String(100), nullable=False, unique=True)     # "DREX"

    status = db.Column(db.String(20), default="ACTIVE")   # ACTIVE / INACTIVE
    titles_won = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    season_ratings = db.relationship("PlayerSeasonRating", backref="player", lazy=True)
    career_rating = db.relationship("PlayerCareerRating", backref="player", uselist=False)
    assignments = db.relationship("SeasonAssignment", backref="player", lazy=True)

    @staticmethod
    def generate_next_code():
        last = Player.query.order_by(Player.id.desc()).first()
        next_num = (last.id + 1) if last else 1
        return f"TFL-{next_num:03d}"

    def __repr__(self):
        return f"<{self.player_code} {self.username}>"


# =========================
# PLAYER SEASON RATING — RESETS EVERY SEASON
# =========================
class PlayerSeasonRating(StatsMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey("season.id"), nullable=False)

    current_elo = db.Column(db.Float, default=1500.0)
    peak_elo = db.Column(db.Float, default=1500.0)
    lowest_elo = db.Column(db.Float, default=1500.0)

    __table_args__ = (db.UniqueConstraint("player_id", "season_id", name="uq_player_season"),)

    def apply_elo_change(self, delta):
        self.current_elo += delta
        self.peak_elo = max(self.peak_elo, self.current_elo)
        self.lowest_elo = min(self.lowest_elo, self.current_elo)


# =========================
# PLAYER CAREER RATING — NEVER RESETS
# =========================
class PlayerCareerRating(StatsMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=False, unique=True)

    starting_elo = db.Column(db.Float, default=1500.0)
    current_elo = db.Column(db.Float, default=1500.0)
    peak_elo = db.Column(db.Float, default=1500.0)
    seasons_participated = db.Column(db.Integer, default=0)

    def apply_elo_change(self, delta):
        self.current_elo += delta
        self.peak_elo = max(self.peak_elo, self.current_elo)


# =========================
# ELO HISTORY — IMMUTABLE LEDGER
# =========================
class EloHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=False)
    opponent_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey("season.id"), nullable=False)

    season_delta = db.Column(db.Float, nullable=False)
    career_delta = db.Column(db.Float, nullable=False)

    result = db.Column(db.String(1), nullable=False)     # W / D / L
    goals_for = db.Column(db.Integer, nullable=False)
    goals_against = db.Column(db.Integer, nullable=False)
    goal_difference = db.Column(db.Integer, nullable=False)
    stage = db.Column(db.String(50), nullable=False)

    is_voided = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# =========================
# GROUP
# =========================
class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey("season.id"), nullable=False)


# =========================
# SEASON ASSIGNMENT — "This Player uses this Club, this Season, this Group"
# =========================
class SeasonAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey("season.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=True)

    team = db.relationship("Team")
    group = db.relationship("Group", backref="assignments")

    __table_args__ = (
        db.UniqueConstraint("season_id", "player_id", name="uq_season_player"),
        db.UniqueConstraint("season_id", "team_id", name="uq_season_club"),
    )

    @property
    def display_name(self):
        return f"{self.team.name} ({self.player.username})"

    def __repr__(self):
        return f"<Assignment S{self.season_id}: {self.player.username} @ {self.team.name}>"


# =========================
# MATCH — references SeasonAssignment
# =========================
class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey("season.id"), nullable=False)

    home_assignment_id = db.Column(db.Integer, db.ForeignKey("season_assignment.id"), nullable=False)
    away_assignment_id = db.Column(db.Integer, db.ForeignKey("season_assignment.id"), nullable=False)

    home_score = db.Column(db.Integer, nullable=True)
    away_score = db.Column(db.Integer, nullable=True)

    stage = db.Column(db.String(50), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=True)
    matchday = db.Column(db.Integer, nullable=True)

    is_completed = db.Column(db.Boolean, default=False)
    elo_processed = db.Column(db.Boolean, default=False)

    home_assignment = db.relationship("SeasonAssignment", foreign_keys=[home_assignment_id])
    away_assignment = db.relationship("SeasonAssignment", foreign_keys=[away_assignment_id])

    # --- Compatibility shortcuts — old templates keep working ---
    @property
    def home_team(self):
        return self.home_assignment.team

    @property
    def away_team(self):
        return self.away_assignment.team

    @property
    def home_player(self):
        return self.home_assignment.player

    @property
    def away_player(self):
        return self.away_assignment.player


def get_active_season():
    return Season.query.filter_by(is_active=True).first()