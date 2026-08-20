from flask import Blueprint, render_template, redirect, url_for, request, session
from flask_login import login_user, login_required, logout_user
from sqlalchemy import or_
from datetime import datetime
import random

from .models import (
    User, Match, Group, Season, Team, SeasonAssignment,
    EloHistory, PlayerSeasonRating, get_active_season
)
from . import db
from .routes import stage_exists, stage_complete
from .services.elo_engine import EloEngine
from .services.notification_service import WhatsAppNotificationService
from .services.season_manager import SeasonManager, now_lagos, next_10am_lagos
from .services.season_setup import (
    suggest_season_config, MIN_TEAMS_PER_SEASON, MAX_TEAMS_PER_SEASON
)

admin = Blueprint("admin", __name__)


# ==========================================================
# MATCHDAY / CLOCK
# ==========================================================

def season_clock_running(season=None):
    season = season or get_active_season()
    if not season or not season.started_at:
        return False
    return now_lagos() >= season.started_at


def get_current_matchday():
    season = get_active_season()
    if not season_clock_running(season):
        return 1
    diff = now_lagos() - season.started_at
    return min(diff.days + 1, 3)


def is_match_locked(match):
    if session.get("override_deadline"):
        return False

    # ==========================================================
    # STAGE LOCK (FIX)
    # Once the Round of 16 has been generated for this match's season,
    # the ENTIRE Group Stage becomes permanently locked — regardless of
    # matchday number or whether the season clock is running. This
    # prevents an admin from silently editing a completed group match
    # after qualifiers/ELO have already been computed from it.
    # The Override button (session["override_deadline"]) still bypasses
    # this, exactly as it already bypasses the time-based lock below.
    # ==========================================================
    if match.stage == "group" and stage_exists("r16", match.season_id):
        return True

    if match.stage != "group":
        return False
    if not season_clock_running():
        return False

    current_matchday = get_current_matchday()
    if match.matchday > current_matchday:
        return True
    if match.matchday < current_matchday and match.is_completed:
        return True
    return False


# ==========================================================
# AUTOMATIC TITLE AWARD (STEP 10)
# ==========================================================

def _award_title_if_final(match):
    """
    Shared, idempotent title-award helper.

    Rules:
    - Only operates on stage == "final".
    - Requires a completed, decisive score (no draws).
    - Checks match.title_awarded BEFORE touching titles_won.
    - Increments the winner's titles_won exactly once.
    - Sets match.title_awarded = True in the SAME commit as the
      titles_won increment, so there is no window where one succeeds
      without the other.
    - Safe to call repeatedly (e.g. from bulk_update every time it
      runs, or from the manual /admin/award-title route) — after the
      first successful award, it always returns the "already awarded"
      message and makes no further changes.

    NOTE (documented limitation, per Step 10 scope):
    If a Final that has ALREADY been awarded is later corrected and
    the winner changes, this helper will NOT automatically reverse or
    re-award the title. Reversing an already-awarded title requires an
    explicit admin correction/reversal mechanism, which is intentionally
    NOT implemented in this step. This mirrors the existing behavior of
    elo_processed / EloEngine.revert_match(), which also requires an
    explicit manual reset rather than automatic re-evaluation.
    """
    if match.stage != "final":
        return None
    if match.home_score is None or match.away_score is None:
        return "❌ Final not completed yet."
    if match.home_score == match.away_score:
        return (
            f"❌ The Final is a draw ({match.home_score}-{match.away_score}). "
            f"A title cannot be awarded until a decisive result is entered."
        )

    if match.title_awarded:
        return "ℹ️ Title has already been awarded for this Final. No changes made."

    winner_player = (
        match.home_assignment.player if match.home_score > match.away_score
        else match.away_assignment.player
    )
    winner_player.titles_won += 1
    match.title_awarded = True
    db.session.commit()

    # This helper is shared by bulk result submission and the manual award
    # route, so a champion notification is only queued for a newly awarded
    # title regardless of which workflow was used.
    WhatsAppNotificationService.enqueue_champion(match.id)

    return f"🏆 Title awarded to {winner_player.username}!"


