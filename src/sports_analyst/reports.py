from __future__ import annotations

import html
import json
from copy import deepcopy

from sports_analyst.models import InvestigationBundle
from sports_analyst.team_palettes import rgb_csv, team_report_palette


def _window_label(season: int, weeks: tuple[int, int]) -> str:
    return f"{season} W{weeks[0]}–{weeks[1]}"


def _scope_label(scope) -> str:
    if scope.comparison_design == "full_seasons":
        return f"Full seasons {scope.baseline.season}–{scope.comparison.season} (inclusive)"
    baseline = _window_label(scope.baseline.season, scope.baseline.weeks)
    comparison = _window_label(scope.comparison.season, scope.comparison.weeks)
    return f"{baseline} → {comparison}"


def render_markdown(bundle: InvestigationBundle) -> str:
    scope = bundle.run.scope
    lines = [
        f"# {scope.team} efficiency investigation",
        "",
        bundle.summary,
        "",
        f"**Question:** {bundle.run.question}  ",
        f"**Scope:** {_scope_label(scope)} ({scope.season_type})  ",
        f"**Investigation:** `{bundle.run.investigation_id}`",
        "",
        "## Findings",
        "",
    ]
    for claim in bundle.claims:
        citations = ", ".join(f"`{identifier}`" for identifier in claim.evidence_ids)
        lines.append(f"- **{claim.claim_type.value.title()} · {claim.confidence}:** {claim.statement} [{citations}]")
    lines.extend(["", "## Metrics", "", "| Metric | Baseline | Comparison | Change | N |", "|---|---:|---:|---:|---:|"])
    for item in bundle.aggregate_evidence:
        if item.baseline_value is not None and item.comparison_value is not None:
            lines.append(f"| {item.label} | {item.baseline_value:.4f} | {item.comparison_value:.4f} | {item.value} | {item.sample_size} |")
    seasonal = [item for item in bundle.aggregate_evidence if item.metric.startswith("seasonal_")]
    if seasonal:
        lines.extend(["", "## Season-by-season measurements", "", "| Season / metric | Value | N |", "|---|---:|---:|"])
        lines.extend(f"| {item.label} | {item.value} | {item.sample_size} |" for item in seasonal)
    lines.extend(["", "## Representative plays", ""])
    for play in bundle.play_evidence:
        lines.append(f"- `{play.game_id}/{play.play_id}` — EPA {play.epa}: {play.description} (`{play.evidence_id}`)")
    lines.extend(["", "## Methodological caveats", ""])
    lines.extend(f"- {caveat}" for caveat in bundle.methodological_caveats)
    lines.extend(["", "## Data provenance", ""])
    for manifest in bundle.dataset_manifests:
        lines.append(
            f"- {manifest.season} {manifest.dataset}: `{manifest.sha256}` — {manifest.attribution} "
            f"[{manifest.license}]({manifest.source_url})"
        )
    return "\n".join(lines) + "\n"


def _themed_chart_specification(specification: dict, team: str) -> dict:
    themed = deepcopy(specification)
    palette = team_report_palette(team)
    encoding = themed.get("encoding")
    if isinstance(encoding, dict) and isinstance(encoding.get("color"), dict):
        color = encoding["color"]
        scale = color.get("scale") if isinstance(color.get("scale"), dict) else {}
        color["scale"] = {**scale, "range": [palette.display_primary, palette.display_secondary]}

    config = themed.get("config") if isinstance(themed.get("config"), dict) else {}
    themed["background"] = "transparent"
    themed["config"] = {
        **config,
        "view": {"stroke": None},
        "axis": {
            "labelColor": "#AFC0D3",
            "titleColor": "#E7EDF6",
            "domainColor": "#3B5068",
            "gridColor": "#2C4057",
            "gridOpacity": 0.55,
            "tickColor": "#3B5068",
        },
        "legend": {"labelColor": "#C7D3E0", "titleColor": "#E7EDF6"},
    }
    return themed


def _chart_svg(specification: dict, team: str) -> str:
    themed = _themed_chart_specification(specification, team)
    try:
        import vl_convert as vlc

        return vlc.vegalite_to_svg(themed)
    except Exception:
        return f"<pre>{html.escape(json.dumps(themed, indent=2))}</pre>"


