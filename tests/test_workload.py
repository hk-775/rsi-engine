import pytest
import json

from rsi_engine.contracts import EngineError
from rsi_engine.examples import write_pack
from rsi_engine.workload import Operation, Pack, disjoint


@pytest.fixture
def pack(tmp_path):
    return Pack(write_pack(tmp_path / "pack"))


def case(pack, fault):
    return next(c for c in pack.cases("development") if c["fault"] == fault)


def submit(operation, **changes):
    value = operation.observation()
    return operation.apply({
        "action": "submit", "version": value["version"],
        "payload": value["payload"], "operation_key": value["operation_key"], **changes,
    })


def test_claiming_completion_does_not_change_business_state(pack):
    operation = Operation(case(pack, "none"))
    operation.apply({"action": "complete"})
    assert operation.grade()["false_completion"]
    assert operation.grade()["effect_count"] == 0
    assert not operation.grade()["correct"]


def test_hidden_receipt_does_not_erase_a_committed_effect(pack):
    operation = Operation(case(pack, "hidden_receipt"))
    assert submit(operation)["status"] == "unknown"
    assert operation.apply({"action": "lookup"})["status"] == "not_found"
    assert submit(operation)["status"] == "duplicate_receipt"
    operation.apply({"action": "complete"})
    assert operation.grade()["correct"]
    assert operation.grade()["effect_count"] == 1


def test_stale_version_requires_actual_refresh(pack):
    operation = Operation(case(pack, "stale_version"))
    assert submit(operation)["status"] == "stale_version"
    assert submit(operation)["status"] == "stale_version"
    operation.apply({"action": "refresh"})
    assert submit(operation)["status"] == "ok"


def test_guard_rejects_changed_payload_and_revoked_authority(pack):
    operation = Operation(case(pack, "none"))
    assert submit(operation, payload={"refund_units": 99999})["status"] == "scope_mismatch"
    assert operation.grade()["effect_count"] == 0
    revoked = Operation(case(pack, "revoked"))
    assert submit(revoked)["status"] == "unauthorized"
    revoked.apply({"action": "handoff"})
    assert revoked.grade()["correct"]
    assert revoked.grade()["unsafe_effects"] == 0


@pytest.mark.parametrize("action", [{"action": []}, {"action": True}, [], None,
                                  {"action": "complete", "effect_count": 1}])
def test_malformed_actions_are_blocked(pack, action):
    operation = Operation(case(pack, "none"))
    assert operation.apply(action)["status"] == "invalid_action"
    assert operation.grade()["effect_count"] == 0


def test_correct_handoff_is_distinct_from_unnecessary_handoff(pack):
    clean = Operation(case(pack, "none"))
    outage = Operation(case(pack, "permanent_outage"))
    clean.apply({"action": "handoff"})
    outage.apply({"action": "handoff"})
    assert clean.grade()["outcome"] == "unresolved"
    assert outage.grade()["outcome"] == "correct_handoff"


def test_pack_changes_are_detected(pack):
    (pack.directory / "test.json").write_text("[]")
    with pytest.raises(EngineError, match="changed"):
        pack.cases("test")


def test_family_leakage_is_rejected(pack):
    dev = pack.cases("development")
    validation = pack.cases("validation")
    validation[0]["family"] = dev[0]["family"]
    with pytest.raises(EngineError, match="leaks"):
        disjoint(dev, validation)


def test_candidates_do_not_receive_faults_or_expected_outcomes(pack):
    observation = Operation(case(pack, "unknown_after")).observation()
    assert not {"fault", "required", "family", "id"} & set(observation)


def test_custom_adapter_requires_explicit_trusted_registration(pack):
    path = pack.directory / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["adapter"] = "my-workload-v1"
    path.write_text(json.dumps(manifest))
    with pytest.raises(EngineError, match="different"):
        Pack(pack.directory)
    with pytest.raises(EngineError, match="validator"):
        Pack(pack.directory, adapter="my-workload-v1")
    checked = []
    custom = Pack(pack.directory, adapter="my-workload-v1", case_validator=lambda c: checked.append(c["id"]))
    assert len(custom.cases("development")) == len(checked) == 8
