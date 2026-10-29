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
@pytest.mark.parametrize("backend", ["native", "autohelix"])
def test_complete_search_selection_final_and_export(tmp_path, runner, domain, backend):
    pack = Pack(write_pack(tmp_path / "pack", domain))
    run = tmp_path / "search"
    result = search(pack, ScriptedGenerator(), runner, StatefulWorkload(), run, backend=backend)
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
    assert result["iteration_backend"]["name"] == backend
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
    if backend == "autohelix":
        decisions = [o["content"] for o in verified["objects"].values()
                     if o["kind"] == "autohelix_iteration_result"]
        assert sorted(d["accepted"] for d in decisions) == [False, True, True]
        assert not list((run / "autohelix/workspace/.autohelix/worktrees").glob("iter-*"))


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


@pytest.mark.parametrize("backend", ["native", "autohelix"])
def test_composed_search_executes_edited_improver_with_history(tmp_path, runner, backend):
    from rsi_engine.composed import ComposedWorkload, open_pack, write_pack as write_composed
    from rsi_engine.policy import SearchPolicy
    pack = open_pack(write_composed(tmp_path / "pack"))
    task = '''def decide(c):
    if c["stage"] == 2: return {"action": "complete"}
    if c["confirmed"]: return {"action": "next"}
    if c["last_status"] == "unauthorized": return {"action": "handoff"}
    if c["last_status"] == "unavailable" and c["attempts"] >= 3: return {"action": "handoff"}
    if c["last_status"] == "stale_version": return {"action": "refresh"}
    return {"action": "submit", **{k: c[k] for k in ("stage", "version", "operation_key", "payload")}}
'''
    improver = '''def plan(c):
    return {"target": c["requested_target"], "instruction": "Use bounded retries. History: " + str(len(c["history"]))}
'''
    class Generator:
        identity = "synthetic-composed-fixture"
        provenance = "scripted_fixture"
        def generate(self, request, timeout):
            assert "history" in request
            assert request["plan"]["target"] == ("improver" if request["iteration"] == 0 else "task")
            return {"proposal": {"target": request["plan"]["target"],
                                 "source": improver if request["iteration"] == 0 else task,
                                 "hypothesis": "scripted fixture, not learned"},
                    "usage": {"input_tokens": None, "output_tokens": None, "estimated_usd": None}}
    result = search(pack, Generator(), runner, ComposedWorkload(), tmp_path / "run",
                    Limits(2, 66, 600, 24), SearchPolicy("evolving_history", (0,), True, True), backend)
    assert result["summary"]["correct"] == 10
    verified = audit(tmp_path / "run")
    assert any(e["kind"] == "improvement_plan_executed" and e["data"]["edited_improver"]
               and e["data"]["plan"]["instruction"].endswith("1") for e in verified["events"])
    final = evaluate_final(tmp_path / "run", pack, runner, ComposedWorkload(), tmp_path / "final",
                           Limits(1, 56, 600, 24))
    assert final["report"]["correct"] == 56


def test_autohelix_preserves_fatal_budget_failure(tmp_path, runner):
    pack = Pack(write_pack(tmp_path / "pack"))
    run = tmp_path / "run"
    with pytest.raises(EngineError, match="budget"):
        search(pack, ScriptedGenerator(), runner, StatefulWorkload(), run,
               Limits(proposals=1, case_evaluations=8), backend="autohelix")
    assert not (run / "selection.json").exists()
    assert audit(run)["events"][-1]["kind"] == "run_aborted"
    assert not list((run / "autohelix/workspace/.autohelix/worktrees").glob("iter-*"))
