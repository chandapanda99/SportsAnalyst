"""Calendar-month context from the same recorded match measurements as comparisons."""
import hashlib
import json
from datetime import date

import polars as pl

from sports_analyst.datasets.soccer.statistics import EVENT_METRICS, MATCH_METRICS, event_value, measured_value
from sports_analyst.models import AggregateEvidence, stable_id


def monthly_evidence(plugin, request, frames, supplemental, aggregates, metrics, execution_id, manifest_ids):
    # Reuse already-comparable metrics; add small, relevant context from installed data only.
    candidates = [a.metric for a in aggregates if a.metric in metrics and metrics[a.metric][1] != "season_statistics"]
    if request.subject.type == "team":
        candidates += ["fotmob_expected_goals_per_match", "fotmob_expected_goals_on_target_per_match", "pass_completion_rate",
                       "goals_for_per_match", "goals_against_per_match", "shots_per_match", "possession_pct"]

    def calculate(name, season, rows):
        def get(dataset):
            return supplemental.get(dataset, {}).get(season, pl.DataFrame())
        if name in MATCH_METRICS:
            return measured_value(name, rows, get(MATCH_METRICS[name][1]), str(request.subject.id))
        if name in EVENT_METRICS:
            return event_value(name, rows, get("open_events"), str(request.subject.id))
        return plugin._value(name, rows, get("team_stats"), get("lineups"), get("key_events"),
                             str(request.subject.id), get("player_game_logs"), get("expected_goals"), get("player_expected_goals"))

    output, limitations, months = [], [], {}
    for window_name, (_, rows) in frames.items():
        buckets = {}
        for row in rows:
            try:
                month = date.fromisoformat(str(row["date"])[:10]).strftime("%Y-%m")
            except (ValueError, KeyError):
                limitations.append(f"Monthly {window_name} context unavailable: missing or invalid recorded match dates.")
                buckets = {}
                break
            buckets.setdefault(month, []).append(row)
        months[window_name] = buckets
    included = 0
    for name in dict.fromkeys(candidates):
        if included >= 6:
            break
        try:
            unavailable = any(calculate(name, window.season, rows)[0] is None for window, rows in frames.values())
        except ValueError as error:
            limitations.append(f"Monthly {metrics[name][0]} context failed validation: {error}")
            continue
        if unavailable:
            continue
        included += 1
        source = next((a for a in aggregates if a.metric == name), None)
        for window_name, (window, _rows) in frames.items():
            for month, sample in sorted(months[window_name].items()):
                value, count = calculate(name, window.season, sample)
                if value is None or not count:
                    continue
                identity = {"execution": execution_id, "metric": name, "window": window_name,
                            "month": month, "games": sorted(r["game_id"] for r in sample), "value": value,
                            "manifests": sorted(manifest_ids)}
                output.append(AggregateEvidence(evidence_id=stable_id("evidence", identity), metric="soccer_monthly",
                    label=f"{metrics[name][0]} · {month} · {window_name}", value=value, unit=metrics[name][4], sample_size=count,
                    row_set_sha256=hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
                    dataset_manifest_ids=manifest_ids, tool_execution_id=execution_id,
                    caveats=[*(source.caveats if source else []),
                             *(["FotMob-reported values; upstream model version undisclosed, stability across seasons unverified. "
                                "Missing matches are not filled from another provider."] if metrics[name][1] == "match_analytics" else []),
                             f"Calendar month {month}: {count}/{len(sample)} qualifying matches. Missing values are not zero.",
                             "Monthly context is descriptive; unlike metrics can have different covered-match samples."],
                    context={"objective": "Monthly soccer performance", "window": window_name, "group": {"month": month},
                             "time_bucket": {"field": "date", "interval": "month"}, "metric_label": metrics[name][0],
                             "measure": {"op": "defined_metric", "field": name}, "qualifying_rows": len(sample),
                             "definition": metrics[name][5], "aggregation": "recomputed from recorded match observations",
                             "game_ids": sorted(r["game_id"] for r in sample),
                             "source_dataset": metrics[name][1]}))
    return output, limitations
