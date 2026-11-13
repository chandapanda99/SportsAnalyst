"""Isolated computation tier for calculations the host's typed operations cannot express.

Model-written JavaScript runs in a fresh QuickJS runtime with no host functions, network,
files or clock. Its only input is a host-built, subject-scoped, column-projected extract.
The host runs the code twice in separate runtimes and registers outputs only when both runs
agree. Results are labelled sandbox-computed: reproducible, but the method is not verified.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

MAX_CODE_CHARS = 4000
MAX_OUTPUTS = 12
MAX_INPUT_BYTES = 6 * 1024 * 1024
NAME = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

PRELUDE = """
const rows = JSON.parse(__ROWS__);
const sum = (xs) => xs.reduce((a, b) => a + b, 0);
const mean = (xs) => xs.length ? sum(xs) / xs.length : null;
const quantile = (xs, q) => { if (!xs.length) return null; const s = [...xs].sort((a, b) => a - b);
  const p = (s.length - 1) * q, lo = Math.floor(p), hi = Math.ceil(p); return s[lo] + (s[hi] - s[lo]) * (p - lo); };
const median = (xs) => quantile(xs, 0.5);
const std = (xs) => { if (xs.length < 2) return null; const m = mean(xs);
  return Math.sqrt(sum(xs.map((x) => (x - m) ** 2)) / (xs.length - 1)); };
const values = (field) => rows.map((r) => r[field]).filter((v) => typeof v === "number" && Number.isFinite(v));
const groupBy = (field) => rows.reduce((g, r) => { const k = String(r[field]); (g[k] = g[k] || []).push(r); return g; }, {});
"""


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _validate(code: str, outputs: list[dict]) -> None:
    if not code.strip() or len(code) > MAX_CODE_CHARS:
        raise ValueError(f"Provide a function body of at most {MAX_CODE_CHARS} characters that returns an object of numbers")
    if not 1 <= len(outputs) <= MAX_OUTPUTS:
        raise ValueError(f"Declare 1-{MAX_OUTPUTS} outputs as [{{name, label, unit}}]")
    names = [item.get("name", "") for item in outputs]
    if len(set(names)) != len(names) or not all(NAME.match(name) for name in names):
        raise ValueError("Output names must be unique snake_case identifiers")
    for item in outputs:
        if not str(item.get("label", "")).strip() or len(str(item["label"])) > 160 or len(str(item.get("unit", ""))) > 60:
            raise ValueError("Each output needs a label (<=160 chars) and a unit (<=60 chars)")


def _execute(code: str, rows_json: str, timeout: float, memory_limit: int) -> dict:
    from quickjs_rs import Context, Runtime

    script = PRELUDE + "\nconst __result = (() => {\n" + code + "\n})();\nJSON.stringify(__result);"
    with Runtime(memory_limit=memory_limit) as runtime, Context(runtime, timeout=timeout) as context:
        context.globals["__ROWS__"] = rows_json
        try:
            raw = context.eval(script)
        except Exception as error:  # Guest errors, timeouts and memory limits are all model-correctable refusals.
            raise ValueError(f"Sandbox code failed: {type(error).__name__}: {str(error)[:400]}") from None
    if not isinstance(raw, str):
        raise ValueError("Code must return a plain object of named numbers")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("Code must return a JSON-serialisable object") from None


def run(code: str, outputs: list[dict], extract: dict, *, timeout: float = 2.0, memory_limit: int = 64 * 1024 * 1024) -> dict:
    """Execute twice in fresh runtimes; return checked outputs and the hashes that identify the computation."""
    _validate(code, outputs)
    rows_json = json.dumps(extract["rows"], default=str)
    if len(rows_json) > MAX_INPUT_BYTES:
        raise ValueError("Extract is too large for the sandbox; select fewer fields or add filters")
    first = _execute(code, rows_json, timeout, memory_limit)
    second = _execute(code, rows_json, timeout, memory_limit)
    if first != second:
        raise ValueError("Sandbox result was not reproducible across two runs; remove randomness or time dependence")
    if not isinstance(first, dict):
        raise ValueError("Code must return a plain object of named numbers")
    expected = [item["name"] for item in outputs]
    if sorted(first) != sorted(expected):
        raise ValueError(f"Returned keys {sorted(first)} must match declared outputs {sorted(expected)}")
    for name, value in first.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e15:
            raise ValueError(f"Output {name!r} must be a finite number")
    return {"values": first, "code_sha256": digest(code), "input_sha256": digest(rows_json), "rows": len(extract["rows"])}
