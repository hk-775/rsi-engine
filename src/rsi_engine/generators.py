"""An explicit JSON-lines bridge to an operator-supplied model integration."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time

from .contracts import EngineError, canonical, decode, exact, text
from .sandbox import BoundedPipe, send, stop


class CommandGenerator:
    """Trusted host executable. Never accepts executable paths from candidate output."""

    provenance = "external_generator"

    def __init__(self, argv: list[str], identity: str, env_names: list[str] | None = None):
        if not isinstance(argv, list) or not argv or len(argv) > 30:
            raise EngineError("Generator argv must be a nonempty list")
        for arg in argv:
            text(arg, "generator argument", 4000)
        self.argv = list(argv)
        self.identity = text(identity, "generator identity", 200)
        if not isinstance(env_names or [], list):
            raise EngineError("env_names must be a list")
        self.env_names = list(env_names or [])
        for name in self.env_names:
            text(name, "environment variable name", 100)
            if not name.replace("_", "").isalnum():
                raise EngineError("Invalid environment variable name")

    @classmethod
    def from_file(cls, filename: Path):
        value = decode(filename.read_bytes())
        exact(value, {"argv", "identity", "env_names"}, "generator configuration")
        return cls(**value)

    def generate(self, request, timeout):
        raw = canonical(request)
        if len(raw) > 128_000:
            raise EngineError("Generator request exceeds 128000 bytes")
        env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"}
        for name in self.env_names:
            if name not in os.environ:
                raise EngineError("A configured generator environment variable is missing")
            env[name] = os.environ[name]
        try:
            process = subprocess.Popen(
                self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, start_new_session=True, shell=False,
            )
        except OSError as exc:
            raise EngineError("Could not start the configured generator command") from exc
        pipe = BoundedPipe(process)
        deadline = time.monotonic() + timeout
        try:
            send(process, raw + b"\n", max(0.001, deadline - time.monotonic()))
            # One response per invocation. Daemon children are killed during cleanup.
            return decode(pipe.line(max(0.001, deadline - time.monotonic())))
        finally:
            stop(process)
            pipe.close()
