"""Data-only contracts. Parsing source here never executes it."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Protocol

MAX_SOURCE_BYTES = 32_000
MAX_JSON_BYTES = 256_000


class EngineError(ValueError):
    pass


class BudgetExceeded(EngineError):
    pass


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as exc:
        raise EngineError("Expected finite JSON data") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def decode(raw: bytes | str, limit: int = MAX_JSON_BYTES) -> Any:
    if len(raw if isinstance(raw, bytes) else raw.encode()) > limit:
        raise EngineError("JSON size limit exceeded")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise EngineError("Duplicate JSON object key")
            result[key] = value
        return result

    def constant(_):
        raise EngineError("Non-finite JSON value")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        canonical(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise EngineError("Invalid JSON data") from exc


def exact(value: Any, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise EngineError(f"{label} requires exactly: {', '.join(sorted(keys))}")
    return value


def text(value: Any, label: str, limit: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > limit:
        raise EngineError(f"Invalid {label}")
    return value


def positive(value: Any, label: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise EngineError(f"{label} must be an integer between 1 and {maximum}")
    return value


def source(value: Any, function: str) -> str:
    text(value, "source", MAX_SOURCE_BYTES)
    try:
        tree = ast.parse(value)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise EngineError("Candidate source is not valid Python") from exc
    if not any(isinstance(n, ast.FunctionDef) and n.name == function for n in tree.body):
        raise EngineError(f"Candidate must define {function}(context)")
    return value


@dataclass(frozen=True)
class Candidate:
    task: str
    improver: str

    def __post_init__(self):
        source(self.task, "decide")
        source(self.improver, "plan")

    @property
    def id(self) -> str:
        return digest(asdict(self))

    @classmethod
    def parse(cls, value: Any) -> Candidate:
        return cls(**exact(value, {"task", "improver"}, "candidate"))


@dataclass(frozen=True)
class Proposal:
    target: str
    source: str
    hypothesis: str

    def __post_init__(self):
        if not isinstance(self.target, str) or self.target not in {"task", "improver"}:
            raise EngineError("Only task and improver modules can be changed")
        source(self.source, "decide" if self.target == "task" else "plan")
        text(self.hypothesis, "hypothesis")

    def apply(self, parent: Candidate) -> Candidate:
        return Candidate(
            self.source if self.target == "task" else parent.task,
            self.source if self.target == "improver" else parent.improver,
        )

    @classmethod
    def parse(cls, value: Any) -> Proposal:
        return cls(**exact(value, {"target", "source", "hypothesis"}, "proposal"))


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_usd: str | None = None

    def __post_init__(self):
        for item in (self.input_tokens, self.output_tokens):
            if item is not None and (type(item) is not int or not 0 <= item <= 1_000_000_000):
                raise EngineError("Token usage must be a nonnegative integer or null")
        if self.estimated_usd is not None:
            if not isinstance(self.estimated_usd, str) or len(self.estimated_usd) > 40:
                raise EngineError("Estimated cost must be Decimal text or null")
            try:
                n = Decimal(self.estimated_usd)
            except InvalidOperation as exc:
                raise EngineError("Invalid estimated cost") from exc
            if not n.is_finite() or not 0 <= n <= Decimal("1000000000"):
                raise EngineError("Invalid estimated cost")


@dataclass(frozen=True)
class Generated:
    proposal: Proposal
    usage: Usage

    @classmethod
    def parse(cls, value):
        exact(value, {"proposal", "usage"}, "generator response")
        usage = Usage(**exact(value["usage"], {"input_tokens", "output_tokens", "estimated_usd"}, "usage"))
        return cls(Proposal.parse(value["proposal"]), usage)


class Generator(Protocol):
    """Trusted adapter; all returned data and generated source are untrusted."""

    provenance: str
    identity: str

    def generate(self, request: dict, timeout: float) -> dict: ...


class Session(Protocol):
    def call(self, argument: dict, timeout: float | None = None) -> Any: ...
    def close(self) -> None: ...
    def __enter__(self) -> Session: ...
    def __exit__(self, *args) -> None: ...


class Runner(Protocol):
    identity: dict

    def open(self, code: str, function: str) -> Session: ...


class Workload(Protocol):
    """Trusted host adapter. Candidate code sees observations, never grader state."""

    identity: dict
    contract: dict

    def evaluate(self, candidate: Candidate, cases: list[dict], runner: Runner,
                 budget: Any) -> dict: ...
