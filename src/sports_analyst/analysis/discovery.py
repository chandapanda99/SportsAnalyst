"""Compact, complete metric discovery shared by calculation and narrative agents."""
from collections import Counter


def metric_index(rows):
    counts = Counter(row["metric"] for row in rows)
    return [{"metric": name, "records": counts[name]} for name in sorted(counts)]


def evidence_page(rows, offset=0, limit=30):
    offset, limit = max(0, offset), max(1, min(limit, 50))
    page = rows[offset:offset + limit]
    return {"evidence": page, "total": len(rows),
            "next_offset": offset + len(page) if offset + len(page) < len(rows) else None}
