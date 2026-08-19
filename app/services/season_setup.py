import random

MIN_TEAMS_PER_SEASON = 4
MAX_TEAMS_PER_SEASON = 20


def suggest_season_config(team_count):
    """
    Determine the tournament structure automatically.

    Supported tournament sizes:
        4  -> Final
        5-8 -> Semi-final
        9-16 -> Quarter-final
        17-20 -> Round of 16

    Maximum tournament size is 20 teams.
    """

    if team_count < MIN_TEAMS_PER_SEASON:
        raise ValueError(
            f"Minimum {MIN_TEAMS_PER_SEASON} teams required."
        )

    if team_count > MAX_TEAMS_PER_SEASON:
        raise ValueError(
            f"Maximum {MAX_TEAMS_PER_SEASON} teams allowed."
        )

    # 4 teams
    if team_count == 4:
        return {
            "team_count": team_count,
            "num_groups": 2,
            "qualifiers_per_group": 1,
            "wildcard_slots": 0,
            "knockout_stage": "final",
        }

    # 5-8 teams
    elif team_count <= 8:
        return {
            "team_count": team_count,
            "num_groups": 2 if team_count <= 7 else 4,
            "qualifiers_per_group": 2 if team_count <= 7 else 1,
            "wildcard_slots": 0,
            "knockout_stage": "semi",
        }

    # 9-16 teams
    elif team_count <= 16:
        return {
            "team_count": team_count,
            "num_groups": 4,
            "qualifiers_per_group": 2,
            "wildcard_slots": 0,
            "knockout_stage": "quarter",
        }

    # 17-20 teams
    else:
        return {
            "team_count": team_count,
            "num_groups": 5,
            "qualifiers_per_group": 3,
            "wildcard_slots": 1,
            "knockout_stage": "r16",
        }


def distribute_ids_into_groups(ids, num_groups):
    shuffled = ids[:]
    random.shuffle(shuffled)

    groups = [[] for _ in range(num_groups)]

    for i, item_id in enumerate(shuffled):
        groups[i % num_groups].append(item_id)

    return groups


def generate_round_robin(ids):
    """
    Circle-method round robin.

    Handles odd numbers of teams by adding a bye slot.
    """

    items = ids[:]

    if len(items) % 2 == 1:
        items.append(None)

    n = len(items)
    rounds = []

    for _ in range(n - 1):
        pairs = []

        for i in range(n // 2):
            a = items[i]
            b = items[n - 1 - i]

            if a is not None and b is not None:
                pairs.append((a, b))

        rounds.append(pairs)

        items = (
            [items[0]]
            + [items[-1]]
            + items[1:-1]
        )

    return rounds