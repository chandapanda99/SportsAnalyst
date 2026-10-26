"""Bounded, gap-aware CFB sequence alignment with explicit ambiguity rejection."""
from array import array


def _weight(left, right):
    required = ("quarter", "team_id", "down", "distance", "yards_to_goal", "play_type", "yards_gained")
    if any(left.get(key) is None or right.get(key) is None or left[key] != right[key] for key in required):
        return 0
    if left.get("no_play") or right.get("no_play") or left.get("penalty") or right.get("penalty"):
        return 0
    for key in ("home_score", "away_score", "end_yards_to_goal", "drive_key"):
        if left.get(key) is not None and right.get(key) is not None and left[key] != right[key]:
            return 0
    has_clock = left.get("clock") is not None and right.get("clock") is not None
    same_clock = has_clock and left["clock"] == right["clock"]
    same_drive = left.get("drive_key") is not None and left.get("drive_key") == right.get("drive_key")
    same_scores = all(left.get(key) is not None and left.get(key) == right.get(key) for key in ("home_score", "away_score"))
    # Missing play clocks require both a verified drive and score checkpoint.
    if not has_clock and not (same_drive and same_scores):
        return 0
    same_end = left.get("end_yards_to_goal") is not None and left.get("end_yards_to_goal") == right.get("end_yards_to_goal")
    # Feeds may record snap vs end clocks. Never invent a clock correction:
    # a disagreement requires corroborated drive, scores AND end position.
    if has_clock and not same_clock and not (same_drive and same_scores and same_end):
        return 0
    return 10 + 3 * same_clock + 3 * same_drive + 2 * same_scores + same_end


def align_sequences(primary, secondary, *, game_verified):
    empty = {"matches": {}, "evidence": {}, "ambiguous_primary": [],
             "unmatched_primary": [str(row.get("id")) for row in primary],
             "unmatched_secondary": [str(row.get("id")) for row in secondary]}
    if len(primary) > 1000 or len(secondary) > 1000:
        raise ValueError("Sequence alignment is limited to 1000 events per provider/game")
    identifiers = [[str(row.get("id") or "") for row in rows] for rows in (primary, secondary)]
    if not game_verified or any(not all(ids) or len(ids) != len(set(ids)) for ids in identifiers):
        return empty
    n, m = len(primary), len(secondary)
    weights = {}
    for i, left in enumerate(primary):
        for j, right in enumerate(secondary):
            value = _weight(left, right)
            if value > 0:
                weights[i, j] = value
                if len(weights) > 25000:
                    return {**empty, "reason": "candidate_budget_exceeded"}
    forward = [array("i", [0]) * (m + 1) for _ in range(n + 1)]
    backward = [array("i", [0]) * (m + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(m):
            forward[i + 1][j + 1] = max(forward[i][j + 1], forward[i + 1][j],
                                        forward[i][j] + weights.get((i, j), 0))
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            backward[i][j] = max(backward[i + 1][j], backward[i][j + 1],
                                 backward[i + 1][j + 1] + weights.get((i, j), 0))
    best = forward[n][m]
    optimal = [(i, j) for (i, j), weight in weights.items()
               if forward[i][j] + weight + backward[i + 1][j + 1] == best]
    row_counts, col_counts = [0] * n, [0] * m
    row_min, row_max = [m] * n, [-1] * n
    for i, j in optimal:
        row_counts[i] += 1
        col_counts[j] += 1
        row_min[i], row_max[i] = min(row_min[i], j), max(row_max[i], j)
    before, after = [-1] * n, [m] * n
    for i in range(1, n):
        before[i] = max(before[i - 1], row_max[i - 1])
    for i in range(n - 2, -1, -1):
        after[i] = min(after[i + 1], row_min[i + 1])
    matches, evidence, ambiguous = {}, {}, set()
    for i, j in optimal:
        # Accept only links compatible with EVERY optimal candidate. Tied,
        # crossing or repeated-context alternatives remain explicitly unresolved.
        conflict = row_counts[i] > 1 or col_counts[j] > 1 or before[i] >= j or after[i] <= j
        if conflict:
            ambiguous.add(str(primary[i]["id"]))
            continue
        identity = str(primary[i]["id"])
        matches[identity] = str(secondary[j]["id"])
        evidence[identity] = {"method": "unique monotonic context alignment", "weight": weights[i, j],
                              "verified_drive": primary[i].get("drive_key") == secondary[j].get("drive_key")
                                                and primary[i].get("drive_key") is not None,
                              "clock_recorded_both": primary[i].get("clock") is not None and secondary[j].get("clock") is not None}
        evidence[identity]["clock_disagreement"] = (evidence[identity]["clock_recorded_both"]
                                                    and primary[i]["clock"] != secondary[j]["clock"])
    return {"matches": matches, "evidence": evidence, "ambiguous_primary": sorted(ambiguous),
            "unmatched_primary": [identity for identity in identifiers[0] if identity not in matches],
            "unmatched_secondary": [identity for identity in identifiers[1] if identity not in matches.values()]}
