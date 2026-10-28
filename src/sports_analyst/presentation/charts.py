"""Shared Vega-Lite specifications for comparison charts."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any


def _display_value(value: float, unit: str | None) -> str:
    normalized_unit = (unit or "").casefold()
    if normalized_unit in {"percentage", "rate", "proportion"} and abs(value) <= 1:
        return f"{value * 100:.1f}%"
    if normalized_unit == "percent_points":
        return f"{value:.1f}%"
    if normalized_unit == "percentage_points":
        return f"{value:.2f} pp"
    if normalized_unit in {"attempts", "completions", "count", "observations", "interceptions", "sacks", "touchdowns", "yards"}:
        return f"{value:,.0f}"
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:,.1f}"
    return f"{value:.3f}" if value != 0 else "0.000"


def _axis_format(values: Sequence[float], unit: str | None) -> str:
    normalized_unit = (unit or "").casefold()
    largest = max((abs(value) for value in values), default=0)
    if normalized_unit in {"percentage", "rate", "proportion"} and largest <= 1:
        return ".1%"
    if normalized_unit in {
        "attempts",
        "completions",
        "count",
        "observations",
        "interceptions",
        "sacks",
        "touchdowns",
        "yards",
    } or largest >= 100:
        return ",.0f"
    if largest >= 1:
        return ".1f"
    return ".2f"


def metric_row_comparison_spec(rows: Iterable[dict[str, Any]], *, series_field: str, series_order: Sequence[str],
                               comparison_kind: str | None = None, color_field: str | None = None) -> dict[str, Any]:
    """Render unlike metrics as independently scaled, easy-to-target comparison rows."""
    values: list[dict[str, Any]] = []
    metric_order: list[str] = []
    for row in rows:
        value = row.get("value")
        if type(value) not in (int, float) or not math.isfinite(value):
            continue
        metric = str(row["metric"])
        # Repair legacy football chart units using the metric's definition,
        # never its magnitude: CPOE is already on a percentage-point scale.
        unit = row.get("unit")
        if metric.casefold() == "cpoe" and unit in {"rate", "rate or per play", "per play"}:
            unit = "percentage_points"
        elif unit == "rate or per play" and "rate" in metric.casefold():
            unit = "rate"
        series = str(row[series_field])
        if metric not in metric_order:
            metric_order.append(metric)
        values.append(
            {
                **row,
                "unit": unit,
                "value": float(value),
                "display_value": _display_value(float(value), unit),
                "sample_display": f"{row['sample_size']:,}" if row.get("sample_size") is not None else "Not recorded",
                "context_label": row.get("context_label") or "Not recorded",
                "series_order": series_order.index(series) if series in series_order else len(series_order),
            }
        )

    comparison_kind = comparison_kind or ("season-trend" if series_field == "season" else "period-comparison")
    order = list(dict.fromkeys([*series_order, *(str(row[series_field]) for row in values)]))
    color_order = list(dict.fromkeys(str(row[color_field]) for row in values)) if color_field else order
    metric_specs = []
    for metric in metric_order:
        metric_values = [row for row in values if row["metric"] == metric]
        numeric_values = [float(row["value"]) for row in metric_values]
        unit = str(metric_values[0].get("unit") or "") if metric_values else ""
        smallest, largest = min(numeric_values), max(numeric_values)
        proportion = unit.casefold() in {"percentage", "rate", "proportion"} and max(abs(smallest), abs(largest)) <= 1
        padding = max((largest - smallest) * .18, max(abs(smallest), abs(largest)) * .04, .002 if proportion else .01)
        lower, upper = smallest - padding, largest + padding
        if unit.casefold() in {"percentage", "rate", "proportion"} and 0 <= smallest <= largest <= 1:
            lower, upper = max(0, lower), min(1, upper)
        elif unit == "percent_points" and 0 <= smallest <= largest <= 100:
            lower, upper = max(0, lower), min(100, upper)
        elif unit in {"count", "observations", "attempts", "completions"} and smallest >= 0:
            lower, upper = max(0, math.floor(lower)), max(math.ceil(upper), 1)
        axis_format = _axis_format(numeric_values, unit)
        if proportion:
            precision = max(1, min(5, math.ceil(-math.log10((upper - lower) * 100 / 4))))
            axis_format = f".{precision}%"
        y_encoding = {
            "field": "value",
            "type": "quantitative",
            "scale": {"zero": False, "nice": False, "domain": [lower, upper]},
            "axis": {
                "title": None,
                "tickCount": 4,
                "format": axis_format,
                "grid": True,
                **({"tickMinStep": 1} if unit in {"count", "observations", "attempts", "completions", "yards"} else {}),
                **({"labelExpr": "format(datum.value, '.1f') + '%'"} if unit == "percent_points" else {}),
                **({"labelExpr": "format(datum.value, '.2f') + ' pp'"} if unit == "percentage_points" else {}),
            },
        }
        x_encoding = {
            "field": series_field,
            "type": "ordinal",
            "sort": order,
            "axis": {
                "title": None,
                "ticks": False,
                "domain": False,
                "grid": False,
                "labels": True,
                "labelAngle": 0,
                "labelLimit": 160,
                "labelOverlap": "greedy",
            },
        }
        if comparison_kind == "monthly-trend":
            x_encoding = {"field": "month", "type": "temporal", "axis": {
                "title": "Calendar month", "format": "%b %Y", "labelAngle": -35,
                "grid": False, "labelOverlap": "greedy"}}
        color_encoding = {
            "field": color_field or series_field,
            "type": "nominal",
            "sort": color_order,
            "scale": {"domain": color_order},
            "legend": None,
        }
        series_title = {"season-trend": "Season", "grouped-observations": "Recorded context",
                        "monthly-trend": "Month and context"}.get(comparison_kind, "Period")
        tooltip = [
            {"field": "metric", "type": "nominal", "title": "Metric"},
            {"field": series_field, "type": "nominal", "title": series_title},
            {"field": "display_value", "type": "nominal", "title": "Value"},
            *([{"field": "context_label", "type": "nominal", "title": "Recorded context"}]
              if any(row["context_label"] != "Not recorded" for row in metric_values) else []),
            *([{"field": "sample_display", "type": "nominal", "title": "Sample size"}]
              if any(row["sample_display"] != "Not recorded" for row in metric_values) else []),
        ]
        point_encoding = {
            "x": x_encoding,
            "y": y_encoding,
            "color": color_encoding,
            "order": {"field": "series_order", "type": "ordinal"},
            "tooltip": tooltip,
        }
        metric_specs.append(
            {
                "title": {"text": metric, "anchor": "start", "fontSize": 13, "offset": 14},
                "data": {"values": metric_values},
                "width": "container",
                "height": 120,
                "layer": [
                    *([{
                        "mark": {"type": "line", "strokeWidth": 1.5, "color": "#52697A", "opacity": 0.8},
                        "encoding": {
                            "x": x_encoding,
                            "y": y_encoding,
                            "order": {"field": "series_order", "type": "ordinal"},
                        },
                    }] if comparison_kind not in {"grouped-observations", "monthly-trend"} and len(metric_values) > 1 else []),
                    {
                        "mark": {"type": "point", "filled": True, "size": 92, "strokeWidth": 1, "opacity": 1},
                        "encoding": point_encoding,
                    },
                    {
                        "mark": {"type": "point", "filled": True, "size": 750, "opacity": 0.001},
                        "encoding": point_encoding,
                    },
                    {
                        "mark": {"type": "text", "align": "center", "dy": -10, "fontSize": 11, "fontWeight": 600},
                        "encoding": {**point_encoding, "color": {"value": "#edf5fa"},
                                     "text": {"field": "display_value", "type": "nominal"}},
                    },
                ],
            }
        )

    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "usermeta": {
            "chartKind": "metric-rows",
            "presentationVersion": 2,
            "comparisonKind": comparison_kind,
            "metricRowCount": len(metric_order),
            "seriesCount": len({row[series_field] for row in values}),
            "seriesField": series_field,
            "seriesLabels": order,
            **({"colorField": color_field, "colorLabels": color_order} if color_field else {}),
        },
        "data": {"values": values},
        "vconcat": metric_specs,
        "resolve": {"scale": {"x": "independent", "y": "independent"}},
        "spacing": 14,
        "bounds": "full",
        "autosize": {"type": "pad", "contains": "padding", "resize": True},
    }
