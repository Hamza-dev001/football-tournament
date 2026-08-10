import random

MIN_TEAMS_PER_SEASON = 4
MAX_TEAMS_PER_SEASON = 20


def suggest_season_config(team_count):
    if team_count < MIN_TEAMS_PER_SEASON:
        raise ValueError(f"Minimum {MIN_TEAMS_PER_SEASON} teams required.")
    if team_count >= 16:
        return {"num_groups": 5, "qualifiers_per_group": 3, "wildcard_slots": 1}
    elif team_count >= 12:
        return {"num_groups": 4, "qualifiers_per_group": 2, "wildcard_slots": 0}
    elif team_count >= 8:
        return {"num_groups": 4, "qualifiers_per_group": 2, "wildcard_slots": 0}
    else:  # 4 - 7
        return {"num_groups": 2, "qualifiers_per_group": 2, "wildcard_slots": 0}


def distribute_ids_into_groups(ids, num_groups):
    shuffled = ids[:]
    random.shuffle(shuffled)
    groups = [[] for _ in range(num_groups)]
    for i, item_id in enumerate(shuffled):
        groups[i % num_groups].append(item_id)
    return groups


def generate_round_robin(ids):
    """
    Circle-method round robin. Handles odd counts via a bye slot (None).
    Returns list of rounds, each round a list of (id_a, id_b) tuples.
    """
    items = ids[:]
    if len(items) % 2 == 1:
        items.append(None)

    n = len(items)
    rounds = []

    for _ in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = items[i], items[n - 1 - i]
            if a is not None and b is not None:
                pairs.append((a, b))
        rounds.append(pairs)
        items = [items[0]] + [items[-1]] + items[1:-1]

    return rounds