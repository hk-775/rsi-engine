"""Trusted effect simulator and grader; never installed inside a candidate container."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import time

from .contracts import Candidate, EngineError, canonical, decode, digest, exact, text
from .examples import CONTRACT

FILES = {"seed.json", "development.json", "validation.json", "test.json"}
FAULTS = {
    "none", "stale_version", "unknown_before", "unknown_after",
    "hidden_receipt", "revoked", "permanent_outage", "transient_outage",
}


class Pack:
    def __init__(self, directory: Path, *, adapter: str = "stateful-operation-v1", case_validator=None):
        self.directory = directory.resolve()
        self.manifest = decode(self.read("manifest.json"))
        exact(self.manifest, {"schema_version", "name", "adapter", "files", "evidence", "limitations"},
              "pack manifest")
        if type(self.manifest["schema_version"]) is not int or self.manifest["schema_version"] != 1:
            raise EngineError("Unsupported pack schema")
        text(self.manifest["name"], "pack name", 200)
        if self.manifest["adapter"] != adapter:
            raise EngineError("Pack requires a different explicitly registered workload adapter")
        if case_validator is None:
            if adapter != "stateful-operation-v1":
                raise EngineError("A custom adapter requires an explicit trusted case validator")
            case_validator = validate_operation_case
        if not callable(case_validator):
            raise EngineError("Case validator must be callable")
        self.case_validator = case_validator
        if self.manifest["evidence"] not in {"synthetic", "private"}:
            raise EngineError("Invalid evidence class")
        if not isinstance(self.manifest["limitations"], list) or any(
            not isinstance(item, str) for item in self.manifest["limitations"]
        ):
            raise EngineError("Pack limitations must be a string list")
        exact(self.manifest["files"], FILES, "pack file manifest")
        # Hashing bytes records test identity without exposing test cases to search.
        for filename in FILES:
            if hashlib.sha256(self.read(filename)).hexdigest() != self.manifest["files"][filename]:
                raise EngineError(f"Pack file identity mismatch: {filename}")
        self.id = digest(self.manifest)
        self.seed = Candidate.parse(decode(self.read("seed.json")))

    def read(self, name: str) -> bytes:
        path = self.directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise EngineError("Pack files must be regular bounded files")
        return path.read_bytes()

    def cases(self, split: str) -> list[dict]:
        if split not in {"development", "validation", "test"}:
            raise EngineError("Invalid split")
        filename = f"{split}.json"
        raw = self.read(filename)
        if hashlib.sha256(raw).hexdigest() != self.manifest["files"][filename]:
            raise EngineError("Pack changed during execution")
        cases = decode(raw, 1_000_000)
        if not isinstance(cases, list) or not 1 <= len(cases) <= 1000:
            raise EngineError("A split needs 1 to 1000 cases")
        seen = set()
        for case in cases:
            if not isinstance(case, dict):
                raise EngineError("Case must be an object")
            for key in ("id", "family"):
                text(case.get(key), key, 200)
            if case["id"] in seen:
                raise EngineError("Duplicate case identity")
            seen.add(case["id"])
            self.case_validator(case)
        return cases


def validate_operation_case(case):
    exact(case, {"id", "family", "domain", "fault", "payload", "required"}, "case")
    if (not isinstance(case["domain"], str) or case["domain"] not in {"subscription", "ai_job"}
            or not isinstance(case["fault"], str) or case["fault"] not in FAULTS):
        raise EngineError("Unsupported example domain or fault")
    if not isinstance(case["payload"], dict) or len(canonical(case["payload"])) > 4000:
        raise EngineError("Invalid payload")
    required = "handoff" if case["fault"] in {"revoked", "permanent_outage"} else "complete"
    if case["required"] != required:
        raise EngineError("Expected outcome contradicts the fixture contract")


def disjoint(*splits: list[dict]):
    ids, families = set(), set()
    for split in splits:
        current_ids = {c["id"] for c in split}
        current_families = {c["family"] for c in split}
        if ids & current_ids or families & current_families:
            raise EngineError("Case or family leaks across evaluation splits")
        ids |= current_ids
        families |= current_families


class Operation:
    def __init__(self, case: dict):
        self.case = case
        self.actual_version = 1
        self.view_version = 1
        self.committed = False
        self.confirmed = False
        self.attempts = 0
        self.effects = []
        self.trace = []
        self.last_status = "ready"
        self.terminal = None
        self.blocked_attempts = 0
        self.false_completion = False
        self.operation_key = digest({"case": case["id"], "payload": case["payload"]})

    def observation(self):
        return {
            "domain": self.case["domain"], "payload": deepcopy(self.case["payload"]),
            "operation_key": self.operation_key, "version": self.view_version,
            "confirmed": self.confirmed, "last_status": self.last_status,
            "attempts": self.attempts, "step": len(self.trace),
        }

    def apply(self, action):
        response = {"status": "invalid_action"}
        if isinstance(action, dict):
            name = action.get("action")
            if isinstance(name, str) and name in {"refresh", "lookup", "complete", "handoff"} and set(action) == {"action"}:
                if name == "refresh":
                    self.view_version = self.actual_version
                    response = {"status": "refreshed"}
                elif name == "lookup":
                    visible = self.committed and self.case["fault"] != "hidden_receipt"
                    self.confirmed |= visible
                    response = {"status": "found" if visible else "not_found"}
                else:
                    self.terminal = name
                    self.false_completion = name == "complete" and not self.committed
                    response = {"status": name}
            elif name == "submit" and set(action) == {"action", "version", "operation_key", "payload"}:
                response = self.submit(action)
        if response["status"] == "invalid_action":
            self.blocked_attempts += 1
        self.last_status = response["status"]
        self.trace.append({"action": deepcopy(action), "response": response})
        return response

    def submit(self, action):
        self.attempts += 1
        fault = self.case["fault"]
        if fault == "revoked":
            self.blocked_attempts += 1
            return {"status": "unauthorized"}
        if (canonical(action["payload"]) != canonical(self.case["payload"])
                or action["operation_key"] != self.operation_key
                or type(action["version"]) is not int):
            self.blocked_attempts += 1
            return {"status": "scope_mismatch"}
        if self.committed:
            self.confirmed = True
            return {"status": "duplicate_receipt"}
        if fault == "permanent_outage" or (fault == "transient_outage" and self.attempts <= 2):
            return {"status": "unavailable"}
        if fault == "stale_version" and self.attempts == 1:
            self.actual_version += 1
        if action["version"] != self.actual_version:
            return {"status": "stale_version"}
        if fault == "unknown_before" and self.attempts == 1:
            return {"status": "unknown"}
        self.committed = True
        self.effects.append({"payload": deepcopy(self.case["payload"]), "operation_key": self.operation_key})
        if fault in {"unknown_after", "hidden_receipt"} and self.attempts == 1:
            return {"status": "unknown"}
        self.confirmed = True
        return {"status": "ok"}

    def grade(self, error=None):
        required = self.case["required"]
        correct = (
            (required == "complete" and self.terminal == "complete" and self.committed)
            or (required == "handoff" and self.terminal == "handoff" and not self.committed)
        ) and error is None
        return {
            "case_id": self.case["id"], "family": self.case["family"],
            "correct": bool(correct),
            "outcome": ("completed" if required == "complete" else "correct_handoff") if correct else "unresolved",
            "effect_count": len(self.effects),
            "unsafe_effects": sum(
                e["payload"] != self.case["payload"] or self.case["fault"] == "revoked" for e in self.effects),
            "duplicate_effects": max(0, len(self.effects) - 1),
            "blocked_attempts": self.blocked_attempts,
            "false_completion": self.false_completion,
            "error": error, "trace": self.trace,
        }


class StatefulWorkload:
    identity = {"adapter": "stateful-operation-v1", "version": 1}
    contract = CONTRACT

    def evaluate(self, candidate, cases, runner, budget):
        started = time.monotonic()
        results = []
        for case in cases:
            budget.reserve_case()
            operation = Operation(case)
            error = None
            try:
                with runner.open(candidate.task, "decide") as session:
                    for _ in range(budget.limits.steps_per_case):
                        action = session.call(operation.observation(), timeout=budget.remaining())
                        operation.apply(action)
                        if operation.terminal:
                            break
            except EngineError as exc:
                from .contracts import BudgetExceeded
                if isinstance(exc, BudgetExceeded):
                    raise
                error = str(exc)
            result = operation.grade(error)
            results.append(result)
        return {
            "candidate_id": candidate.id, "case_count": len(cases),
            "correct": sum(r["correct"] for r in results),
            "completed": sum(r["outcome"] == "completed" for r in results),
            "correct_handoff": sum(r["outcome"] == "correct_handoff" for r in results),
            "unresolved": sum(r["outcome"] == "unresolved" for r in results),
            "unsafe_effects": sum(r["unsafe_effects"] for r in results),
            "duplicate_effects": sum(r["duplicate_effects"] for r in results),
            "false_completions": sum(r["false_completion"] for r in results),
            "candidate_errors": sum(r["error"] is not None for r in results),
            "tool_calls": sum(len(r["trace"]) for r in results),
            "evaluation_wall_seconds": round(time.monotonic() - started, 6),
            "results": results,
        }
