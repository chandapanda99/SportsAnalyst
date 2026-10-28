"""Opt-in source-only soccer probes; retain raw captures without calling a model."""
from __future__ import annotations

import argparse
import importlib.metadata
import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sports_analyst.datasets.optional import load_optional_module
from sports_analyst.datasets.soccer.enrichment import FOTMOB_LEAGUES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live-sources", action="store_true")
    parser.add_argument("--include-open-events", action="store_true", help="Also verify a covered 2015/16 EPL event sample and xT")
    parser.add_argument("--output", type=Path, default=Path("build/soccer-source-audit"))
    args = parser.parse_args()
    if not args.run_live_sources:
        parser.error("Source downloads require --run-live-sources")
    args.output.mkdir(parents=True, exist_ok=True)
    soccer = load_optional_module("sportsdataverse.soccer", "Soccer source audit")
    families = ("espn_", "asa_", "fotmob_", "uefa_", "fifa_", "football_data_", "openliga", "soccer_")
    catalog = [{"function": name, "signature": str(inspect.signature(function)),
                "description": (inspect.getdoc(function) or "").split("\n", 1)[0],
                "verification": "declared function; not proof of usable source coverage"}
               for name, function in inspect.getmembers(soccer, inspect.isfunction) if name.startswith(families)]
    probes = [(f"asa-{league}-{year}", "asa_games_xgoals", {"league_slug": league, "season_name": str(year)})
              for league in ("mls", "nwsl") for year in (2024, 2025)]
    probes += [("asa-mls-teams", "asa_teams", {"league_slug": "mls"}),
               ("asa-mls-goalkeeping", "asa_goalkeepers_xgoals",
                {"league_slug": "mls", "season_name": "2025", "split_by_games": "true"}),
               ("fotmob-historical", "fotmob_matches", {"date": "20241020", "timezone": "UTC"}),
               ("fotmob-recent", "fotmob_matches", {"date": "20261020", "timezone": "UTC"}),
               ("fotmob-detail", "fotmob_match_details", {"match_id": "4813647"})]

    def probe(item):
        name, function, parameters = item
        path = args.output / f"{name}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else getattr(soccer, function)(
                **parameters, return_parsed=False, timeout=20, num_retries=0)
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            return {"probe": name, "function": function, "parameters": parameters, "status": "fetched",
                    "top_keys": list(raw)[:30] if isinstance(raw, dict) else [],
                    "rows": len(raw) if isinstance(raw, list) else None, "capture": str(path)}
        except Exception as error:
            return {"probe": name, "function": function, "parameters": parameters,
                    "status": "failed", "error_type": type(error).__name__,
                    "http_status": next((code for code in (400, 401, 403, 404, 410, 429, 500, 502, 503, 504)
                                         if f"HTTP {code}" in str(error)), None)}

    with ThreadPoolExecutor(max_workers=4) as pool:
        result = {"package_version": importlib.metadata.version("sportsdataverse"),
                  "declared_capabilities": catalog, "probes": list(pool.map(probe, probes))}
        details = []
        for period in ("historical", "recent"):
            path = args.output / f"fotmob-{period}.json"
            if not path.exists():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            for league in raw.get("leagues", []):
                if league.get("id") not in FOTMOB_LEAGUES.values():
                    continue
                games = [game for game in league.get("matches", []) if game.get("status", {}).get("finished") is True]
                if games:
                    details.append((f"fotmob-{period}-{league['id']}", "fotmob_match_details", {"match_id": str(games[0]["id"])}))
        result["probes"].extend(pool.map(probe, details))
    for receipt in result["probes"]:
        if receipt.get("status") != "fetched" or receipt.get("function") != "fotmob_match_details":
            continue
        raw = json.loads(Path(receipt["capture"]).read_text(encoding="utf-8"))
        content = raw.get("content") or {}
        shots = (content.get("shotmap") or {}).get("shots") or []
        receipt["coverage"] = {"shots": len(shots), "shot_xg": sum(s.get("expectedGoals") is not None for s in shots),
            "shot_xgot": sum(s.get("expectedGoalsOnTarget") is not None for s in shots),
            "players": len(content.get("playerStats") or {}), "sections": list(content),
            "match_date": (raw.get("general") or {}).get("matchTimeUTCDate")}
    if args.include_open_events:
        from sports_analyst.config import Settings
        from sports_analyst.datasets.soccer.connector import SportsDataverseSoccerConnector
        from sports_analyst.datasets.soccer.enrichment import SoccerEnrichment
        from sports_analyst.datasets.soccer.open_events import OpenEvents

        connector = SportsDataverseSoccerConnector(Settings(_env_file=None, data_dir=args.output / "runtime"))
        source = SoccerEnrichment(connector)
        games = source.fetch("eng.1", 2016, "statsbomb_open", {"resource": "matches/2/27.json"})
        date = games[0]["match_date"].replace("-", "")
        fixtures = connector._parse_scoreboard(connector._request("eng.1", "scoreboard", {"dates": date, "limit": 100}))
        events, counts = OpenEvents(connector).prepare("eng.1", 2016, fixtures)
        events.write_parquet(args.output / "open-events.parquet")
        result["open_events"] = {"coverage": counts, "rows": events.height,
            "xt_values": events["xt"].is_not_null().sum() if "xt" in events.columns else 0,
            "xt_model_hashes": events["xt_model_sha256"].unique().to_list() if "xt_model_sha256" in events.columns else []}
    (args.output / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "declared_capabilities"}, indent=2))


if __name__ == "__main__":
    main()
