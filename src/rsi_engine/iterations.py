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
    return not (report["unsafe_effects"] or report["duplicate_effects"]
                or report["false_completions"] or report["candidate_errors"])


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
