from sqlalchemy import or_
from app.models import Team, Match


class AnalyticsService:

    @staticmethod
    def calculate_team_stats(team):

        matches = Match.query.filter(
            or_(
                Match.home_team_id == team.id,
                Match.away_team_id == team.id
            )
        ).all()

        played = wins = 0
        goals_scored = goals_conceded = 0

        for m in matches:
            if m.home_score is None:
                continue

            played += 1

            if m.home_team_id == team.id:
                goals_scored += m.home_score
                goals_conceded += m.away_score
                if m.home_score > m.away_score:
                    wins += 1
            else:
                goals_scored += m.away_score
                goals_conceded += m.home_score
                if m.away_score > m.home_score:
                    wins += 1

        return {
            "team": team,
            "played": played,
            "wins": wins,
            "goals_scored": goals_scored,
            "goals_conceded": goals_conceded
        }