"""Summarise how the calculation planner spent its calls across saved investigations.

Run with ``python scripts/audit_planner_runs.py [investigations_dir] [--json]``. It reads saved
bundles only; nothing is re-executed. Tool calls made from interpreter code
(``tools.someTool(...)``) are counted as well as direct tool calls.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

DISCOVERY = {"inspect_calculation_inputs", "inspect_scoped_datasets", "inspect_dataset_schema", "discover_relationships",
             "inspect_dataset_profile", "search_fields", "inspect_field_values", "inspect_sport_analyses"}
COMPUTATION = {"aggregate_scoped_data", "execute_joined_aggregate", "register_arithmetic", "run_sport_analysis",
               "compute_on_extract"}
CALL = re.compile(r"tools\.(\w+)\s*\(")
ERROR = re.compile(r'error\\*"\s*:\s*\\*"([A-Za-z][^"\\]{0,200})')


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def text(content) -> str:
    return content if isinstance(content, str) else json.dumps(content, default=str)


def planner_runs(root: Path):
    for path in sorted(root.glob("*/bundle.json")):
        bundle = json.loads(path.read_text(encoding="utf-8"))
        run = bundle["run"]
        for execution in bundle.get("executions", []):
            if execution["tool"] not in {"complete_calculations", "complete_calculations_failed"}:
                continue
            yield run, execution


def summarise(root: Path) -> dict:
    calls, errors = collections.Counter(), collections.Counter()
    runs, unresolved = [], []
    for run, execution in planner_runs(root):
        parameters = execution["parameters"]
        sequence, model_calls = [], 0
        for message in parameters.get("messages", []):
            if message.get("type") == "ai":
                model_calls += 1
                for call in message.get("tool_calls", []):
                    inner = CALL.findall(json.dumps(call.get("args", {}))) if call["name"] == "eval" else []
                    sequence.extend(snake(name) for name in inner) if inner else sequence.append(call["name"])
            elif message.get("type") == "tool":
                errors.update(ERROR.findall(text(message.get("content"))))
        for item in parameters.get("tool_audit", []):
            sequence.append(item["tool"])
            errors.update(ERROR.findall(text(item.get("result"))))
        calls.update(sequence)
        plan = parameters.get("plan") or {}
        review = parameters.get("question_review") or parameters.get("review") or {}
        objectives = plan.get("objectives") or []
        for key, reason in (review.get("unresolved") or {}).items():
            index = int(key) if str(key).isdigit() else -1
            unresolved.append({"sport": run["sport"], "objective": objectives[index] if 0 <= index < len(objectives) else key,
                               "reason": reason})
        turns = parameters.get("planning_turns") or []
        runs.append({"investigation_id": run["investigation_id"], "sport": run["sport"],
                     "follow_up": bool(run.get("parent_investigation_id")), "failed": execution["tool"].endswith("_failed"),
                     "model_calls": model_calls, "tool_calls": len(sequence),
                     "discovery_calls": sum(name in DISCOVERY for name in sequence),
                     "computation_calls": sum(name in COMPUTATION for name in sequence),
                     "hit_call_limit": any(turn.get("stop_reason") == "model_call_limit" for turn in turns),
                     "objectives": len(objectives), "unresolved": len(review.get("unresolved") or {})})
    total = sum(calls.values()) or 1
    return {"runs": len(runs), "failed_runs": sum(r["failed"] for r in runs),
            "runs_without_new_computation": sum(not r["computation_calls"] for r in runs),
            "call_limit_hits": sum(r["hit_call_limit"] for r in runs),
            "discovery_share": round(sum(calls[n] for n in DISCOVERY) / total, 3),
            "computation_share": round(sum(calls[n] for n in COMPUTATION) / total, 3),
            "calls": calls.most_common(), "errors": errors.most_common(25),
            "unresolved_objectives": unresolved, "per_run": runs}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", help="Investigations directory (defaults to the configured data directory)")
    parser.add_argument("--json", action="store_true", help="Print the full summary as JSON")
    args = parser.parse_args()
    if args.root:
        root = Path(args.root)
    else:
        from sports_analyst.config import Settings

        root = Settings().investigations_dir
    summary = summarise(root)
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
        return
    print(f"Planner runs: {summary['runs']} (failed {summary['failed_runs']}, call-limit hits {summary['call_limit_hits']})")
    print(f"Runs that computed nothing new: {summary['runs_without_new_computation']}")
    print(f"Discovery share of tool calls: {summary['discovery_share']:.0%}; computation share: {summary['computation_share']:.0%}")
    print("\nTool calls:")
    for name, count in summary["calls"]:
        print(f"  {count:4}  {name}")
    print("\nMost common refusals:")
    for message, count in summary["errors"]:
        print(f"  {count:4}  {message[:120]}")
    print("\nUnresolved objectives:")
    for item in summary["unresolved_objectives"]:
        print(f"  [{item['sport']}] {item['objective'][:100]}\n         {item['reason'][:160]}")


if __name__ == "__main__":
    main()
