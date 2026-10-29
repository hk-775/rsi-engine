from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
import time

from .contracts import BudgetExceeded, Usage, positive


@dataclass(frozen=True)
class Limits:
    proposals: int = 3
    case_evaluations: int = 120
    wall_seconds: int = 600
    steps_per_case: int = 12

    def __post_init__(self):
        for name, maximum in (("proposals", 1000), ("case_evaluations", 100000),
                              ("wall_seconds", 86400), ("steps_per_case", 100)):
            positive(getattr(self, name), name, maximum)


class Budget:
    def __init__(self, limits: Limits):
        self.limits = limits
        self.started = time.monotonic()
        self.proposals = 0
        self.case_evaluations = 0
        self.usages: list[Usage] = []

    def remaining(self) -> float:
        left = self.limits.wall_seconds - (time.monotonic() - self.started)
        if left <= 0:
            raise BudgetExceeded("Run wall-clock budget exhausted")
        return left

    def reserve_proposal(self):
        self.remaining()
        if self.proposals >= self.limits.proposals:
            raise BudgetExceeded("Proposal budget exhausted")
        self.proposals += 1

    def reserve_case(self):
        self.remaining()
        if self.case_evaluations >= self.limits.case_evaluations:
            raise BudgetExceeded("Case-evaluation budget exhausted")
        self.case_evaluations += 1

    def snapshot(self):
        known = [Decimal(u.estimated_usd) for u in self.usages if u.estimated_usd is not None]
        unknown = self.proposals - len(known)
        return {
            "limits": asdict(self.limits),
            "proposal_calls": self.proposals,
            "case_evaluations": self.case_evaluations,
            "wall_seconds": round(time.monotonic() - self.started, 6),
            "reported_input_tokens": sum(u.input_tokens or 0 for u in self.usages),
            "reported_output_tokens": sum(u.output_tokens or 0 for u in self.usages),
            "calls_with_unknown_tokens": self.proposals - sum(
                u.input_tokens is not None and u.output_tokens is not None for u in self.usages),
            "known_estimated_usd_subtotal": str(sum(known, Decimal(0))),
            "calls_with_unknown_cost": unknown,
            "total_estimated_usd": str(sum(known, Decimal(0))) if unknown == 0 else None,
            "cost_source": "generator_reported_not_independently_verified",
        }
