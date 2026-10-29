"""A new two-stage synthetic workflow; effect grading is a separate module."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import itertools
from pathlib import Path
import random
import time

from .contracts import BudgetExceeded, EngineError, canonical, digest, exact, text
from .grading import grade_effects
from .workload import Pack

FAULTS = ("clean", "stale_twice", "unavailable_twice", "unknown_before_twice",
          "unknown_after_visible", "unknown_after_hidden", "permanent_outage", "revoked")
STOPS = {"permanent_outage", "revoked"}

SEED_TASK = '''def decide(context):
    if context["stage"] == 2:
        return {"action": "complete"}
    if context["confirmed"]:
        return {"action": "next"}
    if context["last_status"] in ("stale_version", "unknown", "unavailable", "unauthorized"):
        return {"action": "handoff"}
    return {"action": "submit", "stage": context["stage"], "version": context["version"],
            "operation_key": context["operation_key"], "payload": context["payload"]}
'''

SEED_IMPROVER = '''def plan(context):
    failures = {}
    for result in context["development"]["results"]:
        if not result["correct"]:
            for event in result["trace"]:
                status = event["response"]["status"]
                failures[status] = failures.get(status, 0) + 1
    target = context["requested_target"]
    return {"target": target,
            "instruction": "Improve " + target + " code using these failure signals: " +
            repr(failures) + ". Preserve successful outcomes. Review history before repeating a failed approach."}
'''

CONTRACT = {
    "name": "composed-operation-v1",
    "description": "Execute two authorized stages in order, confirming each receipt before advancing.",
    "observations": {
        "stage": "0 or 1 for the current stage; 2 means both stages have confirmed receipts",
        "stage_name": "descriptive name; do not hardcode domain-specific names",
        "domain": "subscription or ai_job; the action contract is the same",
        "payload": "exact authorized payload for the current stage",
        "operation_key": "stable idempotency key for the current stage",
        "version": "last observed state version; refresh updates it",
        "confirmed": "a receipt for the current stage has been observed",
        "last_status": "response to the last action",
        "attempts": "number of submit attempts in the current stage",
        "step": "total actions executed in this case",
    },
    "actions": {
        "submit": "Exactly action, stage, version, operation_key and payload.",
        "refresh": "Exactly action. Refresh the current version.",
        "lookup": "Exactly action. Look up this stage's receipt; absence does not prove no effect.",
        "next": "Exactly action. Advance only after confirmed receipt. Stage-local counters reset.",
        "complete": "Exactly action. Valid only at stage 2 with both authorized effects.",
        "handoff": "Exactly action. Correct only for a permanent outage or withdrawn authority, with committed prefix preserved.",
    },
    "recovery_contract": [
        "Transient injected failures of one kind recover after at most two failed submit attempts.",
        "A successful write can return unknown and its receipt can remain hidden from lookup.",
        "An exact authorized retry with the same operation key returns the existing receipt without another effect.",
        "Stale version requires refresh before retry; repeated conflicts can occur.",
        "Revoked authority is permanent for the remainder of a case.",
        "Each case has a 24-action ceiling.",
    ],
}


def validate_case(case):
    exact(case, {"id", "family", "domain", "stages", "reference"}, "composed case")
    if case["domain"] not in {"subscription", "ai_job"}:
        raise EngineError("Invalid composed domain")
    if not isinstance(case["stages"], list) or len(case["stages"]) != 2:
        raise EngineError("Composed case needs two stages")
    for stage in case["stages"]:
        exact(stage, {"name", "fault", "payload"}, "stage")
        text(stage["name"], "stage name", 100)
        if not isinstance(stage["fault"], str) or stage["fault"] not in FAULTS:
            raise EngineError("Invalid stage fault")
        if not isinstance(stage["payload"], dict) or len(canonical(stage["payload"])) > 2000:
            raise EngineError("Invalid stage payload")
    reference = exact(case["reference"], {"terminal", "effects"}, "reference")
    if reference["terminal"] not in {"complete", "handoff"} or not isinstance(reference["effects"], list):
        raise EngineError("Invalid reference")
    stop = next((i for i, s in enumerate(case["stages"]) if s["fault"] in STOPS), 2)
    expected = [{"stage": i, "payload": case["stages"][i]["payload"]} for i in range(stop)]
    if reference != {"terminal": "complete" if stop == 2 else "handoff", "effects": expected}:
        raise EngineError("Reference contradicts the authored case")


def open_pack(path):
    return Pack(path, adapter="composed-operation-v1", case_validator=validate_case)


def write_pack(destination: Path):
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    # Unreachable second-stage variations after a permanent first-stage stop
    # are canonicalized, rather than inflating the family count.
    families = sorted({(a, "clean" if a in STOPS else b) for a, b in itertools.product(FAULTS, repeat=2)})
    random.Random(20261029).shuffle(families)
    groups = {"development": families[:12], "validation": families[12:22], "test": families[22:]}
    contents = {"seed.json": canonical({"task": SEED_TASK, "improver": SEED_IMPROVER}) + b"\n"}
    for split, subset in groups.items():
        cases = []
        for pair in subset:
            family = digest({"faults": pair})
            for variant in range(2 if split == "test" else 1):
                domain = "ai_job" if variant else "subscription"
                names = ["record_refund", "set_access"] if domain == "subscription" else ["submit_job", "publish_result"]
                stages = [
                    {"name": names[i], "fault": fault,
                     "payload": {"resource": "SYN-" + family[:10], "revision": variant + i + 1,
                                 "operation": names[i], "units": 17 + variant * 19 + i}}
                    for i, fault in enumerate(pair)
                ]
                stop = next((i for i, fault in enumerate(pair) if fault in STOPS), 2)
                cases.append({
                    "id": f"composed-{family[:16]}-{variant}", "family": family,
                    "domain": domain, "stages": stages,
                    "reference": {
                        "terminal": "complete" if stop == 2 else "handoff",
                        "effects": [{"stage": i, "payload": stages[i]["payload"]} for i in range(stop)],
                    },
                })
        contents[split + ".json"] = canonical(cases) + b"\n"
    hashes = {}
    for name, raw in contents.items():
        (destination / name).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    manifest = {
        "schema_version": 1, "name": "composed-workflow-pilot-v1", "adapter": "composed-operation-v1",
        "files": hashes, "evidence": "synthetic",
        "limitations": [
            "Fresh authored compositions with development, validation and test grouped by full fault composition.",
            "50 families; development 12 cases, validation 10 cases, test 56 cases from 28 families.",
            "One author and simulator; separately implemented grader is not independent external authorship.",
            "Test parameter/domain variants share families; no production reliability or independent transfer claim.",
        ],
    }
    (destination / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return destination


class WorkflowState:
    def __init__(self, case):
        self.case = case
        self.stage = 0
        self.version = [1, 1]
        self.known_version = [1, 1]
        self.attempts = [0, 0]
        self.confirmed = [False, False]
        self.effects = []
        self.trace = []
        self.terminal = None
        self.last_status = "ready"
        self.blocked = 0

    def key(self, stage):
        return digest({"case": self.case["id"], "stage": stage})

    def observation(self):
        i = min(self.stage, 1)
        stage = self.case["stages"][i]
        return {"stage": self.stage, "stage_name": stage["name"], "domain": self.case["domain"],
                "payload": deepcopy(stage["payload"]), "operation_key": self.key(i),
                "version": self.known_version[i], "attempts": self.attempts[i],
                "confirmed": self.confirmed[i], "last_status": self.last_status, "step": len(self.trace)}

    def apply(self, action):
        response = {"status": "invalid_action"}
        if isinstance(action, dict):
            name = action.get("action")
            if isinstance(name, str) and name in {"complete", "handoff"} and set(action) == {"action"}:
                self.terminal = name
                response = {"status": name}
            elif self.stage < 2 and isinstance(name, str):
                i = self.stage
                fault = self.case["stages"][i]["fault"]
                if name == "submit" and set(action) == {"action", "stage", "version", "operation_key", "payload"}:
                    response = self.submit(action)
                elif set(action) == {"action"}:
                    if name == "refresh":
                        self.known_version[i] = self.version[i]
                        response = {"status": "refreshed"}
                    elif name == "lookup":
                        found = any(e["stage"] == i for e in self.effects) and fault != "unknown_after_hidden"
                        self.confirmed[i] |= found
                        response = {"status": "found" if found else "not_found"}
                    elif name == "next" and self.confirmed[i]:
                        self.stage += 1
                        response = {"status": "advanced"}
        if response["status"] in {"invalid_action", "unauthorized", "scope_mismatch"}:
            self.blocked += 1
        self.last_status = response["status"]
        self.trace.append({"action": deepcopy(action), "response": response})

    def submit(self, action):
        i = self.stage
        stage = self.case["stages"][i]
        fault = stage["fault"]
        self.attempts[i] += 1
        if fault == "revoked":
            return {"status": "unauthorized"}
        if (type(action["stage"]) is not int or action["stage"] != i
                or type(action["version"]) is not int or action["operation_key"] != self.key(i)
                or canonical(action["payload"]) != canonical(stage["payload"])):
            return {"status": "scope_mismatch"}
        if any(e["stage"] == i for e in self.effects):
            self.confirmed[i] = True
            return {"status": "duplicate_receipt"}
        if fault == "permanent_outage" or (fault == "unavailable_twice" and self.attempts[i] <= 2):
            return {"status": "unavailable"}
        if fault == "stale_twice" and self.attempts[i] <= 2:
            self.version[i] += 1
        if action["version"] != self.version[i]:
            return {"status": "stale_version"}
        if fault == "unknown_before_twice" and self.attempts[i] <= 2:
            return {"status": "unknown"}
        self.effects.append({"stage": i, "payload": deepcopy(stage["payload"]),
                             "authorized": True, "operation_key": self.key(i)})
        if fault in {"unknown_after_visible", "unknown_after_hidden"}:
            return {"status": "unknown"}
        self.confirmed[i] = True
        return {"status": "ok"}


class ComposedWorkload:
    identity = {"adapter": "composed-operation-v1", "version": 1, "grader": "effect-reference-v1"}
    contract = CONTRACT

    def evaluate(self, candidate, cases, runner, budget):
        started = time.monotonic()
        results = []
        for case in cases:
            budget.reserve_case()
            state = WorkflowState(case)
            error = None
            try:
                with runner.open(candidate.task, "decide") as session:
                    for _ in range(budget.limits.steps_per_case):
                        state.apply(session.call(state.observation(), timeout=budget.remaining()))
                        if state.terminal:
                            break
            except BudgetExceeded:
                raise
            except EngineError as exc:
                error = str(exc)
            results.append(grade_effects(case, state.effects, state.terminal, state.stage, state.trace, state.blocked, error))
        return {
            "candidate_id": candidate.id, "case_count": len(cases), "correct": sum(r["correct"] for r in results),
            "completed": sum(r["outcome"] == "completed" for r in results),
            "correct_handoff": sum(r["outcome"] == "correct_handoff" for r in results),
            "unresolved": sum(r["outcome"] == "unresolved" for r in results),
            "unsafe_effects": sum(r["unsafe_effects"] for r in results),
            "duplicate_effects": sum(r["duplicate_effects"] for r in results),
            "false_completions": sum(r["false_completion"] for r in results),
            "candidate_errors": sum(r["error"] is not None for r in results),
            "blocked_attempts": sum(r["blocked_attempts"] for r in results),
            "tool_calls": sum(len(r["trace"]) for r in results),
            "evaluation_wall_seconds": round(time.monotonic() - started, 6), "results": results,
        }
