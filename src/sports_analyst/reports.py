from __future__ import annotations

import html
import json

from sports_analyst.models import InvestigationBundle


def _window_label(season: int, weeks: tuple[int, int]) -> str:
    return f"{season} W{weeks[0]}–{weeks[1]}"


def render_markdown(bundle: InvestigationBundle) -> str:
    scope = bundle.run.scope
    lines = [
        f"# {scope.team} efficiency investigation",
        "",
        bundle.summary,
        "",
        f"**Question:** {bundle.run.question}  ",
        f"**Comparison:** {_window_label(scope.baseline.season, scope.baseline.weeks)} → "
        f"{_window_label(scope.comparison.season, scope.comparison.weeks)} ({scope.season_type})  ",
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


def _chart_svg(specification: dict) -> str:
    try:
        import vl_convert as vlc

        return vlc.vegalite_to_svg(specification)
    except Exception:
        return f"<pre>{html.escape(json.dumps(specification, indent=2))}</pre>"


def render_html(bundle: InvestigationBundle) -> str:
    scope = bundle.run.scope
    comparison_label = (
        f"{_window_label(scope.baseline.season, scope.baseline.weeks)} → {_window_label(scope.comparison.season, scope.comparison.weeks)}"
    )
    claims = "".join(
        f'<article class="claim"><span>{html.escape(claim.claim_type.value)} · {claim.confidence}</span>'
        f"<p>{html.escape(claim.statement)}</p><code>{html.escape(', '.join(claim.evidence_ids))}</code></article>"
        for claim in bundle.claims
    )
    charts = "".join(f"<section><h2>{html.escape(chart.title)}</h2>{_chart_svg(chart.specification)}</section>" for chart in bundle.charts)
    plays = "".join(
        f"<tr><td>{html.escape(play.game_id)}</td><td>{play.play_id}</td><td>{play.epa}</td><td>{html.escape(play.description)}</td></tr>"
        for play in bundle.play_evidence
    )
    caveats = "".join(f"<li>{html.escape(item)}</li>" for item in bundle.methodological_caveats)
    attribution = " ".join(html.escape(item.attribution) for item in bundle.dataset_manifests)
    styles = """
:root{color-scheme:dark}
body{font:16px system-ui;max-width:1120px;margin:auto;padding:40px;background:#09111d;color:#e7edf6}
header{border-bottom:1px solid #24364d;padding-bottom:28px}
h1{font-size:42px;margin:.2em 0} h2{margin-top:36px}
.eyebrow,span{color:#78dcca;text-transform:uppercase;letter-spacing:.12em;font-size:12px}
.claim,section{background:#111e2d;border:1px solid #24364d;border-radius:14px;padding:20px;margin:14px 0}
code{color:#86a9ce;font-size:11px} table{width:100%;border-collapse:collapse}
td,th{padding:10px;border-bottom:1px solid #24364d;text-align:left} svg{max-width:100%;height:auto}
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
