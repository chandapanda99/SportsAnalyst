"""Publish validated measurements durably before handing them to the writer."""
from sports_analyst.application.preparation import coordinator
from sports_analyst.models import AggregateEvidence, ToolExecutionRecord


def publish(access, plan_id, evidence, execution):
    state = access.acquisition.state
    with coordinator(access.app).lease(f"research-measurements:{state.root.name}", seconds=60):
        saved = state.read("measurement_journal") or {"entries": {}}
        sequence = saved["entries"].get(execution.execution_id, {}).get("sequence", len(saved["entries"]))
        saved["entries"][execution.execution_id] = {
            "sequence": sequence,
            "plan_id": plan_id, "evidence": [e.model_dump(mode="json") for e in evidence],
            "execution": execution.model_dump(mode="json", exclude={"parameters"})}
        state.write("measurement_journal", saved)


def recover(access):
    state = access.acquisition.state
    saved = state.read("measurement_journal") or {"entries": {}}
    evidence, executions, invalidated = [], [], []
    for identifier, entry in sorted(saved["entries"].items(), key=lambda pair: pair[1].get("sequence", 0)):
        try:
            payload = state.read(identifier)
            if payload is None:
                raise ValueError("Measurement execution receipt is missing")
            access.executor.revalidate(payload)
            for key in payload["inputs"]:
                access.executor.scan(access.manifests[key], [])
            evidence.extend(AggregateEvidence.model_validate(row) for row in entry["evidence"])
            executions.append(ToolExecutionRecord.model_validate({**entry["execution"], "parameters": payload}))
        except (ValueError, KeyError, OSError) as error:
            invalidated.append({"execution_id": identifier, "status": "invalidated", "reason": str(error)[:500]})
    if invalidated:
        state.write("invalidated_measurements", invalidated)
    return evidence, executions, invalidated
