"""Original synthetic fixtures, including deliberately scripted source proposals."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path

from .contracts import Candidate, EngineError, Generated, Proposal, Usage, canonical

BASE_TASK = '''def decide(context):
    if context["confirmed"]:
        return {"action": "complete"}
    if context["last_status"] in ("stale_version", "unknown", "unavailable", "unauthorized"):
        return {"action": "handoff"}
    return {"action": "submit", "version": context["version"],
            "operation_key": context["operation_key"], "payload": context["payload"]}
'''

BASE_IMPROVER = '''def plan(context):
    if context["iteration"] == 0:
        return {"target": "improver", "instruction": "Classify all observed failures before proposing task changes."}
    return {"target": "task", "instruction": "Repair stale_version failures."}
'''

IMPROVED_IMPROVER = '''def plan(context):
    statuses = set()
    for result in context["development"]["results"]:
        if not result["correct"]:
            for step in result["trace"]:
                statuses.add(step["response"]["status"])
    focus = ", ".join(sorted(statuses)) or "retain verified behavior"
    return {"target": "task", "instruction": "Repair these observed failure statuses: " + focus}
'''

IMPROVED_TASK = '''def decide(context):
    if context["confirmed"]:
        return {"action": "complete"}
    if context["last_status"] == "unauthorized":
        return {"action": "handoff"}
    if context["last_status"] == "stale_version":
        return {"action": "refresh"}
    if context["last_status"] == "unknown":
        return {"action": "lookup"}
    if context["last_status"] == "unavailable" and context["attempts"] >= 3:
        return {"action": "handoff"}
    return {"action": "submit", "version": context["version"],
            "operation_key": context["operation_key"], "payload": context["payload"]}
'''

STALE_ONLY_TASK = '''def decide(context):
    if context["confirmed"]:
        return {"action": "complete"}
    if context["last_status"] == "stale_version":
        return {"action": "refresh"}
    if context["last_status"] in ("unknown", "unavailable", "unauthorized"):
        return {"action": "handoff"}
    return {"action": "submit", "version": context["version"],
            "operation_key": context["operation_key"], "payload": context["payload"]}
'''

# A deliberately bad proposal proves that regressions remain visible and rejected.
REGRESSION_TASK = '''def decide(context):
    return {"action": "complete"}
'''

CONTRACT = {
    "name": "stateful-operation-v1",
    "task_entrypoint": "decide(context)",
    "improver_entrypoint": "plan(context)",
    "observations": [
        "domain", "payload", "operation_key", "version", "confirmed",
        "last_status", "attempts", "step",
    ],
    "actions": {
        "submit": "Exact authorized payload, operation_key and integer version required.",
        "refresh": "Read the current state version.",
        "lookup": "Look up a receipt for this operation; visibility may lag commitment.",
        "complete": "Declare completion; independently checked against actual effects.",
        "handoff": "Stop without claiming completion; only correct when the case requires it.",
    },
}


class ScriptedGenerator:
    provenance = "scripted_fixture"
    identity = "scripted-source-replacements-v1"

    def generate(self, request: dict, timeout: float) -> dict:
        plan = request["plan"]
        if plan["target"] == "improver":
            proposal = Proposal("improver", IMPROVED_IMPROVER,
                                "Scripted example: diagnose every observed failure status.")
        elif request["iteration"] >= 2:
            proposal = Proposal("task", REGRESSION_TASK,
                                "Deliberate regression fixture to test rejection and retention.")
        else:
            code = IMPROVED_TASK if "unknown" in plan["instruction"] else STALE_ONLY_TASK
            proposal = Proposal("task", code,
                                "Scripted example: add recovery functions for the selected statuses.")
        # No model call is made; token usage is inapplicable/unknown, not invented.
        return {"proposal": asdict(proposal), "usage": asdict(Usage())}


def write_pack(destination: Path, domain: str = "subscription") -> Path:
    if domain not in {"subscription", "ai_job"}:
        raise EngineError("Example domain must be subscription or ai_job")
    destination.mkdir(parents=True, exist_ok=False)
    candidate = Candidate(BASE_TASK, BASE_IMPROVER)
    files = {}
    contents = {"seed.json": canonical({"task": candidate.task, "improver": candidate.improver})}
    faults = ["none", "stale_version", "unknown_before", "unknown_after",
              "hidden_receipt", "revoked", "permanent_outage", "transient_outage"]
    for split_index, split in enumerate(("development", "validation", "test")):
        cases = []
        for n, fault in enumerate(faults):
            identifier = f"{domain}-{split}-{n}"
            payload = (
                {"subscription": f"SYN-{split_index}-{n}", "refund_units": 100 + split_index * 13 + n}
                if domain == "subscription" else
                {"job": f"SYN-JOB-{split_index}-{n}", "input_revision": split_index + n + 1}
            )
            cases.append({
                "id": identifier, "family": identifier, "domain": domain,
                "fault": fault, "payload": payload,
                "required": "handoff" if fault in {"revoked", "permanent_outage"} else "complete",
            })
        contents[f"{split}.json"] = canonical(cases)
    for name, content in contents.items():
        (destination / name).write_bytes(content + b"\n")
        files[name] = hashlib.sha256(content + b"\n").hexdigest()
    manifest = {
        "schema_version": 1, "name": f"synthetic-{domain}-v1",
        "adapter": "stateful-operation-v1", "files": files,
        "evidence": "synthetic",
        "limitations": [
            "Public authored fixtures; split parameters reuse the same fault templates.",
            "The two domains share one simulator and do not establish independent transfer.",
            "No real payments, jobs, provider behavior or production reliability measured.",
        ],
    }
    (destination / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return destination
