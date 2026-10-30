from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .archive import audit, write_new
from .budget import Limits
from .contracts import EngineError, canonical, decode
from .engine import evaluate_final, export_evidence, search
from .examples import ScriptedGenerator, write_pack
from .generators import CommandGenerator
from .sandbox import DockerRunner
from .workload import Pack, StatefulWorkload


def load_workload(path):
    manifest = decode((path / "manifest.json").read_bytes())
    if manifest.get("adapter") == "composed-operation-v1":
        from .composed import ComposedWorkload, open_pack
        return open_pack(path), ComposedWorkload()
    return Pack(path), StatefulWorkload()


def parser():
    result = argparse.ArgumentParser(prog="rsi-engine", description="Standalone agent and improver code evolution")
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a synthetic workload pack")
    init.add_argument("directory", type=Path)
    init.add_argument("--domain", choices=["subscription", "ai_job", "composed", "reward"], default="subscription")
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
        if name != "evaluate":
            command.add_argument("--backend", choices=["native", "autohelix"], default="native",
                                 help="Iteration backend; AutoHelix uses the RSI generator/evaluator bridge")
        if name == "run":
            source = command.add_mutually_exclusive_group(required=True)
            source.add_argument("--generator-config", type=Path)
            source.add_argument("--bedrock-config", type=Path)
            command.add_argument("--policy", choices=["prototype", "frozen_history", "evolving_history"],
                                 default="prototype")
        if name == "evaluate":
            command.add_argument("--run", type=Path, required=True)
    check = commands.add_parser("audit", help="Verify records, artifact digests and selection")
    check.add_argument("run", type=Path)
    export = commands.add_parser("export", help="Write portable evidence for future adapters")
    export.add_argument("run", type=Path)
    export.add_argument("--out", type=Path, required=True)
    for name in ("study-prepare", "study-run", "study-evaluate"):
        command = commands.add_parser(name, help="Register, run or evaluate the bounded live-model pilot")
        command.add_argument("--pack", type=Path, required=True)
        command.add_argument("--study", type=Path, required=True)
        command.add_argument("--image", default="python:3.12-slim")
        if name == "study-prepare":
            command.add_argument("--bedrock-config", type=Path, required=True)
            command.add_argument("--max-estimated-usd", default="3.00")
            command.add_argument("--backend", choices=["native", "autohelix"], default="native")
    for name in ("reward-prepare", "reward-run", "reward-evaluate"):
        command = commands.add_parser(name, help="Register, run or audit the AutoHelix reward-integrity study")
        command.add_argument("--pack", type=Path, required=True)
        command.add_argument("--study", type=Path, required=True)
        command.add_argument("--image", default="python:3.12-slim")
        if name == "reward-prepare":
            command.add_argument("--bedrock-config", type=Path, required=True)
            command.add_argument("--max-estimated-usd", default="3.00")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            if args.domain == "reward":
                from .reward import write_pack as write_reward
                destination = write_reward(args.directory)
            elif args.domain == "composed":
                from .composed import write_pack as write_composed
                destination = write_composed(args.directory)
            else:
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
        if args.command.startswith("reward-"):
            from .bedrock import BedrockConfig
            from .reward import open_pack
            from .reward_study import evaluate_study, prepare, run_study
            pack = open_pack(args.pack)
            progress = lambda value: print(json.dumps(value), flush=True)
            if args.command == "reward-prepare":
                config = BedrockConfig(**decode(args.bedrock_config.read_bytes()))
                result = prepare(args.study, pack, runner, config, args.max_estimated_usd)
                progress({"protocol_id": result["id"], "study": str(args.study)})
            elif args.command == "reward-run":
                result = run_study(args.study, pack, runner, progress=progress)
                progress({"selections_committed": len(result["content"]["selections"])})
            else:
                result = evaluate_study(args.study, pack, runner, progress=progress)
                progress({"summary": str(args.study / "summary.json"), "cost": result["cost"],
                          "recursive_benefit_established": False})
            return 0
        pack, workload = load_workload(args.pack)
        if args.command.startswith("study-"):
            from .bedrock import BedrockConfig
            from .study import evaluate_study, prepare, run_study
            progress = lambda value: print(json.dumps(value), flush=True)
            if args.command == "study-prepare":
                config = BedrockConfig(**decode(args.bedrock_config.read_bytes()))
                result = prepare(args.study, pack, runner, config, args.max_estimated_usd, args.backend)
                progress({"protocol_id": result["id"], "study": str(args.study)})
            elif args.command == "study-run":
                result = run_study(args.study, pack, runner, progress=progress)
                progress({"selections_committed": len(result["content"]["selections"])})
            else:
                result = evaluate_study(args.study, pack, runner, progress=progress)
                progress({"summary": str(args.study / "summary.json"),
                          "paired_correct_count_differences": result["paired_correct_count_differences"],
                          "cost": result["cost"], "recursive_benefit_established": False})
            return 0
        limits = Limits(args.iterations, args.max_case_evaluations, args.max_wall_seconds, args.max_steps)
        if args.command == "evaluate":
            result = evaluate_final(args.run, pack, runner, workload, args.out, limits)
            report = result["report"]
            split = "test"
        else:
            from .policy import SearchPolicy
            policy = SearchPolicy()
            if args.command == "demo":
                if pack.manifest["adapter"] == "composed-operation-v1":
                    raise EngineError("The scripted demo is only for the original single-operation packs")
                generator = ScriptedGenerator()
            else:
                if args.bedrock_config:
                    from .bedrock import BedrockConfig, BedrockGenerator
                    generator = BedrockGenerator(BedrockConfig(**decode(args.bedrock_config.read_bytes())))
                else:
                    generator = CommandGenerator.from_file(args.generator_config)
                if args.policy != "prototype":
                    from .study import ARMS
                    policy = ARMS[args.policy]
                elif pack.manifest["adapter"] == "composed-operation-v1":
                    raise EngineError("Composed packs require a frozen_history or evolving_history policy")
            result = search(pack, generator, runner, workload, args.out, limits, policy, args.backend)
            report = result["summary"]
            split = "validation"
        print(json.dumps({
            "split": split, "provenance": result["provenance"],
            "correct": report["correct"], "cases": report["case_count"],
            "completed": report["completed"], "correct_handoff": report["correct_handoff"],
            "unresolved": report["unresolved"], "false_completions": report["false_completions"],
            "candidate_id": result["candidate_id"], "budget": result["budget"],
            "iteration_backend": result.get("iteration_backend"),
            "recursive_benefit_established": False, "output": str(args.out),
        }, indent=2))
        return 0
    except (EngineError, OSError, KeyError, TypeError) as exc:
        print(f"rsi-engine: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
