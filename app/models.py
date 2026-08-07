from . import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


# =========================
# ADMIN USER
# =========================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# =========================
# GROUP
# =========================
class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)

    teams = db.relationship("Team", backref="group", lazy=True)


# =========================
# TEAM
# =========================
class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=True)

    


# =========================
# MATCH
# =========================
class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    home_team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    away_team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)

    home_score = db.Column(db.Integer, nullable=True)
    away_score = db.Column(db.Integer, nullable=True)

    stage = db.Column(db.String(50), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=True)

    matchday = db.Column(db.Integer, nullable=True)

    is_completed = db.Column(db.Boolean, default=False)

    home_team = db.relationship("Team", foreign_keys=[home_team_id])
    away_team = db.relationship("Team", foreign_keys=[away_team_id])