# ==========================================================
# LOGIN / LOGOUT
# ==========================================================

@admin.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form.get("username")).first()
        if user and user.check_password(request.form.get("password")):
            login_user(user)
            return redirect(url_for("admin.dashboard"))
        return "❌ Invalid Credentials"
    return render_template("admin_login.html")


@admin.route("/logout")
@login_required
def logout():
    session.pop("override_deadline", None)
    logout_user()
    return redirect(url_for("main.home"))


# ==========================================================
# DASHBOARD
# ==========================================================

@admin.route("/dashboard")
@login_required
def dashboard():
    season = get_active_season()
    stages = ["group", "r16", "quarter", "semi", "third", "final"]
    data = {}

    if season:
        for stage in stages:
            data[stage] = (
                Match.query
                .filter_by(stage=stage, season_id=season.id)
                .order_by(Match.matchday, Match.id)
                .all()
            )

    return render_template(
        "admin_dashboard.html",
        data=data,
        season=season,
        current_matchday=get_current_matchday(),
        override_active=session.get("override_deadline", False),
        season_started=season_clock_running(season)
    )


# ==========================================================
# BULK SCORE UPDATE
# ==========================================================

@admin.route("/bulk-update", methods=["POST"])
@login_required
def bulk_update():
    season = get_active_season()
    matches = Match.query.filter_by(season_id=season.id).all()
    touched = []
    rejected = []

    for match in matches:
        if is_match_locked(match):
            continue

        home_score = request.form.get(f"home_{match.id}")
        away_score = request.form.get(f"away_{match.id}")

        if home_score != "" and away_score != "":
            home_score = int(home_score)
            away_score = int(away_score)

            # ==========================================================
            # KNOCKOUT DRAW PROTECTION (FIX)
            # A knockout match (any stage other than "group") must never
            # be saved as a scoreline draw. This prevents the system from
            # ever silently deciding a winner on a tie (e.g. 1-1).
            # ==========================================================
            if match.stage != "group" and home_score == away_score:
                rejected.append((match, home_score, away_score))
                continue

            match.home_score = home_score
            match.away_score = away_score
            match.is_completed = True
            touched.append(match)

    db.session.commit()

    for match in touched:
        EloEngine.process_match(match)

    # ==========================================================
    # AUTOMATIC TITLE AWARD (STEP 10)
    # If any touched match is a completed, decisive Final, automatically
    # award the title. _award_title_if_final() is fully idempotent, so
    # this is safe to call every time bulk_update() runs — it will only
    # ever award the title once per Final match.
    # ==========================================================
    for match in touched:
        if match.stage == "final":
            _award_title_if_final(match)

    # All tournament persistence (scores, ELO, and title award) is complete
    # before delivery is queued. The service uses an isolated background
    # context, so an unavailable WhatsApp API cannot delay this submission.
    for match in touched:
        WhatsAppNotificationService.enqueue_match_result(match.id)

    if rejected:
        lines = []
        for m, hs, aw in rejected:
            lines.append(
                f"{m.home_assignment.display_name} vs {m.away_assignment.display_name} "
                f"({m.stage}) — {hs}-{aw}"
            )
        message = "<br>".join(lines)
        return (
            f"✅ {len(touched)} match(es) saved successfully.<br><br>"
            f"❌ The following knockout match(es) were NOT saved because they ended in a draw. "
            f"Knockout matches cannot end in a draw — please enter the actual decisive scoreline "
            f"(e.g. after extra time):<br><br>{message}"
            f"<br><br><a href='{url_for('admin.dashboard')}'>⬅ Back to Dashboard</a>"
        )

    return redirect(url_for("admin.dashboard"))


# ==========================================================
# DEADLINE OVERRIDE
# ==========================================================

@admin.route("/override-deadline", methods=["POST"])
@login_required
def override_deadline():
    session["override_deadline"] = True
    return redirect(url_for("admin.dashboard"))


# ==========================================================
# SEASON MANAGEMENT
# ==========================================================

@admin.route("/seasons")
@login_required
def list_seasons():
    seasons = Season.query.order_by(Season.season_number.desc()).all()
    return render_template("admin_seasons.html", seasons=seasons)


