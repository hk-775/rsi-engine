"""A registered, bounded comparison with a barrier before any final evaluation."""

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .archive import Archive, audit, write_new
from .bedrock import BedrockConfig, BedrockGenerator, CostLedger, decimal_amount
from .budget import Budget, Limits
from .composed import ComposedWorkload, open_pack
from .contracts import EngineError, canonical, decode, digest
from .engine import evaluate_final, kernel_identity, search, selected
from .iterations import describe_backend
from .policy import SearchPolicy
from .workload import disjoint

ARMS = {
    "frozen_history": SearchPolicy("frozen_history", (), True, True),
    "evolving_history": SearchPolicy("evolving_history", (0,), True, True),
}
LIMITS = Limits(proposals=4, case_evaluations=110, wall_seconds=1200, steps_per_case=24)
FINAL_LIMITS = Limits(proposals=1, case_evaluations=56, wall_seconds=600, steps_per_case=24)


def envelope(value):
    return {"id": digest(value), "content": value}


def read_record(path):
    record = decode(path.read_bytes(), 16_000_000)
    if set(record) != {"id", "content"} or digest(record["content"]) != record["id"]:
        raise EngineError("Study record hash mismatch")
    return record


def prepare(root: Path, pack, runner, config: BedrockConfig, ceiling="3.00", backend="native"):
    if decimal_amount(ceiling, "study ceiling") > Decimal("3.00"):
        raise EngineError("This pilot supports at most $3 estimated inference cost")
    if config.max_calls != 4 or Decimal(config.max_estimated_usd) > Decimal("0.50"):
        raise EngineError("Pilot requires four calls and at most $0.50 per arm run")
    if pack.manifest["adapter"] != "composed-operation-v1":
        raise EngineError("Pilot requires the composed workflow pack")
    dev, val = pack.cases("development"), pack.cases("validation")
    disjoint(dev, val)
    if (len(dev), len(val)) != (12, 10):
        raise EngineError("Unexpected pilot calibration split sizes")
    order = [
        {"block": block, "arm": arm, "name": f"block-{block}-{arm}"}
        for block in range(1, 4)
        for arm in (tuple(ARMS) if block % 2 else tuple(reversed(ARMS)))
    ]
    protocol = {
        "schema": "rsi-engine.pilot.v1",
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "question": "Does spending one of four model calls on improver code improve final "
                    "workflow correctness compared with spending all four on task code?",
        "estimand": "Effect of the scheduled editing strategy under a common resource allowance.",
        "primary_metric": "Paired difference in selected-candidate final correctness, evolving minus frozen.",
        "design": "Three sequential paired blocks with alternating arm order; no shared model RNG seed.",
        "kernel_id": kernel_identity(), "pack_id": pack.id, "runner": runner.identity,
        "workload": ComposedWorkload.identity, "model": asdict(config),
        "iteration_backend": describe_backend(backend),
        "arms": {k: asdict(v) for k, v in ARMS.items()}, "order": order,
        "limits": asdict(LIMITS), "final_limits": asdict(FINAL_LIMITS),
        "estimated_inference_ceiling_usd": ceiling,
        "selection_rule": "Maximum eligible validation correctness, then fewer actions, then earliest revision.",
        "test_rule": "Commit all six selections before loading test cases; no feedback from test.",
        "baseline_rule": "Evaluate the unchanged seed once after the selection barrier.",
        "limitations": [
            "Small synthetic pilot, not a production reliability estimate or proof of recursive advantage.",
            "The evolving arm spends one call editing its improver and has three task-edit calls.",
            "Both arms receive the same contract, development feedback format and history access.",
            "Three blocks are the repeated-run units; test domain variants are correlated within 28 families.",
            "Same author and simulator; the separate effect grader is not external independent validation.",
            "A fixed schedule allows improver editing; it does not demonstrate open-ended recursive improvement.",
            "No training or weight updates, deployment, or existing-project integration.",
            "Costs are token-rate estimates, not an AWS invoice; local compute and engineering time excluded.",
        ],
    }
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    record = envelope(protocol)
    write_new(root / "protocol.json", canonical(record) + b"\n", 0o400)
    return record


def verify_protocol(root, pack, runner):
    record = read_record(root / "protocol.json")
    p = record["content"]
    if p["kernel_id"] != kernel_identity() or p["pack_id"] != pack.id or p["runner"] != runner.identity:
        raise EngineError("Engine, pack or runner changed after pilot registration")
    if p["workload"] != ComposedWorkload.identity:
        raise EngineError("Workload changed after registration")
    if p["iteration_backend"] != describe_backend(p["iteration_backend"]["name"]):
        raise EngineError("Iteration backend changed after registration")
    return record


