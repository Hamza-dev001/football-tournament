from .. import db
from ..models import PlayerSeasonRating, PlayerCareerRating, EloHistory, Match

K_FACTORS = {
    "group": 20, "r16": 30, "quarter": 35,
    "semi": 40, "third": 25, "final": 50,
}


class EloEngine:

    @staticmethod
    def get_season_rating(player_id, season_id):
        r = PlayerSeasonRating.query.filter_by(player_id=player_id, season_id=season_id).first()
        if not r:
            r = PlayerSeasonRating(player_id=player_id, season_id=season_id)
            db.session.add(r)
            db.session.commit()
        return r

    @staticmethod
    def get_career_rating(player_id):
        r = PlayerCareerRating.query.filter_by(player_id=player_id).first()
        if not r:
            r = PlayerCareerRating(player_id=player_id)
            db.session.add(r)
            db.session.commit()
        return r

    @staticmethod
    def expected_score(a, b):
        return 1 / (1 + 10 ** ((b - a) / 400))

    @staticmethod
    def goal_diff_multiplier(gd):
        if gd <= 1:
            return 1.0
        if gd == 2:
            return 1.5
        return (11 + gd) / 8

    @staticmethod
    def actual_score(hs, aw, perspective):
        if hs == aw:
            return 0.5
        if perspective == "home":
            return 1.0 if hs > aw else 0.0
        return 1.0 if aw > hs else 0.0

    @classmethod
    def revert_match(cls, match: Match):
        rows = EloHistory.query.filter_by(match_id=match.id, is_voided=False).all()
        for row in rows:
            season_r = cls.get_season_rating(row.player_id, row.season_id)
            career_r = cls.get_career_rating(row.player_id)

            season_r.current_elo -= row.season_delta
            career_r.current_elo -= row.career_delta

            season_r.matches_played = max(0, season_r.matches_played - 1)
            career_r.matches_played = max(0, career_r.matches_played - 1)

            for r in (season_r, career_r):
                if row.result == "W":
                    r.wins = max(0, r.wins - 1)
                elif row.result == "D":
                    r.draws = max(0, r.draws - 1)
                else:
                    r.losses = max(0, r.losses - 1)

                r.goals_scored = max(0, r.goals_scored - row.goals_for)
                r.goals_conceded = max(0, r.goals_conceded - row.goals_against)
                if row.goals_against == 0:
                    r.clean_sheets = max(0, r.clean_sheets - 1)

            row.is_voided = True
        db.session.commit()

    @classmethod
    def process_match(cls, match: Match):
        if match.home_score is None or match.away_score is None:
            return

        if match.elo_processed:
            cls.revert_match(match)

        home_player_id = match.home_assignment.player_id
        away_player_id = match.away_assignment.player_id
        season_id = match.season_id

        home_season = cls.get_season_rating(home_player_id, season_id)
        away_season = cls.get_season_rating(away_player_id, season_id)
        home_career = cls.get_career_rating(home_player_id)
        away_career = cls.get_career_rating(away_player_id)

        k = K_FACTORS.get(match.stage, 20)
        gd = abs(match.home_score - match.away_score)
        g = cls.goal_diff_multiplier(gd)

        w_home = cls.actual_score(match.home_score, match.away_score, "home")
        w_away = 1 - w_home

        we_home_season = cls.expected_score(home_season.current_elo, away_season.current_elo)
        we_home_career = cls.expected_score(home_career.current_elo, away_career.current_elo)

        d_home_season = k * g * (w_home - we_home_season)
        d_away_season = k * g * (w_away - (1 - we_home_season))
        d_home_career = k * g * (w_home - we_home_career)
        d_away_career = k * g * (w_away - (1 - we_home_career))

        home_season.apply_elo_change(d_home_season)
        away_season.apply_elo_change(d_away_season)
        home_career.apply_elo_change(d_home_career)
        away_career.apply_elo_change(d_away_career)

        home_season.record_result(match.home_score, match.away_score)
        away_season.record_result(match.away_score, match.home_score)
        home_career.record_result(match.home_score, match.away_score)
        away_career.record_result(match.away_score, match.home_score)

        home_result = "W" if w_home == 1 else ("D" if w_home == 0.5 else "L")
        away_result = "W" if w_away == 1 else ("D" if w_away == 0.5 else "L")

        db.session.add(EloHistory(
            player_id=home_player_id, opponent_id=away_player_id, match_id=match.id,
            season_id=season_id, season_delta=d_home_season, career_delta=d_home_career,
            result=home_result, goals_for=match.home_score, goals_against=match.away_score,
            goal_difference=gd, stage=match.stage
        ))
        db.session.add(EloHistory(
            player_id=away_player_id, opponent_id=home_player_id, match_id=match.id,
            season_id=season_id, season_delta=d_away_season, career_delta=d_away_career,
            result=away_result, goals_for=match.away_score, goals_against=match.home_score,
            goal_difference=gd, stage=match.stage
        ))

        match.elo_processed = True
        db.session.commit()

    @staticmethod
    def expected_win_probability(player_a_id, player_b_id, season_id):
        rating_a = EloEngine.get_season_rating(player_a_id, season_id)
        rating_b = EloEngine.get_season_rating(player_b_id, season_id)
        return EloEngine.expected_score(rating_a.current_elo, rating_b.current_elo)