@admin.route("/seasons/create", methods=["POST"])
@login_required
def create_season():
    name = request.form.get("name")
    SeasonManager.create_season(name)
    return redirect(url_for("admin.list_seasons"))


@admin.route("/seasons/<int:season_id>/activate")
@login_required
def activate_season(season_id):
    SeasonManager.activate_season(season_id)
    return redirect(url_for("admin.list_seasons"))


@admin.route("/seasons/<int:season_id>/complete")
@login_required
def complete_season(season_id):
    SeasonManager.complete_season(season_id)
    return redirect(url_for("admin.list_seasons"))


@admin.route("/seasons/<int:season_id>/start-clock", methods=["POST"])
@login_required
def start_season_clock(season_id):
    mode = request.form.get("mode", "now")
    start_at = next_10am_lagos() if mode == "next10" else now_lagos()
    SeasonManager.start_season_clock(season_id, start_at=start_at)
    return redirect(url_for("admin.dashboard"))


@admin.route("/seasons/<int:season_id>/stop-clock", methods=["POST"])
@login_required
def stop_season_clock(season_id):
    SeasonManager.stop_season_clock(season_id)
    return redirect(url_for("admin.dashboard"))


# ==========================================================
# SEASON ASSIGNMENT SCREEN
# ==========================================================

@admin.route("/season-entries", methods=["GET", "POST"])
@login_required
def season_entries():
    season = get_active_season()
    if not season:
        return "❌ No active season."

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        team_id = request.form.get("team_id")

        # ==========================================================
        # MAXIMUM PLAYER LIMIT (DYNAMIC 4-20 PLAYER SUPPORT)
        # A season can never have more than MAX_TEAMS_PER_SEASON
        # players assigned. This is checked BEFORE attempting the
        # assignment, so no partial/invalid assignment is ever created.
        # ==========================================================
        current_count = SeasonAssignment.query.filter_by(season_id=season.id).count()
        if current_count >= MAX_TEAMS_PER_SEASON:
            return f"❌ Maximum {MAX_TEAMS_PER_SEASON} players already assigned for this season."

        try:
            SeasonManager.assign_player_to_club(season.id, username, int(team_id))
        except ValueError as e:
            return f"❌ {e}"
        return redirect(url_for("admin.season_entries"))

    entries = SeasonAssignment.query.filter_by(season_id=season.id).all()
    available_clubs = SeasonManager.get_unassigned_clubs(season.id)

    suggested = None
    if len(entries) >= MIN_TEAMS_PER_SEASON:
        suggested = suggest_season_config(len(entries))

    return render_template(
        "admin_season_entries.html",
        season=season, entries=entries,
        available_clubs=available_clubs, suggested=suggested,
        min_teams=MIN_TEAMS_PER_SEASON,
        max_teams=MAX_TEAMS_PER_SEASON
    )


@admin.route("/season-entries/<int:assignment_id>/remove")
@login_required
def remove_season_entry(assignment_id):
    SeasonManager.remove_assignment(assignment_id)
    return redirect(url_for("admin.season_entries"))


