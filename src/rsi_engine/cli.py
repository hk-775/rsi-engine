from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .archive import audit, write_new
from .budget import Limits
from .contracts import EngineError, canonical
from .engine import evaluate_final, export_evidence, search
from .examples import ScriptedGenerator, write_pack
from .generators import CommandGenerator
from .sandbox import DockerRunner
from .workload import Pack, StatefulWorkload


def parser():
    result = argparse.ArgumentParser(prog="rsi-engine", description="Standalone agent and improver code evolution")
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a synthetic workload pack")
    init.add_argument("directory", type=Path)
    init.add_argument("--domain", choices=["subscription", "ai_job"], default="subscription")
    doctor = commands.add_parser("doctor", help="Check the candidate execution environment")
    doctor.add_argument("--image", default="python:3.12-slim")
    for name in ("demo", "run", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--pack", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True)
        command.add_argument("--image", default="python:3.12-slim")
        command.add_argument("--iterations", type=int, default=3)
        command.add_argument("--max-case-evaluations", type=int, default=120)
        command.add_argument("--max-wall-seconds", type=int, default=600)
        command.add_argument("--max-steps", type=int, default=12)
        if name == "run":
            command.add_argument("--generator-config", type=Path, required=True)
        if name == "evaluate":
            command.add_argument("--run", type=Path, required=True)
    check = commands.add_parser("audit", help="Verify records, artifact digests and selection")
    check.add_argument("run", type=Path)
    export = commands.add_parser("export", help="Write portable evidence for future adapters")
    export.add_argument("run", type=Path)
    export.add_argument("--out", type=Path, required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            destination = write_pack(args.directory, args.domain)
            print(f"Created synthetic workload pack: {destination}")
            return 0
        if args.command == "audit":
            checked = audit(args.run)
            print(json.dumps({"verified_events": len(checked["events"]),
                              "verified_artifacts": len(checked["objects"]),
                              "selection_committed": checked["selection"] is not None}, indent=2))
            return 0
        if args.command == "export":
            write_new(args.out, canonical(export_evidence(args.run)) + b"\n")
            print(f"Exported standalone evidence: {args.out}")
            return 0
        runner = DockerRunner(args.image)
        if args.command == "doctor":
            with runner.open('def decide(context):\n    return {"ready": True}\n', "decide") as session:
                if session.call({}) != {"ready": True}:
                    raise EngineError("Candidate runner failed its readiness check")
            print(json.dumps(runner.identity, indent=2))
            return 0
        pack = Pack(args.pack)
        workload = StatefulWorkload()
        limits = Limits(args.iterations, args.max_case_evaluations, args.max_wall_seconds, args.max_steps)
        if args.command == "evaluate":
            result = evaluate_final(args.run, pack, runner, workload, args.out, limits)
            report = result["report"]
            split = "test"
        else:
            generator = ScriptedGenerator() if args.command == "demo" else CommandGenerator.from_file(args.generator_config)
            result = search(pack, generator, runner, workload, args.out, limits)
            report = result["summary"]
            split = "validation"
        print(json.dumps({
            "split": split, "provenance": result["provenance"],
            "correct": report["correct"], "cases": report["case_count"],
            "completed": report["completed"], "correct_handoff": report["correct_handoff"],
            "unresolved": report["unresolved"], "false_completions": report["false_completions"],
            "candidate_id": result["candidate_id"], "budget": result["budget"],
            "recursive_benefit_established": False, "output": str(args.out),
        }, indent=2))
        return 0
    except (EngineError, OSError, KeyError, TypeError) as exc:
        print(f"rsi-engine: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