def run_study(root: Path, pack, runner, *, generator_factory=BedrockGenerator, progress=None):
    record = verify_protocol(root, pack, runner)
    p = record["content"]
    # Exclusive one-shot marker prevents a retry from silently resetting a paid budget.
    write_new(root / "execution-started.json", canonical({"protocol_id": record["id"]}) + b"\n")
    ledger = CostLedger(p["estimated_inference_ceiling_usd"])
    config = BedrockConfig(**p["model"])
    selections = []
    try:
        for item in p["order"]:
            if progress:
                progress({"phase": "search_started", **item})
            generator = generator_factory(config, shared_ledger=ledger)
            raw_policy = p["arms"][item["arm"]]
            policy = SearchPolicy(raw_policy["name"], tuple(raw_policy["meta_iterations"]),
                                  raw_policy["history"], raw_policy["compact"])
            search(pack, generator, runner, ComposedWorkload(), root / item["name"],
                   Limits(**p["limits"]), policy, p["iteration_backend"]["name"])
            candidate, _, verified = selected(root / item["name"])
            selections.append({**item, "candidate_id": candidate.id, "chain_head": verified["chain_head"]})
            if progress:
                progress({"phase": "selection_committed", **item,
                          "validation_correct": verified["selection"]["summary"]["correct"],
                          "cost": ledger.snapshot()})
        barrier = envelope({"protocol_id": record["id"], "selections": selections, "cost": ledger.snapshot()})
        write_new(root / "selections.json", canonical(barrier) + b"\n", 0o400)
        return barrier
    finally:
        write_new(root / "execution-cost.json", canonical(ledger.snapshot()) + b"\n", 0o400)


def verify_barrier(root, record):
    barrier = read_record(root / "selections.json")
    b = barrier["content"]
    if b["protocol_id"] != record["id"] or len(b["selections"]) != len(record["content"]["order"]):
        raise EngineError("Incomplete or mismatched selection barrier")
    for selection, expected in zip(b["selections"], record["content"]["order"], strict=True):
        if any(selection[k] != expected[k] for k in ("block", "arm", "name")):
            raise EngineError("Selection barrier order mismatch")
        candidate, manifest, verified = selected(root / expected["name"])
        if (candidate.id != selection["candidate_id"] or verified["chain_head"] != selection["chain_head"]
                or manifest["kernel_id"] != record["content"]["kernel_id"]
                or manifest["pack_id"] != record["content"]["pack_id"]
                or manifest["iteration_backend"] != record["content"]["iteration_backend"]
                or manifest["generator_settings"] is None
                or any(manifest["generator_settings"][k] != v for k, v in record["content"]["model"].items())
                or manifest["search_policy"] != record["content"]["arms"][expected["arm"]]):
            raise EngineError("Selection changed or violates the registered protocol")
    return barrier


def evaluate_study(root: Path, pack, runner, *, progress=None):
    record = verify_protocol(root, pack, runner)
    barrier = verify_barrier(root, record)
    # No final data access is allowed above this point.
    dev, val, test = (pack.cases(split) for split in ("development", "validation", "test"))
    disjoint(dev, val, test)
    if len(test) != 56 or len({c["family"] for c in test}) != 28:
        raise EngineError("Unexpected pilot test shape")
    archive = Archive(root / "final")
    origin = archive.put("study_origin", {"protocol": record, "barrier": barrier})
    workload = ComposedWorkload()
    seed_report = workload.evaluate(pack.seed, test, runner, Budget(FINAL_LIMITS))
    seed_artifact = archive.put("seed_final_report", seed_report)
    rows = []
    for item in barrier["content"]["selections"]:
        if progress:
            progress({"phase": "final_started", "name": item["name"]})
        result = evaluate_final(root / item["name"], pack, runner, workload,
                                root / "final" / item["name"], FINAL_LIMITS)
        verified = audit(root / item["name"], require_selection=True)
        provider_calls = [o["content"] for o in verified["objects"].values()
                          if o["kind"] == "provider_call" and o["content"]["inference_sent"]]
        row = {
            **item,
            "final": {k: v for k, v in result["report"].items() if k != "results"},
            "search_budget": verified["selection"]["budget"],
            "inference_calls": len(provider_calls),
            "provider_wall_seconds": round(sum(c["wall_seconds"] for c in provider_calls), 6),
            "edited_improver_probe_executions": sum(e["kind"] == "improver_executed" for e in verified["events"]),
            "edited_improver_search_executions": sum(
                e["kind"] == "improvement_plan_executed" and e["data"]["edited_improver"]
                for e in verified["events"]),
            "failed_proposals": sum(e["kind"] == "proposal_failed" for e in verified["events"]),
            "final_chain_head": audit(root / "final" / item["name"])["chain_head"],
        }
        rows.append(row)
        archive.put("arm_result", row)
        if progress:
            progress({"phase": "final_completed", "name": item["name"],
                      "correct": row["final"]["correct"], "cases": row["final"]["case_count"]})
    differences = [
        next(r["final"]["correct"] for r in rows if r["block"] == b and r["arm"] == "evolving_history")
        - next(r["final"]["correct"] for r in rows if r["block"] == b and r["arm"] == "frozen_history")
        for b in range(1, 4)
    ]
    summary = {
        "schema": "rsi-engine.pilot-result.v1", "protocol_id": record["id"],
        "kernel_id": record["content"]["kernel_id"], "pack_id": pack.id,
        "provenance": "live_model", "model_id": record["content"]["model"]["model_id"],
        "seed_final": {k: v for k, v in seed_report.items() if k != "results"},
        "rows": rows, "paired_correct_count_differences": differences,
        "mean_paired_percentage_point_difference": sum(differences) / (3 * len(test)) * 100,
        "unique_test_cases": 56, "unique_test_families": 28, "paired_blocks": 3,
        "cost": barrier["content"]["cost"],
        "recursive_benefit_established": False,
        "limitations": record["content"]["limitations"] + pack.manifest["limitations"],
    }
    artifact = archive.put("study_summary", summary)
    archive.event("study_completed", {"origin": origin, "seed_report": seed_artifact, "summary": artifact})
    write_new(root / "summary.json", canonical(summary) + b"\n")
    return summary