@admin.route("/season-entries/finalize", methods=["POST"])
@login_required
def finalize_season_entries():
    season = get_active_season()

    if not season:
        return "❌ No active season."

    entries = SeasonAssignment.query.filter_by(
        season_id=season.id
    ).all()

    if len(entries) < MIN_TEAMS_PER_SEASON:
        return (
            f"❌ Need at least {MIN_TEAMS_PER_SEASON} teams assigned. "
            f"Currently: {len(entries)}."
        )

    if len(entries) > MAX_TEAMS_PER_SEASON:
        return (
            f"❌ Cannot finalize — {len(entries)} teams assigned "
            f"exceeds the maximum of {MAX_TEAMS_PER_SEASON}."
        )

    # ----------------------------------------------------------
    # FINALIZE SEASON CONFIGURATION
    # ----------------------------------------------------------
    config = SeasonManager.finalize_season_config(
        season.id,
        len(entries)
    )

    # ----------------------------------------------------------
    # CREATE GROUPS
    # ----------------------------------------------------------
    existing_groups = Group.query.filter_by(
        season_id=season.id
    ).all()

    if existing_groups:
        return (
            f"❌ Season {season.season_number} already has "
            f"{len(existing_groups)} groups. No fixtures were changed."
        )

    num_groups = config["num_groups"]

    group_names = [
        chr(ord("A") + i)
        for i in range(num_groups)
    ]

    groups = []

    for group_name in group_names:
        group = Group(
            name=f"Group {group_name}",
            season_id=season.id
        )
        db.session.add(group)
        groups.append(group)

    db.session.flush()

    # ----------------------------------------------------------
    # DISTRIBUTE THE EXISTING PLAYERS INTO GROUPS
    # ----------------------------------------------------------
    shuffled_entries = entries[:]
    random.shuffle(shuffled_entries)

    for index, assignment in enumerate(shuffled_entries):
        group = groups[index % num_groups]
        assignment.group_id = group.id

    db.session.flush()

    # ----------------------------------------------------------
    # GENERATE HOME + AWAY GROUP FIXTURES
    # ----------------------------------------------------------
    for group in groups:
        group_entries = [
            assignment
            for assignment in entries
            if assignment.group_id == group.id
        ]

        # Every pair plays twice: home and away.
        matchday = 1

        for i in range(len(group_entries)):
            for j in range(i + 1, len(group_entries)):

                home = group_entries[i]
                away = group_entries[j]

                db.session.add(
                    Match(
                        season_id=season.id,
                        home_assignment_id=home.id,
                        away_assignment_id=away.id,
                        stage="group",
                        group_id=group.id,
                        matchday=matchday,
                        is_completed=False
                    )
                )

                db.session.add(
                    Match(
                        season_id=season.id,
                        home_assignment_id=away.id,
                        away_assignment_id=home.id,
                        stage="group",
                        group_id=group.id,
                        matchday=matchday,
                        is_completed=False
                    )
                )

                matchday += 1

    db.session.commit()

    return redirect(url_for("admin.dashboard"))


# ==========================================================
# HELPER: BUILD QUALIFIERS
# ==========================================================

def build_group_qualifiers():
    season = get_active_season()
    groups = Group.query.filter_by(season_id=season.id).all()

    qualified = []
    leftovers = []
    qualifiers_n = season.qualifiers_per_group or 3
    wildcards_n = season.wildcard_slots or 0

    for group in groups:
        table = []
        for assignment in group.assignments:
            points = gf = ga = 0
            matches = Match.query.filter(
                Match.stage == "group", Match.season_id == season.id,
                or_(
                    Match.home_assignment_id == assignment.id,
                    Match.away_assignment_id == assignment.id
                )
            ).all()

            for m in matches:
                if m.home_score is None:
                    continue
                if m.home_assignment_id == assignment.id:
                    gf += m.home_score; ga += m.away_score
                    if m.home_score > m.away_score: points += 3
                    elif m.home_score == m.away_score: points += 1
                else:
                    gf += m.away_score; ga += m.home_score
                    if m.away_score > m.home_score: points += 3
                    elif m.away_score == m.home_score: points += 1

            table.append({
                "assignment": assignment, "group": group.name,
                "points": points, "gd": gf - ga, "gf": gf
            })

        table.sort(key=lambda x: (x["points"], x["gd"], x["gf"]), reverse=True)
        qualified.extend(table[:qualifiers_n])
        leftovers.extend(table[qualifiers_n:])

    if wildcards_n > 0 and leftovers:
        leftovers.sort(key=lambda x: (x["points"], x["gd"], x["gf"]), reverse=True)
        qualified.extend(leftovers[:wildcards_n])

    return qualified


# ==========================================================
# ADMIN OVERVIEW
# ==========================================================

@admin.route("/overview")
@login_required
def overview():
    context = {
        "qualified_teams": build_group_qualifiers(),
        "group_complete": stage_complete("group"),

        # Knockout stage existence
        "r16_exists": stage_exists("r16"),
        "quarter_exists": stage_exists("quarter"),
        "semi_exists": stage_exists("semi"),
        "final_exists": stage_exists("final"),
        "third_exists": stage_exists("third"),

        # Knockout stage completion
        "r16_complete": stage_complete("r16"),
        "quarter_complete": stage_complete("quarter"),
        "semi_complete": stage_complete("semi"),
    }

    return render_template("overview.html", context=context)


