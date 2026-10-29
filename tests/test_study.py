from types import SimpleNamespace

import pytest

from rsi_engine.bedrock import BedrockConfig
from rsi_engine.composed import open_pack, write_pack
from rsi_engine.contracts import EngineError, canonical
from rsi_engine.policy import SearchPolicy, compact_report
from rsi_engine.study import evaluate_study, prepare, read_record, run_study, verify_protocol


@pytest.fixture
def registered(tmp_path):
    pack = open_pack(write_pack(tmp_path / "pack"))
    runner = SimpleNamespace(identity={"fixture": "no code execution"})
    config = BedrockConfig("fixture", "us-west-2", "3.30", "16.50", "public fixture", "2026-10-29")
    root = tmp_path / "study"
    prepare(root, pack, runner, config)
    return root, pack, runner


def test_policy_keeps_history_access_equal_and_schedules_edit_budget():
    frozen = SearchPolicy("frozen_history", (), True, True)
    evolving = SearchPolicy("evolving_history", (0,), True, True)
    assert [frozen.target(i) for i in range(4)] == ["task"] * 4
    assert [evolving.target(i) for i in range(4)] == ["improver", "task", "task", "task"]
    with pytest.raises(EngineError):
        SearchPolicy("frozen_history", (0,))
    report = {"correct": 0, "evaluation_wall_seconds": 99,
              "results": [{"case_id": "synthetic", "correct": False, "outcome": "unresolved", "error": None,
                           "trace": [{"action": {"action": "submit", "payload": {"large": "value"}},
                                      "response": {"status": "unknown"}}]}]}
    compact = compact_report(report)
    assert "evaluation_wall_seconds" not in compact
    assert compact["results"][0]["trace"][0]["response"]["status"] == "unknown"


def test_prepare_never_opens_final_split(registered, monkeypatch):
    root, pack, runner = registered
    record = read_record(root / "protocol.json")
    assert len(record["content"]["order"]) == 6
    assert record["content"]["estimated_inference_ceiling_usd"] == "3.00"
    original = pack.cases
    def spy(split):
        assert split != "test", "Final split opened before the selection barrier"
        return original(split)
    monkeypatch.setattr(pack, "cases", spy)
    with pytest.raises(FileNotFoundError):
        evaluate_study(root, pack, runner)


def test_interrupted_study_cannot_reset_paid_budget(registered, monkeypatch):
    root, pack, runner = registered
    def factory(*args, **kwargs):
        raise EngineError("synthetic interruption before any inference")
    with pytest.raises(EngineError, match="interruption"):
        run_study(root, pack, runner, generator_factory=factory)
    assert (root / "execution-cost.json").exists()
    with pytest.raises(FileExistsError):
        run_study(root, pack, runner, generator_factory=factory)


def test_protocol_identity_detects_changes(registered):
    root, pack, runner = registered
    with pytest.raises(EngineError, match="changed"):
        verify_protocol(root, pack, SimpleNamespace(identity={"fixture": "different"}))
    record = read_record(root / "protocol.json")
    record["content"]["model"]["temperature"] = 0.9
    (root / "protocol.json").chmod(0o600)
    (root / "protocol.json").write_bytes(canonical(record))
    with pytest.raises(EngineError, match="hash mismatch"):
        read_record(root / "protocol.json")
