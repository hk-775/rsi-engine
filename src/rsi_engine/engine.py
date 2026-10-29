"""Search, selection and final evaluation with separate data access."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
from pathlib import Path
import time

from . import __version__
from .archive import Archive, audit
from .budget import Budget, Limits
from .contracts import BackendError, Candidate, EngineError, Generated, Usage, digest, exact, text
from .iterations import EvaluatedChange, NativeIterations, describe_backend, eligible
from .workload import Pack, disjoint
from .policy import SearchPolicy, compact_report


def kernel_identity():
    root = Path(__file__).parent
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.py"))})


def plan(candidate, context, runner, budget):
    with runner.open(candidate.improver, "plan") as session:
        value = session.call(context, timeout=budget.remaining())
    exact(value, {"target", "instruction"}, "improver plan")
    if not isinstance(value["target"], str) or value["target"] not in {"task", "improver"}:
        raise EngineError("Improver can request only task or improver edits")
    text(value["instruction"], "improver instruction", 4000)
    return value


def search(pack: Pack, generator, runner, workload, out: Path, limits: Limits | None = None,
           policy: SearchPolicy | None = None, backend: str = "native"):
    if workload.identity.get("adapter") != pack.manifest["adapter"]:
        raise EngineError("Workload adapter does not match the pack")
    budget = Budget(limits or Limits())
    policy = policy or SearchPolicy()
    backend_identity = describe_backend(backend)
    if backend == "autohelix":
        from .helix import AutoHelixIterations
    archive = Archive(out)
    manifest = {
        "schema_version": 1, "engine_version": __version__, "kernel_id": kernel_identity(),
        "pack_id": pack.id, "pack": pack.manifest,
        "generator": {"identity": generator.identity, "provenance": generator.provenance},
        "generator_settings": getattr(generator, "settings", None),
        "search_policy": asdict(policy),
        "iteration_backend": backend_identity,
        "runner": runner.identity, "workload": workload.identity,
        "limits": asdict(budget.limits),
        "selection_rule": "eligible maximum validation correctness, then fewer tool calls, then earliest revision",
        "research_status": "engineering prototype; no demonstrated recursive advantage",
    }
    manifest_artifact = archive.put("manifest", manifest)
    archive.event("run_started", {"manifest": manifest_artifact})
    try:
        development = pack.cases("development")
        active = pack.seed
        active_artifact = archive.put("candidate", asdict(active))
        initial_report = workload.evaluate(active, development, runner, budget)
        initial_report_artifact = archive.put("development_report", initial_report)
        archive.event("baseline_evaluated", {"candidate_id": active.id, "report": initial_report_artifact})
        candidates = [(active, active_artifact)]
        seen = {active.id}
        active_report = initial_report
        history = []
        iterations = (AutoHelixIterations(archive, active, initial_report, budget)
                      if backend == "autohelix" else NativeIterations())
        for iteration in range(budget.limits.proposals):
            feedback = compact_report(active_report) if policy.compact else active_report
            requested_target = policy.target(iteration)
            context = {"iteration": iteration, "development": feedback, "contract": workload.contract}
            if policy.history:
                context["history"] = list(history)
            if requested_target:
                context["requested_target"] = requested_target
            def produce(optimizer):
                if optimizer is not None:
                    context["optimizer"] = optimizer
                instruction = plan(active, context, runner, budget)
                if requested_target and instruction["target"] != requested_target:
                    raise EngineError("Improver plan violates the registered edit schedule")
                archive.event("improvement_plan_executed", {
                    "iteration": iteration, "candidate_id": active.id, "plan": instruction,
                    "edited_improver": active.improver != pack.seed.improver,
                })
                request = {
                    "schema_version": 1, "iteration": iteration,
                    "parent_id": active.id, "candidate": asdict(active),
                    "plan": instruction, "development": feedback,
                    "contract": workload.contract,
                    "allowed_targets": ["task", "improver"],
                    "response_contract": {
                        "proposal": {"target": "task or improver", "source": "complete Python module",
                                     "hypothesis": "explanation"},
                        "usage": {"input_tokens": "integer or null", "output_tokens": "integer or null",
                                  "estimated_usd": "Decimal string or null"},
                    },
                }
                if policy.history:
                    request["history"] = list(history)
                if optimizer is not None:
                    request["optimizer"] = optimizer
                request_artifact = archive.put("generation_request", request)
                budget.reserve_proposal()
                started = time.monotonic()
                try:
                    raw = generator.generate(request, timeout=budget.remaining())
                finally:
                    evidence = getattr(generator, "last_call", None)
                    if evidence is not None:
                        evidence_id = archive.put("provider_call", evidence)
                        archive.event("provider_call_recorded", {"iteration": iteration, "artifact": evidence_id})
                response_artifact = archive.put("generation_response", raw)
                archive.event("generator_returned", {
                    "iteration": iteration, "request": request_artifact,
                    "response": response_artifact, "wall_seconds": round(time.monotonic() - started, 6),
                })
                # Preserve reported usage even if the proposal's source is invalid.
                exact(raw, {"proposal", "usage"}, "generator response")
                usage = Usage(**exact(raw["usage"], {"input_tokens", "output_tokens", "estimated_usd"}, "usage"))
                budget.usages.append(usage)
                generated = Generated.parse(raw)
                if generated.proposal.target != instruction["target"]:
                    raise EngineError("Generator changed a module the improver did not request")
                child = generated.proposal.apply(active)
                child_artifact = archive.put("candidate", asdict(child))
                archive.event("candidate_proposed", {
                    "candidate_id": child.id, "parent_id": active.id,
                    "candidate": child_artifact, "response": response_artifact,
                    "target": generated.proposal.target,
                })
                if child.id in seen:
                    archive.event("duplicate_candidate", {"candidate_id": child.id})
                    history.append({"iteration": iteration, "target": generated.proposal.target,
                                    "hypothesis": generated.proposal.hypothesis, "decision": "duplicate"})
                    return None
                seen.add(child.id)
                # An edited improver must actually execute and produce a valid plan.
                if generated.proposal.target == "improver":
                    probe_context = {**context, "iteration": iteration + 1}
                    if requested_target:
                        probe_context["requested_target"] = policy.target(iteration + 1)
                    probe = plan(child, probe_context, runner, budget)
                    if requested_target and probe["target"] != probe_context["requested_target"]:
                        raise EngineError("Edited improver violates the next scheduled target")
                    archive.event("improver_executed", {"candidate_id": child.id, "plan": probe})
                report = workload.evaluate(child, development, runner, budget)
                report_artifact = archive.put("development_report", report)
                candidates.append((child, child_artifact))
                return EvaluatedChange(child, report, generated.proposal.target,
                                       generated.proposal.hypothesis, usage, report_artifact)

            try:
                change, retained = iterations.run(iteration, active, active_report, produce)
                if change is None:
                    continue
                child, report = change.candidate, change.report
                archive.event("development_decision", {
                    "candidate_id": child.id, "report": change.report_artifact,
                    "decision": "retain_for_exploration" if retained else "reject_as_parent",
                    "recursive_benefit_established": False,
                })
                history.append({"iteration": iteration, "target": change.target,
                                "hypothesis": change.hypothesis,
                                "correct": report["correct"], "case_count": report["case_count"],
                                "decision": "retain_for_exploration" if retained else "reject_as_parent"})
                if retained:
                    active, active_report = child, report
            except EngineError as exc:
                from .contracts import BudgetExceeded
                if isinstance(exc, (BudgetExceeded, BackendError)):
                    raise
                archive.event("proposal_failed", {"iteration": iteration, "reason": str(exc)})
                history.append({"iteration": iteration, "decision": "failed", "reason": str(exc)})

        # Validation feedback is never provided to the generator or improver.
        validation = pack.cases("validation")
        disjoint(development, validation)
        choices = []
        for index, (candidate, candidate_artifact) in enumerate(candidates):
            report = workload.evaluate(candidate, validation, runner, budget)
            report_artifact = archive.put("validation_report", report)
            archive.event("validation_evaluated", {"candidate_id": candidate.id, "report": report_artifact})
            if eligible(report):
                choices.append((report["correct"], -report["tool_calls"], -index,
                                candidate, candidate_artifact, report, report_artifact))
        if not choices:
            raise EngineError("No candidate meets the execution-correctness selection gate")
        chosen = max(choices, key=lambda item: item[:3])
        selection = {
            "schema_version": 1, "manifest": manifest_artifact,
            "candidate_id": chosen[3].id, "candidate": chosen[4],
            "validation_report": chosen[6],
            "baseline_development_report": initial_report_artifact,
            "summary": {k: v for k, v in chosen[5].items() if k != "results"},
            "budget": budget.snapshot(),
            "provenance": generator.provenance,
            "iteration_backend": backend_identity,
            "final_test_used": False,
            "recursive_benefit_established": False,
        }
        return archive.select(selection)
    except BaseException as exc:
        archive.event("run_aborted", {"error_type": type(exc).__name__, "budget": budget.snapshot()})
        raise


def selected(root: Path):
    verified = audit(root, require_selection=True)
    selection = verified["selection"]
    objects = verified["objects"]
    try:
        candidate = Candidate.parse(objects[selection["candidate"]]["content"])
        manifest = objects[selection["manifest"]]["content"]
        if candidate.id != selection["candidate_id"]:
            raise EngineError("Selected candidate identity mismatch")
        report = objects[selection["validation_report"]]["content"]
        if report["candidate_id"] != candidate.id:
            raise EngineError("Selection report refers to another candidate")
    except (KeyError, TypeError) as exc:
        raise EngineError("Selection references invalid artifacts") from exc
    return candidate, manifest, verified


def evaluate_final(run: Path, pack: Pack, runner, workload, out: Path, limits: Limits | None = None):
    candidate, manifest, verified = selected(run)
    if pack.id != manifest["pack_id"] or kernel_identity() != manifest["kernel_id"]:
        raise EngineError("Pack or engine changed since selection; start a new run")
    if runner.identity != manifest["runner"] or workload.identity != manifest["workload"]:
        raise EngineError("Runner or workload changed since selection")
    # Test cases are parsed only after a valid committed selection has been verified.
    development, validation, test = (pack.cases(s) for s in ("development", "validation", "test"))
    disjoint(development, validation, test)
    budget = Budget(limits or Limits())
    archive = Archive(out)
    origin = archive.put("final_origin", {
        "selection_chain_head": verified["chain_head"], "selection": verified["selection"],
        "manifest": manifest, "pack_id": pack.id,
    })
    try:
        report = workload.evaluate(candidate, test, runner, budget)
        content = {
            "schema_version": 1, "candidate_id": candidate.id, "split": "test",
            "report": report, "budget": budget.snapshot(),
            "provenance": manifest["generator"]["provenance"],
            "iteration_backend": manifest.get("iteration_backend", NativeIterations.identity),
            "recursive_benefit_established": False,
            "limitations": pack.manifest["limitations"],
        }
        artifact = archive.put("final_report", content)
        archive.event("final_evaluation_completed", {"origin": origin, "report": artifact})
        return content
    except BaseException as exc:
        archive.event("run_aborted", {"error_type": type(exc).__name__, "budget": budget.snapshot()})
        raise


def export_evidence(run: Path):
    _, manifest, verified = selected(run)
    return {
        "format": "rsi-engine.evidence.v1", "engine_version": __version__,
        "integration_status": "standalone_export",
        "manifest": manifest, "selection": verified["selection"],
        "events": verified["events"], "artifacts": verified["objects"],
        "chain_head": verified["chain_head"],
        "notice": "Hashes establish internal consistency, not source authenticity. "
                  "This export does not activate a deployment or register a Workbench integration.",
    }
