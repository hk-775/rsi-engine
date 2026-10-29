"""AutoHelix iteration orchestration with an RSI proposal/evaluation bridge.

Upstream owns worktrees, constraint execution, metric gates, history and merges.
The bridge owns model access and isolated evaluation. No upstream coding-agent
CLI or candidate module is executed on the host.
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import hashlib
from importlib.metadata import PackageNotFoundError, version
import io
import os
from pathlib import Path
import shlex
import subprocess
import sys

from .archive import write_new
from .contracts import BackendError, Candidate, EngineError, canonical, digest
from .iterations import eligible

PIN = "0.1.0"


def identity():
    try:
        installed = version("autohelix")
        import autohelix
    except (PackageNotFoundError, ImportError) as exc:
        raise EngineError("Install AutoHelix with uv sync --locked --extra autohelix") from exc
    if installed != PIN:
        raise EngineError(f"AutoHelix {PIN} is required; found {installed}")
    root = Path(autohelix.__file__).parent
    files = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    return {"name": "autohelix", "version": PIN, "package_digest": digest(files),
            "agent_bridge": "rsi-proposal-v1", "checks": "external-receipt-v1"}


def read_candidate(root):
    from .helix_check import read_regular
    return Candidate(*(read_regular(root / (name + ".py"), 32_000).decode()
                       for name in ("task", "improver")))


def write_candidate(root, candidate):
    for name in ("task", "improver"):
        (root / (name + ".py")).write_text(getattr(candidate, name))


class AutoHelixIterations:
    def __init__(self, archive, seed, baseline, budget):
        from autohelix.agents import AgentRunResult
        from autohelix.harness import Harness
        from autohelix.history import IterationResult
        from autohelix.sandbox import Sandbox
        from rich.console import Console

        self.identity = identity()
        self.archive, self.budget = archive, budget
        self.root = (archive.root / "autohelix").resolve()
        self.project = self.root / "workspace"
        self.control = self.root / "control"
        self.project.mkdir(parents=True, mode=0o700)
        self.control.mkdir(mode=0o700)
        self._produce = None
        self._change = None
        self._error = None
        self._calls = 0
        self._receipt_id = None
        self._iteration = None
        self._next = 0
        owner = self

        # Generated source remains inert data in this private scratch repository.
        write_candidate(self.project, seed)
        write_new(self.project / ".gitignore", b".autohelix/\n")
        script = Path(__file__).with_name("helix_check.py").resolve()
        command = ["/usr/bin/env", "-i", sys.executable, "-I", "-S",
                   str(script), "--control", str(self.control)]
        self.config = {
            "goal": "Improve authorized workflow outcomes using isolated evaluator receipts.",
            "scope": {"editable": ["task.py", "improver.py"]},
            # Upstream constructs an inert mock object, replaced before any iteration.
            "agent": {"type": "mock"},
            "constraints": [{"command": shlex.join(command + ["check"]), "timeout": 10}],
            "metrics": [{"command": shlex.join(command + ["metrics"]), "timeout": 10,
                         "values": {"correct": "higher", "tool_calls": "lower"}}],
            "acceptance": {"metric_gates": [{"metric": "correct", "max_regression_pct": 0}]},
            "budget": {"iterations": budget.limits.proposals},
        }
        write_new(self.project / "autohelix.yaml", canonical(self.config) + b"\n")
        self._git("init", "-q", "--initial-branch=main", checked=True)
        for key, value in (("user.name", "RSI Engine"), ("user.email", "rsi-engine@example.invalid"),
                           ("core.hooksPath", "/dev/null"), ("commit.gpgsign", "false")):
            self._git("config", key, value, checked=True)
        self._git("add", ".", checked=True)
        self._git("commit", "-q", "-m", "Initialize isolated RSI candidate workspace", checked=True)

        class ScopedSandbox(Sandbox):
            def _run_git(self, *args, cwd=None):
                return owner._git(*args, cwd=cwd or self.project_path)

        class ProposalBridge:
            display_name = "RSI proposal generator"

            def run(self, worktree_path, prompt, iteration, log_path, event_callback, project_path=None):
                return owner._generate(worktree_path, iteration, log_path, AgentRunResult)

        self.harness = Harness(self.project)
        self.harness.console = Console(file=io.StringIO(), force_terminal=False)
        self.harness.sandbox = ScopedSandbox(self.project)
        self.bridge = ProposalBridge()
        self.harness.agent = self.bridge
        self.harness.history.append(IterationResult(
            iteration=0, accepted=True, metrics=self.metrics(baseline),
            usage={"cost_known": True, "cost_usd": 0.0},
        ))
        config_id = archive.put("autohelix_config", {
            "config": self.config, "identity": self.identity,
            "notice": "The configured mock object is replaced by the RSI proposal bridge. "
                      "Run through rsi-engine; standalone autohelix CLI is not this integration.",
        })
        archive.event("autohelix_initialized", {"config": config_id,
                                              "seed_commit": self._git("rev-parse", "HEAD", checked=True).stdout.strip()})

    def _git(self, *args, cwd=None, checked=False):
        # Prevent inherited GIT_DIR/index/config from redirecting scratch operations
        # into the user's repository. No user hooks or credentials are needed here.
        env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_TERMINAL_PROMPT="0")
        try:
            result = subprocess.run(
                ["git", *args], cwd=cwd or self.project, env=env,
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendError("AutoHelix scratch Git operation failed") from exc
        if checked and result.returncode:
            raise BackendError("AutoHelix scratch Git operation was rejected")
        return result

    @staticmethod
    def metrics(report):
        return {key: report[key] for key in ("correct", "tool_calls")}

    def context(self):
        # Propagate upstream history and persistent notes, never local paths or
        # command strings from AutoHelix's rendered operator prompt.
        history = [
            {"iteration": item.iteration, "accepted": item.accepted, "metrics": item.metrics}
            for item in self.harness.history.get_recent(5)
        ]
        note = self.project / ".autohelix" / "notes" / "latest.json"
        from .contracts import decode
        notes = decode(note.read_bytes(), 8000) if note.is_file() and not note.is_symlink() else None
        return {"name": "autohelix", "version": PIN, "history": history, "notes": notes}

    def _receipt(self, worktree, candidate, allowed, report):
        content = {
            "schema": 1, "worktree": str(worktree.resolve()), "allowed": allowed,
            "candidate_id": candidate.id,
            "source_hashes": {
                name: hashlib.sha256(getattr(candidate, name).encode()).hexdigest()
                for name in ("task", "improver")
            },
            "metrics": self.metrics(report),
        }
        destination = self.control / f"iter-{self._iteration}.json"
        write_new(destination, canonical(content) + b"\n", 0o400)
        self._receipt_id = self.archive.put("autohelix_evaluation_receipt", content)

    def _generate(self, worktree, iteration, log_path, result_type):
        self._calls += 1
        if self._calls != 1 or iteration != self._iteration or read_candidate(worktree) != self._parent:
            raise BackendError("AutoHelix invoked an unexpected proposal or parent")
        usages_before = len(self.budget.usages)
        try:
            self._change = self._produce(self.context())
            if self._change:
                write_candidate(worktree, self._change.candidate)
                notes = worktree / ".autohelix" / "notes" / "latest.json"
                notes.write_bytes(canonical({
                    "iteration": iteration, "target": self._change.target,
                    "hypothesis": self._change.hypothesis,
                    "development_correct": self._change.report["correct"],
                }) + b"\n")
        except Exception as exc:
            # Upstream catches ordinary exceptions. Keep the original so budget
            # and engine failures can be re-raised after worktree cleanup.
            self._error = exc
        change = self._change
        candidate = change.candidate if change else self._parent
        self._receipt(worktree, candidate, bool(change and eligible(change.report)),
                      change.report if change else self._parent_report)
        recent = self.budget.usages[usages_before:]
        usage = recent[-1] if recent else (change.usage if change else None)
        provider_usage = {"cost_known": bool(usage and usage.estimated_usd is not None),
                          "rsi_usage": asdict(usage) if usage else None}
        if usage:
            for key in ("input_tokens", "output_tokens"):
                if getattr(usage, key) is not None:
                    provider_usage[key] = getattr(usage, key)
            if usage.estimated_usd is not None:
                # Upstream uses floats for display only. RSI's Decimal ledger is authoritative.
                provider_usage["cost_usd"] = float(Decimal(usage.estimated_usd))
        log_path.write_text("Proposal and isolated evaluation are recorded in the RSI evidence archive.\n")
        return result_type(success=self._error is None and change is not None,
                           exit_code=0 if change and self._error is None else 1, usage=provider_usage)

    def run(self, iteration, parent, parent_report, produce):
        self.budget.remaining()
        if iteration != self._next or read_candidate(self.project) != parent:
            raise BackendError("AutoHelix iteration state does not match the research controller")
        if self.harness.agent is not self.bridge:
            raise BackendError("AutoHelix proposal bridge was replaced")
        self._next += 1
        self._iteration = iteration + 1  # AutoHelix numbers its baseline as zero.
        self._parent, self._parent_report, self._produce = parent, parent_report, produce
        self._change, self._error, self._receipt_id, self._calls = None, None, None, 0
        try:
            result = self.harness.run_iteration(self._iteration)
        except Exception as exc:
            raise BackendError("AutoHelix could not complete an isolated iteration") from exc
        artifact = self.archive.put("autohelix_iteration_result", asdict(result))
        self.archive.event("autohelix_iteration_completed", {
            "iteration": iteration, "artifact": artifact, "receipt": self._receipt_id,
        })
        if self._calls != 1 or self._receipt_id is None:
            raise BackendError("AutoHelix iteration has no verified proposal/evaluation receipt")
        if self._error is not None:
            raise self._error
        expected = bool(self._change and eligible(self._change.report)
                        and self._change.report["correct"] >= parent_report["correct"])
        if result.accepted != expected:
            raise BackendError("AutoHelix acceptance disagrees with the recorded evaluation gate")
        expected_candidate = self._change.candidate if expected else parent
        if read_candidate(self.project) != expected_candidate:
            raise BackendError("AutoHelix committed a candidate inconsistent with its decision")
        self.budget.remaining()
        return self._change, result.accepted
