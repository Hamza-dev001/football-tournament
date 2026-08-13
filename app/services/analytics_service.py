from ..models import Player, EloHistory, get_active_season
from .elo_engine import EloEngine


class AnalyticsService:

    @staticmethod
    def calculate_efficiency(rating):
        if rating.matches_played == 0:
            return 0
        points = (rating.wins * 3) + rating.draws
        return round(points / rating.matches_played, 2)

    @staticmethod
    def calculate_attack_rating(rating):
        if rating.matches_played == 0:
            return 0
        return round(rating.goals_scored / rating.matches_played * 10, 2)

    @staticmethod
    def calculate_defense_rating(rating):
        if rating.matches_played == 0:
            return 0
        return round((rating.clean_sheets * 2) - rating.goals_conceded, 2)

    @staticmethod
    def assign_tier(elo):
        if elo >= 1750:
            return "Legendary"
        elif elo >= 1620:
            return "Elite"
        elif elo >= 1520:
            return "Strong"
        elif elo >= 1420:
            return "Competitive"
        return "Developing"

    @staticmethod
    def get_last_3_form(player_id):
        """
        Returns the player's most recent 3 results as a list, e.g. ["W", "W", "L"],
        ordered oldest to newest (so it reads left-to-right chronologically).
        Uses EloHistory.result, which is already recorded for every processed match
        (group and knockout). Returns an empty list if the player has no history yet.
        """
        rows = (
            EloHistory.query
            .filter_by(player_id=player_id, is_voided=False)
            .order_by(EloHistory.created_at.desc())
            .limit(3)
            .all()
        )
        results = [row.result for row in rows]
        results.reverse()  # oldest -> newest, left to right
        return results

    @staticmethod
    def get_power_rankings():
        """Current-season live rankings, driven by PlayerSeasonRating."""
        season = get_active_season()
        if not season:
            return []

        rankings = []
        for player in Player.query.filter_by(status="ACTIVE").all():
            season_rating = EloEngine.get_season_rating(player.id, season.id)

            rankings.append({
                "player": player,
                "elo": round(season_rating.current_elo, 1),
                "peak_elo": round(season_rating.peak_elo, 1),
                "played": season_rating.matches_played,
                "wins": season_rating.wins,
                "draws": season_rating.draws,
                "losses": season_rating.losses,
                "goals_scored": season_rating.goals_scored,
                "goals_conceded": season_rating.goals_conceded,
                "goal_difference": season_rating.goals_scored - season_rating.goals_conceded,
                "clean_sheets": season_rating.clean_sheets,
                "attack_rating": AnalyticsService.calculate_attack_rating(season_rating),
                "defense_rating": AnalyticsService.calculate_defense_rating(season_rating),
                "efficiency": AnalyticsService.calculate_efficiency(season_rating),
                "tier": AnalyticsService.assign_tier(season_rating.current_elo),
                "form": AnalyticsService.get_last_3_form(player.id),
            })

        rankings.sort(key=lambda x: x["elo"], reverse=True)
        return rankings

    @staticmethod
    def get_career_leaderboard():
        """All-time leaderboard, driven by PlayerCareerRating. Never resets."""
        players = Player.query.all()
        rows = []
        for player in players:
            career = EloEngine.get_career_rating(player.id)
            rows.append({
                "player": player,
                "elo": round(career.current_elo, 1),
                "peak_elo": round(career.peak_elo, 1),
                "played": career.matches_played,
                "wins": career.wins,
                "draws": career.draws,
                "losses": career.losses,
                "titles": player.titles_won,
                "status": player.status,
            })
        rows.sort(key=lambda x: x["elo"], reverse=True)
        return rows

    @staticmethod
    def predict_match(player_a, player_b):
        season = get_active_season()
        rating_a = EloEngine.get_season_rating(player_a.id, season.id)
        rating_b = EloEngine.get_season_rating(player_b.id, season.id)

        prob_a = EloEngine.expected_score(rating_a.current_elo, rating_b.current_elo) * 100
        prob_b = 100 - prob_a
        elo_gap = rating_a.current_elo - rating_b.current_elo

        confidence = "High" if abs(elo_gap) > 150 else "Moderate" if abs(elo_gap) > 60 else "Toss-up"

        return {
            "team_a_prob": round(prob_a, 2),
            "team_b_prob": round(prob_b, 2),
            "elo_a": round(rating_a.current_elo, 1),
            "elo_b": round(rating_b.current_elo, 1),
            "elo_gap": round(elo_gap, 1),
            "confidence": confidence
        }