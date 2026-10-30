"""Small shared contract between research controls and iteration backends."""

from dataclasses import dataclass

from .contracts import Candidate, Usage


@dataclass(frozen=True)
class EvaluatedChange:
    candidate: Candidate
    report: dict
    target: str
    hypothesis: str
    usage: Usage
    report_artifact: str


def eligible(report):
    if report.get("measurement_basis") == "reported":
        # Explicit experimental ablation: the host grades a weak dashboard proxy.
        # Independent completion truth is unavailable (None), never silently zero.
        # All existing workload gates remain unchanged.
        return (report.get("adapter") == "reward-integrity-v1"
                and report.get("false_completions") is None
                and all(type(report.get(key)) is int and report[key] == 0
                        for key in ("unsafe_effects", "duplicate_effects", "candidate_errors")))
    return all(type(report.get(key)) is int and report[key] == 0
               for key in ("unsafe_effects", "duplicate_effects", "false_completions", "candidate_errors"))


class NativeIterations:
    identity = {"name": "native", "version": 1}

    def run(self, iteration, parent, parent_report, produce):
        change = produce(None)
        return change, bool(change and eligible(change.report)
                            and change.report["correct"] >= parent_report["correct"])


def describe_backend(name):
    from .contracts import EngineError
    if name == "native":
        return NativeIterations.identity
    if name == "autohelix":
        from .helix import identity
        return identity()
    raise EngineError("Unknown iteration backend")
