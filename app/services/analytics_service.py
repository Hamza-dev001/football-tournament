from sqlalchemy import or_
from app.models import Team, Match


class AnalyticsService:

    # --------------------------------------------------
    # CALCULATE FULL TEAM STATS
    # --------------------------------------------------

    @staticmethod
    def calculate_team_stats(team):

        matches = Match.query.filter(
            or_(
                Match.home_team_id == team.id,
                Match.away_team_id == team.id
            )
        ).order_by(Match.id.desc()).all()

        played = wins = draws = losses = 0
        goals_scored = goals_conceded = 0
        clean_sheets = 0
        points = 0

        recent_form = []  # last 3 matches

        for m in matches:
            if m.home_score is None:
                continue

            if m.home_team_id == team.id:
                gf = m.home_score
                ga = m.away_score
            else:
                gf = m.away_score
                ga = m.home_score

            played += 1
            goals_scored += gf
            goals_conceded += ga

            # Determine result
            if gf > ga:
                wins += 1
                points += 3
                result = "W"
            elif gf == ga:
                draws += 1
                points += 1
                result = "D"
            else:
                losses += 1
                result = "L"

            if ga == 0:
                clean_sheets += 1

            # Store last 3 results
            if len(recent_form) < 3:
                recent_form.append(result)

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
            "clean_sheets": clean_sheets,
            "form": recent_form
        }

    # --------------------------------------------------
    # ADVANCED METRICS
    # --------------------------------------------------

    @staticmethod
    def calculate_attack_rating(stats):
        if stats["played"] == 0:
            return 0
        return round(stats["goals_scored"] / stats["played"] * 10, 2)

    @staticmethod
    def calculate_defense_rating(stats):
        if stats["played"] == 0:
            return 0
        defensive_strength = (stats["clean_sheets"] * 2) - stats["goals_conceded"]
        return round(defensive_strength, 2)

    @staticmethod
    def calculate_efficiency(stats):
        if stats["played"] == 0:
            return 0
        return round(stats["points"] / stats["played"], 2)

    @staticmethod
    def calculate_form_score(stats):

        score = 0
        for result in stats["form"]:
            if result == "W":
                score += 3
            elif result == "D":
                score += 1

        return score

    # --------------------------------------------------
    # PERFORMANCE SCORE (UPDATED FORMULA)
    # --------------------------------------------------

    @staticmethod
    def calculate_performance_score(stats):

        attack = AnalyticsService.calculate_attack_rating(stats)
        defense = AnalyticsService.calculate_defense_rating(stats)
        efficiency = AnalyticsService.calculate_efficiency(stats)
        form_score = AnalyticsService.calculate_form_score(stats)

        score = (
            (stats["points"] * 2)
            + (stats["goal_difference"] * 1.5)
            + attack
            + defense
            + (efficiency * 5)
            + form_score
        )

        return round(score, 2)

    # --------------------------------------------------
    # TIER SYSTEM
    # --------------------------------------------------

    @staticmethod
    def assign_tier(score):

        if score >= 120:
            return "Legendary"
        elif score >= 95:
            return "Elite"
        elif score >= 75:
            return "Strong"
        elif score >= 55:
            return "Competitive"
        else:
            return "Developing"

    # --------------------------------------------------
    # FINAL POWER RANKINGS
    # --------------------------------------------------

    @staticmethod
    def get_power_rankings():

        teams = Team.query.all()
        rankings = []

        for team in teams:
            stats = AnalyticsService.calculate_team_stats(team)

            stats["attack_rating"] = AnalyticsService.calculate_attack_rating(stats)
            stats["defense_rating"] = AnalyticsService.calculate_defense_rating(stats)
            stats["efficiency"] = AnalyticsService.calculate_efficiency(stats)
            stats["form_score"] = AnalyticsService.calculate_form_score(stats)

            performance = AnalyticsService.calculate_performance_score(stats)
            stats["performance_score"] = performance
            stats["tier"] = AnalyticsService.assign_tier(performance)

            rankings.append(stats)

        rankings.sort(key=lambda x: x["performance_score"], reverse=True)

        return rankings