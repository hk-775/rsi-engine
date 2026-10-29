from dataclasses import asdict
from pathlib import Path
import subprocess
import sys

import pytest

from rsi_engine.archive import Archive, audit
from rsi_engine.budget import Budget, Limits
from rsi_engine.contracts import BackendError, BudgetExceeded, Candidate, EngineError, Usage, canonical, decode
from rsi_engine.helix import AutoHelixIterations, identity, read_candidate
from rsi_engine.helix_check import inspect_receipt
from rsi_engine.iterations import EvaluatedChange, describe_backend


def candidate(label):
    # This top-level statement would fail if a receipt checker imported source.
    return Candidate(
        f"raise RuntimeError('must never import fixture {label}')\n"
        "def decide(context):\n    return {'action':'handoff'}\n",
        "def plan(context):\n    return {'target':'task','instruction':'fixture'}\n",
    )


def report(correct, **extra):
    return {"correct": correct, "tool_calls": 4, "unsafe_effects": 0,
            "duplicate_effects": 0, "false_completions": 0, "candidate_errors": 0, **extra}


def change(label, correct):
    return EvaluatedChange(candidate(label), report(correct), "task", "fixture " + label, Usage(), "test-report")


@pytest.fixture
def backend(tmp_path):
    archive = Archive(tmp_path / "run")
    archive.event("test_started", {})
    return AutoHelixIterations(archive, candidate("seed"), report(1), Budget(Limits()))


def test_upstream_worktree_gates_merges_and_rejected_notes(backend):
    first = change("better", 2)
    produced, accepted = backend.run(0, candidate("seed"), report(1), lambda context: first)
    assert accepted and produced == first
    assert read_candidate(backend.project) == first.candidate
    worse = change("regression", 0)
    _, accepted = backend.run(1, first.candidate, first.report, lambda context: worse)
    assert not accepted and read_candidate(backend.project) == first.candidate
    def proposal(context):
        assert context["notes"]["hypothesis"] == "fixture regression"
        assert context["history"][-1]["accepted"] is False
        return change("recovered", 3)
    _, accepted = backend.run(2, first.candidate, first.report, proposal)
    assert accepted
    records = backend.harness.history.load()
    assert [r.accepted for r in records] == [True, True, False, True]
    assert [r.commit is not None for r in records[1:]] == [True, False, True]
    assert records[1].usage["cost_known"] is False
    assert records[1].usage["rsi_usage"]["estimated_usd"] is None
    assert "cost_usd" not in records[1].usage
    verified = audit(backend.archive.root)
    assert sum(e["kind"] == "autohelix_iteration_completed" for e in verified["events"]) == 3
    assert not list((backend.project / ".autohelix" / "worktrees").glob("iter-*"))


@pytest.mark.parametrize("error", [EngineError("invalid fixture"), BudgetExceeded("fixture budget exhausted")])
def test_failed_proposals_cleanup_and_preserve_original_error(backend, error):
    def failing(_):
        raise error
    with pytest.raises(type(error), match=str(error)):
        backend.run(0, candidate("seed"), report(1), failing)
    assert not backend.harness.history.load()[-1].accepted
    assert read_candidate(backend.project) == candidate("seed")
    assert not list((backend.project / ".autohelix" / "worktrees").glob("iter-*"))
    assert audit(backend.archive.root)["events"][-1]["kind"] == "autohelix_iteration_completed"


def test_duplicate_proposal_cannot_be_accepted(backend):
    result, accepted = backend.run(0, candidate("seed"), report(1), lambda _: None)
    assert result is None and not accepted
    assert read_candidate(backend.project) == candidate("seed")


def test_modification_after_evaluation_cannot_be_committed(backend, monkeypatch):
    original = backend.harness.run_agent
    def tamper(worktree, prompt, iteration):
        result = original(worktree, prompt, iteration)
        with (worktree / "task.py").open("a") as stream:
            stream.write("\n# changed after the evaluator finished\n")
        return result
    monkeypatch.setattr(backend.harness, "run_agent", tamper)
    with pytest.raises(BackendError, match="acceptance disagrees"):
        backend.run(0, candidate("seed"), report(1), lambda _: change("tampered", 2))
    assert read_candidate(backend.project) == candidate("seed")
    assert not backend.harness.history.load()[-1].accepted


def test_receipt_checker_rejects_linked_source(tmp_path):
    import hashlib
    worktree = tmp_path / "iter-1"
    worktree.mkdir()
    control = tmp_path / "control"
    control.mkdir()
    c = candidate("data-only")
    for module in ("task", "improver"):
        (worktree / (module + ".py")).write_text(getattr(c, module))
    receipt = {"schema": 1, "worktree": str(worktree), "allowed": True,
               "source_hashes": {k: hashlib.sha256(getattr(c, k).encode()).hexdigest() for k in ("task", "improver")},
               "metrics": {"correct": 2, "tool_calls": 4}}
    (control / "iter-1.json").write_bytes(canonical(receipt))
    assert inspect_receipt(control, worktree)["allowed"]
    from rsi_engine import helix_check
    result = subprocess.run([sys.executable, "-I", "-S", helix_check.__file__,
                             "--control", str(control), "metrics"], cwd=worktree, capture_output=True, text=True)
    assert result.returncode == 0  # The top-level RuntimeError was never executed.
    assert "##autohelix[correct=2]" in result.stdout
    target = worktree / "task.py"
    target.unlink()
    target.symlink_to(worktree / "improver.py")
    with pytest.raises(ValueError, match="linked"):
        inspect_receipt(control, worktree)


def test_backend_identity_is_pinned_and_invalid_choice_fails():
    assert identity()["version"] == "0.1.0"
    assert len(identity()["package_digest"]) == 64
    with pytest.raises(EngineError, match="Unknown"):
        describe_backend("unregistered")