def render_html(bundle: InvestigationBundle) -> str:
    scope = bundle.run.scope
    palette = team_report_palette(scope.team)
    comparison_label = _scope_label(scope)
    claims = "".join(
        f'<article class="claim"><span>{html.escape(claim.claim_type.value)} · {claim.confidence}</span>'
        f"<p>{html.escape(claim.statement)}</p><code>{html.escape(', '.join(claim.evidence_ids))}</code></article>"
        for claim in bundle.claims
    )
    charts = "".join(
        f'<section class="chart"><h2>{html.escape(chart.title)}</h2>{_chart_svg(chart.specification, scope.team)}</section>'
        for chart in bundle.charts
    )
    plays = "".join(
        f"<tr><td>{html.escape(play.game_id)}</td><td>{play.play_id}</td><td>{play.epa}</td><td>{html.escape(play.description)}</td></tr>"
        for play in bundle.play_evidence
    )
    caveats = "".join(f"<li>{html.escape(item)}</li>" for item in bundle.methodological_caveats)
    attribution = " ".join(html.escape(item.attribution) for item in bundle.dataset_manifests)
    styles = f"""
:root{{--team-primary:{palette.primary};--team-secondary:{palette.secondary};--team-accent:{palette.display_primary};
--team-accent-alt:{palette.display_secondary};--team-primary-rgb:{rgb_csv(palette.primary)};--team-secondary-rgb:{rgb_csv(palette.secondary)};
color-scheme:dark}}
*{{box-sizing:border-box}}
body{{font:16px/1.6 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;max-width:1120px;margin:auto;padding:40px;
background:radial-gradient(circle at 100% 0,rgba(var(--team-primary-rgb),.18),transparent 34rem),#09111d;color:#e7edf6}}
header{{position:relative;border:1px solid #2b3d52;border-top:6px solid var(--team-accent);border-radius:16px;padding:30px;
background:linear-gradient(135deg,rgba(var(--team-primary-rgb),.14),rgba(var(--team-secondary-rgb),.05) 58%,#101d2c)}}
header:after{{content:"";position:absolute;right:28px;top:28px;width:72px;height:8px;border-radius:999px;
background:linear-gradient(90deg,var(--team-primary) 0 50%,var(--team-secondary) 50%)}}
h1{{max-width:850px;font-size:42px;line-height:1.12;margin:.25em 0 .35em}} h2{{margin:34px 0 12px;color:#f4f7fb}}
.eyebrow,.claim>span{{color:var(--team-accent-alt);text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:700}}
.claim,section{{background:#111e2d;border:1px solid #2b3d52;border-radius:14px;padding:20px;margin:14px 0}}
.claim{{border-left:4px solid var(--team-accent)}} .claim p{{font-size:17px;margin:.55rem 0}}
.chart{{overflow:hidden;border-top:3px solid var(--team-accent)}}
code{{color:var(--team-accent-alt);font-size:11px}}
table{{width:100%;border:1px solid #2b3d52;border-collapse:separate;border-spacing:0;border-radius:12px;overflow:hidden}}
thead{{background:rgba(var(--team-primary-rgb),.22)}} td,th{{padding:12px;border-bottom:1px solid #2b3d52;text-align:left}}
th{{color:var(--team-accent-alt)}} tbody tr:last-child td{{border-bottom:0}}
svg{{display:block;max-width:100%;height:auto;margin-inline:auto}}
footer{{margin-top:36px;padding-top:18px;border-top:2px solid var(--team-accent);color:#9aabba;font-size:13px}}
@media(max-width:700px){{body{{padding:18px}}header{{padding:22px}}header:after{{display:none}}h1{{font-size:32px}}}}
@media print{{*{{print-color-adjust:exact;-webkit-print-color-adjust:exact}}body{{max-width:none;padding:0}}}}
"""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(scope.team)} efficiency investigation</title><style>{styles}</style></head><body>
<header><div class="eyebrow">Open Sports Analyst · Evidence-bound report</div>
<h1>{html.escape(scope.team)} passing efficiency</h1><p>{html.escape(bundle.summary)}</p>
<small>{comparison_label} · {html.escape(bundle.run.investigation_id)}</small></header>
<main><h2>Findings</h2>{claims}{charts}<h2>Representative plays</h2><table><thead>
<tr><th>Game</th><th>Play</th><th>EPA</th><th>Description</th></tr></thead><tbody>{plays}</tbody></table>
<h2>Methodological caveats</h2><ul>{caveats}</ul></main>
<footer><p>{attribution}</p></footer></body></html>"""
