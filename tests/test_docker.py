import os

import pytest

from rsi_engine.archive import audit
from rsi_engine.budget import Limits
from rsi_engine.contracts import Candidate, EngineError
from rsi_engine.engine import evaluate_final, export_evidence, search
from rsi_engine.examples import ScriptedGenerator, write_pack
from rsi_engine.sandbox import DockerRunner
from rsi_engine.workload import Pack, StatefulWorkload

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(os.environ.get("RSI_DOCKER_TESTS") != "1", reason="set RSI_DOCKER_TESTS=1"),
]


@pytest.fixture(scope="module")
def runner():
    return DockerRunner()


@pytest.mark.parametrize("domain", ["subscription", "ai_job"])
def test_complete_search_selection_final_and_export(tmp_path, runner, domain):
    pack = Pack(write_pack(tmp_path / "pack", domain))
    run = tmp_path / "search"
    result = search(pack, ScriptedGenerator(), runner, StatefulWorkload(), run)
    verified = audit(run, True)
    baseline = verified["objects"][result["baseline_development_report"]]["content"]
    assert baseline["correct"] == 3
    assert result["summary"]["correct"] == 8
    assert result["summary"]["completed"] == 6
    assert result["summary"]["correct_handoff"] == 2
    assert result["budget"]["case_evaluations"] == 64
    assert result["budget"]["proposal_calls"] == 3
    assert result["budget"]["total_estimated_usd"] is None
    assert not result["final_test_used"]
    assert not result["recursive_benefit_established"]
    events = verified["events"]
    assert any(e["kind"] == "improver_executed" and "unknown" in e["data"]["plan"]["instruction"] for e in events)
    assert any(e["kind"] == "development_decision" and e["data"]["decision"] == "reject_as_parent" for e in events)
    # The generator sees development evidence only.
    requests = [o["content"] for o in verified["objects"].values() if o["kind"] == "generation_request"]
    assert all("-validation-" not in str(r) and "-test-" not in str(r) for r in requests)
    final = evaluate_final(run, pack, runner, StatefulWorkload(), tmp_path / "final")
    assert final["report"]["correct"] == 8
    assert final["report"]["unsafe_effects"] == 0
    assert final["report"]["duplicate_effects"] == 0
    assert final["provenance"] == "scripted_fixture"
    assert export_evidence(run)["integration_status"] == "standalone_export"
    assert audit(tmp_path / "final")["events"][-1]["kind"] == "final_evaluation_completed"


def test_container_has_no_host_environment_and_cannot_write_root(runner, monkeypatch):
    monkeypatch.setenv("RSI_TEST_PRIVATE", "private-host-value")
    code = '''import os, socket
def decide(context):
    writable = True
    try:
        open("/rsi-root-probe", "w").write("test")
    except OSError:
        writable = False
    network = True
    try:
        s = socket.socket()
        s.settimeout(0.1)
        s.connect(("192.0.2.1", 12345))
    except OSError:
        network = False
    return {"uid": os.getuid(), "secret": os.environ.get("RSI_TEST_PRIVATE"),
            "root_writable": writable, "network": network, "cwd": os.getcwd()}
'''
    with runner.open(code, "decide") as session:
        result = session.call({})
    assert result == {"uid": 65534, "secret": None, "root_writable": False, "network": False, "cwd": "/tmp"}


def test_candidate_cannot_hang_or_flood_host(runner):
    with runner.open("def decide(context):\n    while True: pass\n", "decide") as session:
        with pytest.raises(EngineError, match="timed out"):
            session.call({}, timeout=0.8)
    with runner.open("def decide(context):\n    print('x' * 1000000)\n", "decide") as session:
        with pytest.raises(EngineError, match="limit"):
            session.call({})


def test_exhausted_budget_never_creates_a_final_selection(tmp_path, runner):
    pack = Pack(write_pack(tmp_path / "pack"))
    run = tmp_path / "run"
    with pytest.raises(EngineError, match="budget"):
        search(pack, ScriptedGenerator(), runner, StatefulWorkload(), run,
               Limits(proposals=1, case_evaluations=1))
    assert not (run / "selection.json").exists()
    assert audit(run)["events"][-1]["kind"] == "run_aborted"