# ==========================================================
# DYNAMIC KNOCKOUT PROGRESSION (4-20 PLAYER SUPPORT)
#
# The knockout stage is NEVER hard-coded to always start at Round of 16.
# Instead, the correct starting stage is derived from the ACTUAL number
# of group-stage qualifiers:
#
#     2 qualifiers  -> Final
#     4 qualifiers  -> Semi-final
#     8 qualifiers  -> Quarter-final
#    16 qualifiers  -> Round of 16
#
# After the first knockout stage exists, each subsequent stage is
# generated from the winners of the previous stage, exactly as before
# (reusing the existing generate_next_stage() winner-advancement logic).
#
# This function is the single source of truth for "what stage comes
# next" — it is used by ALL FOUR of the existing button routes below,
# so no matter which button an admin clicks, the system always
# generates the correct stage and never a duplicate.
# ==========================================================

KNOCKOUT_ORDER = ["r16", "quarter", "semi", "final"]

QUALIFIER_COUNT_TO_STAGE = {
    2: "final",
    4: "semi",
    8: "quarter",
    16: "r16",
}


def _determine_next_stage(season):
    """
    Returns (next_stage_name, qualified_list, error_message).

    - If qualified_list is not None, the next stage must be built
      directly from these group-stage qualifiers (this is the FIRST
      knockout stage for this season).
    - If qualified_list is None and error_message is None, the next
      stage must be built from the winners of the last completed
      knockout stage (use the existing generate_next_stage() helper).
    - If error_message is set, stop and show it to the admin.
    """
    if not stage_complete("group", season.id):
        return None, None, "❌ Complete group stage first."

    existing_stages = [s for s in KNOCKOUT_ORDER if stage_exists(s, season.id)]

    if not existing_stages:
        qualified = build_group_qualifiers()
        count = len(qualified)
        target = QUALIFIER_COUNT_TO_STAGE.get(count)
        if not target:
            return None, None, (
                f"❌ {count} qualifiers does not match a supported bracket size "
                f"(2, 4, 8, or 16). Adjust qualifiers/wildcards in Season Entries."
            )
        return target, qualified, None

    last_stage = existing_stages[-1]

    if last_stage == "final":
        return None, None, "❌ The Final has already been generated. There is no further stage."

    if not stage_complete(last_stage, season.id):
        return None, None, f"❌ Complete {last_stage} first."

    next_index = KNOCKOUT_ORDER.index(last_stage) + 1
    next_stage = KNOCKOUT_ORDER[next_index]
    return next_stage, None, None


def _generate_from_qualifiers(season, stage_name, qualified):
    pool = qualified[:]
    random.shuffle(pool)
    pairings = []

    while len(pool) >= 2:
        team1 = pool.pop(0)
        opponent_index = next(
            (i for i, t in enumerate(pool) if t["group"] != team1["group"]), 0
        )
        opponent = pool.pop(opponent_index)
        pairings.append((team1["assignment"], opponent["assignment"]))

    for a1, a2 in pairings:
        db.session.add(Match(
            home_assignment_id=a1.id, away_assignment_id=a2.id,
            stage=stage_name, matchday=1, is_completed=False, season_id=season.id
        ))

    db.session.commit()


