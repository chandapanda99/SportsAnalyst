"""Shared Vega-Lite specifications for comparison charts."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any


def _display_value(value: float, unit: str | None) -> str:
    normalized_unit = (unit or "").casefold()
    if normalized_unit in {"percentage", "rate"} and abs(value) <= 1:
        return f"{value * 100:.1f}%"
    if normalized_unit in {"attempts", "completions", "count", "interceptions", "sacks", "touchdowns", "yards"}:
        return f"{value:,.0f}"
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:,.1f}"
    return f"{value:+.3f}" if value != 0 else "0.000"


def _axis_format(values: Sequence[float], unit: str | None) -> str:
    normalized_unit = (unit or "").casefold()
    largest = max((abs(value) for value in values), default=0)
    if normalized_unit in {"percentage", "rate"} and largest <= 1:
        return ".0%"
    if normalized_unit in {
        "attempts",
        "completions",
        "count",
        "interceptions",
        "sacks",
        "touchdowns",
        "yards",
    } or largest >= 100:
        return ",.0f"
    if largest >= 1:
        return ".1f"
    return ".2f"


def metric_row_comparison_spec(rows: Iterable[dict[str, Any]], *, series_field: str, series_order: Sequence[str]) -> dict[str, Any]:
    """Render unlike metrics as independently scaled, easy-to-target comparison rows."""
    values: list[dict[str, Any]] = []
    metric_order: list[str] = []
    for row in rows:
        value = row.get("value")
        if value is None:
            continue
        metric = str(row["metric"])
        series = str(row[series_field])
        if metric not in metric_order:
            metric_order.append(metric)
        values.append(
            {
                **row,
                "value": float(value),
                "display_value": row.get("display_value") or _display_value(float(value), row.get("unit")),
                "series_order": series_order.index(series) if series in series_order else len(series_order),
            }
        )

    metric_specs = []
    for metric in metric_order:
        metric_values = [row for row in values if row["metric"] == metric]
        numeric_values = [float(row["value"]) for row in metric_values]
        unit = str(metric_values[0].get("unit") or "") if metric_values else ""
        y_encoding = {
            "field": "value",
            "type": "quantitative",
            "scale": {"zero": False, "nice": True},
            "axis": {
                "title": None,
                "tickCount": 4,
                "format": _axis_format(numeric_values, unit),
                "grid": True,
            },
        }
        x_encoding = {
            "field": series_field,
            "type": "ordinal",
            "sort": list(series_order),
            "axis": {"title": None, "ticks": False, "domain": False, "grid": False, "labelLimit": 125},
        }
        color_encoding = {
            "field": series_field,
            "type": "nominal",
            "sort": list(series_order),
            "legend": None,
        }
        tooltip = [
            {"field": "metric", "type": "nominal", "title": "Metric"},
            {"field": series_field, "type": "nominal", "title": "Window"},
            {"field": "display_value", "type": "nominal", "title": "Value"},
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
                "title": {"text": metric, "anchor": "start", "fontSize": 12, "offset": 6},
                "data": {"values": metric_values},
                "width": "container",
                "height": 130,
                "layer": [
                    {
                        "mark": {"type": "line", "strokeWidth": 1.5, "color": "#52697A", "opacity": 0.8},
                        "encoding": {
                            "x": x_encoding,
                            "y": y_encoding,
                            "order": {"field": "series_order", "type": "ordinal"},
                        },
                    },
                    {
                        "mark": {"type": "point", "filled": True, "size": 92, "strokeWidth": 1},
                        "encoding": point_encoding,
                    },
                    {
                        "mark": {"type": "point", "filled": True, "size": 750, "opacity": 0.001},
                        "encoding": point_encoding,
                    },
                    {
                        "mark": {"type": "text", "align": "center", "dy": -10, "fontSize": 11, "fontWeight": 600},
                        "encoding": {**point_encoding, "text": {"field": "display_value", "type": "nominal"}},
                    },
                ],
            }
        )

    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "usermeta": {
            "chartKind": "metric-rows",
            "metricRowCount": len(metric_order),
            "seriesCount": len({row[series_field] for row in values}),
            "seriesField": series_field,
        },
        "data": {"values": values},
        "vconcat": metric_specs,
        "resolve": {"scale": {"x": "independent", "y": "independent"}},
        "spacing": 32,
        "bounds": "full",
        "autosize": {"type": "pad", "contains": "padding", "resize": True},
    }
