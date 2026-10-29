"""Predeclared experimental policies and identical feedback access."""

from dataclasses import dataclass

from .contracts import EngineError


@dataclass(frozen=True)
class SearchPolicy:
    name: str = "prototype"
    meta_iterations: tuple[int, ...] = ()
    history: bool = False
    compact: bool = False

    def __post_init__(self):
        if self.name not in {"prototype", "frozen_history", "evolving_history"}:
            raise EngineError("Unknown search policy")
        if any(type(i) is not int or i < 0 for i in self.meta_iterations):
            raise EngineError("Invalid strategy-edit schedule")
        if self.name == "frozen_history" and self.meta_iterations:
            raise EngineError("Frozen policies cannot edit their improver")

    def target(self, iteration):
        if self.name == "prototype":
            return None
        return "improver" if iteration in self.meta_iterations else "task"


def compact_report(report):
    """Preserve all case outcomes and status sequences; bound repeated payload text."""
    result = {k: v for k, v in report.items() if k not in {"results", "evaluation_wall_seconds"}}
    result["results"] = [
        {
            "case_id": row["case_id"], "correct": row["correct"], "outcome": row["outcome"],
            "error": row["error"],
            "trace": [
                {"action": {"action": step["action"].get("action")} if isinstance(step["action"], dict) else {},
                 "response": step["response"]}
                for step in row["trace"]
            ],
        } for row in report["results"]
    ]
    return result