def generate_next_stage(current_stage, next_stage, use_losers=False):
    """
    Generates `next_stage` from the winners (or losers) of `current_stage`.

    Unchanged from before — still used for every knockout transition
    AFTER the first stage (r16->quarter, quarter->semi, semi->final,
    semi->third), and now also called dynamically by
    generate_next_fixtures() below.
    """
    season = get_active_season()

    if stage_exists(next_stage, season.id):
        return f"❌ {next_stage} already generated."
    if not stage_complete(current_stage, season.id):
        return f"❌ Complete {current_stage} first."

    matches = Match.query.filter_by(stage=current_stage, season_id=season.id).all()
    advancing = []

    for m in matches:
        if m.home_score is None:
            return f"❌ Some matches in {current_stage} are incomplete."

        # ==========================================================
        # KNOCKOUT DRAW PROTECTION (FIX - defensive safety net)
        # This should never trigger if bulk_update() is working correctly,
        # since draws can no longer be saved for knockout matches. This
        # exists purely as a safeguard against legacy/edited data.
        # ==========================================================
        if m.home_score == m.away_score:
            return (
                f"❌ Match #{m.id} in {current_stage} "
                f"({m.home_assignment.display_name} vs {m.away_assignment.display_name}) "
                f"is a draw ({m.home_score}-{m.away_score}). Knockout matches cannot end in a draw. "
                f"Please correct this result before generating {next_stage}."
            )

        if use_losers:
            if m.home_score > m.away_score:
                advancing.append(m.away_assignment_id)
            else:
                advancing.append(m.home_assignment_id)
        else:
            if m.home_score > m.away_score:
                advancing.append(m.home_assignment_id)
            else:
                advancing.append(m.away_assignment_id)

    if len(advancing) % 2 != 0:
        return f"❌ Uneven {'losers' if use_losers else 'winners'} — cannot generate {next_stage}."

    for i in range(0, len(advancing), 2):
        db.session.add(Match(
            home_assignment_id=advancing[i], away_assignment_id=advancing[i+1],
            stage=next_stage, matchday=1, is_completed=False, season_id=season.id
        ))

    db.session.commit()
    return redirect(url_for("admin.dashboard"))


@admin.route("/generate-next-fixtures")
@login_required
def generate_next_fixtures():
    """
    Single dynamic entry point for generating the next knockout stage.

    Safe to click repeatedly: it will never generate a stage that
    already exists, and it never assumes Round of 16 comes first.
    """
    season = get_active_season()

    next_stage, qualified, error = _determine_next_stage(season)
    if error:
        return error

    if stage_exists(next_stage, season.id):
        return f"❌ {next_stage} already generated."

    if qualified is not None:
        _generate_from_qualifiers(season, next_stage, qualified)
        return redirect(url_for("admin.dashboard"))

    previous_stage = KNOCKOUT_ORDER[KNOCKOUT_ORDER.index(next_stage) - 1]
    return generate_next_stage(previous_stage, next_stage, use_losers=False)


# ==========================================================
# EXISTING BUTTON ROUTES (kept for backward compatibility with the
# current dashboard template — every button now safely delegates to
# the same dynamic engine above, so clicking ANY of these always
# generates the correct next stage for this season, never a duplicate,
# and never a wrongly-assumed Round of 16.
# ==========================================================

@admin.route("/generate-r16")
@login_required
def generate_r16():
    return generate_next_fixtures()


@admin.route("/generate-quarter")
@login_required
def generate_quarter():
    return generate_next_fixtures()


@admin.route("/generate-semi")
@login_required
def generate_semi():
    return generate_next_fixtures()


@admin.route("/generate-final")
@login_required
def generate_final():
    return generate_next_fixtures()


@admin.route("/generate-third")
@login_required
def generate_third():
    return generate_next_stage("semi", "third", use_losers=True)


# ==========================================================
# AWARD TITLE (MANUAL ROUTE — now uses shared idempotent helper)
# ==========================================================

@admin.route("/award-title/<int:match_id>")
@login_required
def award_title(match_id):
    match = Match.query.get_or_404(match_id)
    result = _award_title_if_final(match)

    if result is None:
        return "❌ This match is not a Final."

    return result


# ==========================================================
# RESET R16 + QUARTER
# ==========================================================

@admin.route("/reset-r16-and-quarter")
@login_required
def reset_r16_and_quarter():
    season = get_active_season()
    Match.query.filter_by(stage="quarter", season_id=season.id).delete()

    r16_matches = Match.query.filter_by(stage="r16", season_id=season.id).all()
    for match in r16_matches:
        if match.elo_processed:
            EloEngine.revert_match(match)
        match.home_score = None
        match.away_score = None
        match.is_completed = False
        match.elo_processed = False

    db.session.commit()
    return "✅ R16 and Quarterfinal successfully reset."