"""Replay published policies in Docker, without calling a model provider."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re

from rsi_engine.archive import Archive, write_new
from rsi_engine.budget import Budget
from rsi_engine.contracts import Candidate, EngineError, canonical, decode, digest
from rsi_engine.engine import kernel_identity
from rsi_engine.reward import RewardWorkload, open_pack
from rsi_engine.reward_study import FINAL_LIMITS, audit_report
from rsi_engine.sandbox import DockerRunner

SEMANTIC_METRICS = (
    "case_count", "verified_correct", "verified_completed", "correct_handoff",
    "false_completion", "valid_documents", "required_documents", "duplicate_artifacts",
    "unexpected_artifacts", "unauthorized_writes", "reported_success", "handoff_requested",
    "candidate_error", "tool_calls", "status_edits", "proxy_false_positives", "proxy_false_negatives",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, type=Path)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--run", action="append", help="Replay a named run; omit to replay all twelve")
    parser.add_argument("--image", default="python:3.12-slim")
    args = parser.parse_args()
    if args.record.is_symlink() or not args.record.is_file() or args.record.stat().st_size > 16_000_000:
        raise EngineError("Publication record must be a bounded regular JSON file")
    record = decode(args.record.read_bytes(), 16_000_000)
    if record["schema"] != "rsi-engine.reward-publication.v1":
        raise EngineError("Not a reward-study publication record")
    protocol = record["protocol"]
    if (digest(protocol["content"]) != protocol["id"]
            or protocol["id"] != record["summary"]["protocol_id"]
            or protocol["content"]["kernel_id"] != kernel_identity()
            or protocol["content"]["final_limits"] != asdict(FINAL_LIMITS)):
        raise EngineError("Protocol or evaluator differs from the published experiment")
    pack = open_pack(args.pack)
    if pack.id != protocol["content"]["pack_id"]:
        raise EngineError("The replay corpus differs from the published experiment")
    policies = record["selected_policies"]
    names = args.run or list(policies)
    if len(names) != len(set(names)):
        raise EngineError("Duplicate replay names")
    for name in names:
        if (name not in policies or
                not re.fullmatch(r"block-[123]-(reported|verified)_(frozen|evolving)_history", name)):
            raise EngineError("Unknown or invalid published run")
        candidate = Candidate.parse(policies[name]["candidate"])
        if candidate.id != policies[name]["candidate_id"]:
            raise EngineError("Published candidate hash mismatch")
    runner = DockerRunner(args.image)
    archive = Archive(args.out)
    origin = archive.put("replay_origin", {
        "protocol_id": protocol["id"], "source_commit": record["source_commit"],
        "kernel_id": kernel_identity(), "pack_id": pack.id, "runner": runner.identity,
        "same_runtime_identity": runner.identity == protocol["content"]["runner"],
        "provenance": "replay_of_published_live_model_policies", "model_calls": 0,
    })
    cases = pack.cases("test")
    outcomes = []
    for name in names:
        policy = policies[name]
        candidate = Candidate.parse(policy["candidate"])
        report = RewardWorkload(policy["objective"]).evaluate(candidate, cases, runner, Budget(FINAL_LIMITS))
        actual = audit_report(report, cases)
        expected = policy["expected_audit"]
        differences = {key: {"expected": expected[key], "actual": actual[key]}
                       for key in SEMANTIC_METRICS if actual[key] != expected[key]}
        expected_rows = record["case_audits"][name]
        comparable = lambda rows: [{k: v for k, v in row.items() if k != "case_wall_seconds"} for row in rows]
        if comparable(actual["rows"]) != comparable(expected_rows):
            differences["per_case_outcomes"] = "One or more case outcomes differ"
        artifact = archive.put("replay_report", {
            "name": name, "candidate_id": candidate.id, "report": report,
            "audit": actual, "differences": differences,
        })
        archive.event("replay_compared", {"name": name, "artifact": artifact, "matches": not differences})
        outcome = {"name": name, "matches": not differences, "verified_correct": actual["verified_correct"],
                   "proxy_false_positives": actual["proxy_false_positives"], "differences": differences}
        outcomes.append(outcome)
        print(json.dumps(outcome), flush=True)
    result = {"origin": origin, "model_calls": 0, "all_match": all(o["matches"] for o in outcomes),
              "runs": outcomes}
    archive.event("replay_completed", result)
    write_new(args.out / "summary.json", canonical(result) + b"\n")
    return 0 if result["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
