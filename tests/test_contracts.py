from dataclasses import asdict
from decimal import Decimal

import pytest

from rsi_engine.budget import Budget, Limits
from rsi_engine.contracts import (
    BudgetExceeded, Candidate, EngineError, Proposal, Usage, canonical, decode,
)
from rsi_engine.examples import BASE_TASK, BASE_IMPROVER, IMPROVED_IMPROVER


def test_candidate_edits_are_confined_to_one_module():
    parent = Candidate(BASE_TASK, BASE_IMPROVER)
    child = Proposal("improver", IMPROVED_IMPROVER, "Improve diagnosis").apply(parent)
    assert child.task == parent.task
    assert child.id != parent.id
    assert Candidate.parse(asdict(child)) == child


@pytest.mark.parametrize("target", ["../../grader.py", "evaluator", [], None])
def test_cannot_edit_protected_files(target):
    with pytest.raises(EngineError):
        Proposal(target, BASE_TASK, "test")


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":'])
def test_rejects_ambiguous_json(raw):
    with pytest.raises(EngineError):
        decode(raw)


@pytest.mark.parametrize("code", ["def decide(:", "def wrong(x): return x", "x" * 40000])
def test_rejects_invalid_candidate(code):
    with pytest.raises(EngineError):
        Candidate(code, BASE_IMPROVER)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", 0.4, "1e999"])
def test_cost_is_bounded_decimal_text(value):
    with pytest.raises(EngineError):
        Usage(estimated_usd=value)


def test_unknown_usage_does_not_become_zero_total():
    budget = Budget(Limits(proposals=2))
    budget.reserve_proposal()
    budget.usages.append(Usage(10, 20, "0.001"))
    budget.reserve_proposal()
    snapshot = budget.snapshot()
    assert snapshot["total_estimated_usd"] is None
    assert Decimal(snapshot["known_estimated_usd_subtotal"]) == Decimal("0.001")
    assert snapshot["calls_with_unknown_cost"] == 1


def test_failed_calls_and_evaluations_consume_budget():
    budget = Budget(Limits(proposals=1, case_evaluations=1))
    budget.reserve_case()
    budget.reserve_proposal()
    with pytest.raises(BudgetExceeded):
        budget.reserve_case()
    with pytest.raises(BudgetExceeded):
        budget.reserve_proposal()


def test_booleans_are_not_token_counts():
    with pytest.raises(EngineError):
        Usage(input_tokens=True)


def test_source_is_never_executed_during_validation(tmp_path):
    marker = tmp_path / "should-not-exist"
    Candidate(f"open({str(marker)!r}, 'w').write('bad')\ndef decide(context): return {{}}", BASE_IMPROVER)
    assert not marker.exists()
