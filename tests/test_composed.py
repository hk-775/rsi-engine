from copy import deepcopy

import pytest

from rsi_engine.composed import WorkflowState, open_pack, write_pack, validate_case
from rsi_engine.contracts import EngineError
from rsi_engine.grading import grade_effects
from rsi_engine.workload import disjoint


@pytest.fixture
def pack(tmp_path):
    return open_pack(write_pack(tmp_path / "pack"))


def test_splits_are_grouped_and_references_valid(pack):
    splits = [pack.cases(s) for s in ("development", "validation", "test")]
    assert [len(s) for s in splits] == [12, 10, 56]
    disjoint(*splits)
    assert len({c["family"] for split in splits for c in split}) == 50
    assert {c["domain"] for c in splits[2]} == {"subscription", "ai_job"}
    for case in sum(splits, []):
        validate_case(case)
    bad = deepcopy(splits[0][0])
    bad["reference"]["effects"].append({"stage": 9, "payload": {}})
    with pytest.raises(EngineError, match="contradicts"):
        validate_case(bad)


def action(state):
    o = state.observation()
    return {k: o[k] for k in ("stage", "version", "operation_key", "payload")} | {"action": "submit"}


def manual_recover(state):
    # Trusted test driver for the simulator; no candidate source is executed.
    for _ in range(24):
        o = state.observation()
        if o["stage"] == 2:
            a = {"action": "complete"}
        elif o["confirmed"]:
            a = {"action": "next"}
        elif o["last_status"] == "unauthorized" or (o["last_status"] == "unavailable" and o["attempts"] >= 3):
            a = {"action": "handoff"}
        elif o["last_status"] == "stale_version":
            a = {"action": "refresh"}
        else:
            a = action(state)
        state.apply(a)
        if state.terminal:
            break


def test_state_machine_has_a_valid_bounded_recovery_for_each_case(pack):
    for split in ("development", "validation", "test"):
        for case in pack.cases(split):
            state = WorkflowState(case)
            manual_recover(state)
            result = grade_effects(case, state.effects, state.terminal, state.stage, state.trace, state.blocked, None)
            assert result["correct"], case["id"]
            assert len(state.trace) <= 24


def test_hidden_receipt_retry_never_duplicates_effect(pack):
    cases = sum([pack.cases(s) for s in ("development", "validation", "test")], [])
    case = next(c for c in cases if c["stages"][0]["fault"] == "unknown_after_hidden")
    state = WorkflowState(case)
    state.apply(action(state))
    assert state.last_status == "unknown" and len(state.effects) == 1
    state.apply({"action": "lookup"})
    assert state.last_status == "not_found" and not state.confirmed[0]
    state.apply(action(state))
    assert state.last_status == "duplicate_receipt" and state.confirmed[0]
    assert len(state.effects) == 1


def test_independent_grader_rejects_fabricated_harm_and_false_completion(pack):
    cases = sum([pack.cases(s) for s in ("development", "validation", "test")], [])
    case = next(c for c in cases if c["reference"]["terminal"] == "complete")
    effects = [{**e, "authorized": True} for e in case["reference"]["effects"]]
    assert grade_effects(case, effects, "complete", 2, [], 0, None)["correct"]
    for mutation in ("wrong_payload", "revoked", "duplicate", "bool_stage"):
        bad = deepcopy(effects)
        if mutation == "wrong_payload":
            bad[0]["payload"] = {"changed": True}
        elif mutation == "revoked":
            bad[0]["authorized"] = False
        elif mutation == "duplicate":
            bad.append(deepcopy(bad[0]))
        else:
            bad[0]["stage"] = False
        result = grade_effects(case, bad, "complete", 2, [], 0, None)
        assert not result["correct"]
        assert result["unsafe_effects"] or result["duplicate_effects"]
    result = grade_effects(case, [], "complete", 0, [], 0, None)
    assert result["false_completion"] and not result["correct"]
