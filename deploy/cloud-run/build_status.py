"""Summarize a Cloud Build resource for the deployment progress watcher."""

from __future__ import annotations

import json
import sys


TERMINAL_STEP_STATUSES = {"SUCCESS", "FAILURE", "INTERNAL_ERROR", "TIMEOUT", "CANCELLED", "EXPIRED"}


def main() -> None:
    build = json.load(sys.stdin)
    build_status = str(build.get("status") or "STATUS_UNKNOWN")
    steps = build.get("steps") or []

    active = next((step for step in steps if step.get("status") == "WORKING"), None)
    if active is None and build_status not in TERMINAL_STEP_STATUSES:
        active = next(
            (step for step in steps if step.get("status") not in TERMINAL_STEP_STATUSES),
            None,
        )

    stage = str((active or {}).get("id") or "finalizing")
    print(f"{build_status}\t{stage}")


if __name__ == "__main__":
    main()
