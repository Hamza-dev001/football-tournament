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

        played = wins = draws = losses = 0
        goals_scored = goals_conceded = 0
        clean_sheets = 0
        points = 0

        for m in matches:
            if m.home_score is None:
                continue

            played += 1

            if m.home_team_id == team.id:
                gf = m.home_score
                ga = m.away_score
            else:
                gf = m.away_score
                ga = m.home_score

            goals_scored += gf
            goals_conceded += ga

            if gf > ga:
                wins += 1
                points += 3
            elif gf == ga:
                draws += 1
                points += 1
            else:
                losses += 1

            if ga == 0:
                clean_sheets += 1

        return {
            "team": team,
            "played": played,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "points": points,
            "goals_scored": goals_scored,
            "goals_conceded": goals_conceded,
            "goal_difference": goals_scored - goals_conceded,
            "clean_sheets": clean_sheets
        }

    # --------------------------------------------------

    @staticmethod
    def calculate_performance_score(stats):

        played = stats["played"] if stats["played"] > 0 else 1

        win_ratio = stats["wins"] / played

        score = (
            (stats["points"] * 3)
            + (stats["goal_difference"] * 2)
            + (stats["goals_scored"] * 1.5)
            + (stats["clean_sheets"] * 2)
            + (win_ratio * 20)
        )

        return round(score, 2)

    # --------------------------------------------------

    @staticmethod
    def assign_tier(score):

        if score >= 90:
            return "Legendary"
        elif score >= 75:
            return "Elite"
        elif score >= 60:
            return "Strong"
        elif score >= 45:
            return "Competitive"
        else:
            return "Developing"

    # --------------------------------------------------

    @staticmethod
    def get_power_rankings():

        teams = Team.query.all()
        rankings = []

        for team in teams:
            stats = AnalyticsService.calculate_team_stats(team)
            score = AnalyticsService.calculate_performance_score(stats)
            tier = AnalyticsService.assign_tier(score)

            stats["performance_score"] = score
            stats["tier"] = tier

            rankings.append(stats)

        rankings.sort(key=lambda x: x["performance_score"], reverse=True)

        return rankings