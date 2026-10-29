"""Disposable Python containers with no host mounts or network."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
import uuid

from .contracts import EngineError, canonical, decode

WORKER = r'''
import contextlib, json, sys
wire = sys.stdout
try:
    setup = json.loads(sys.stdin.readline())
    namespace = {"__name__": "__candidate__"}
    with contextlib.redirect_stdout(sys.stderr):
        exec(compile(setup["source"], "<candidate>", "exec"), namespace)
    function = namespace[setup["function"]]
    for line in sys.stdin:
        argument = json.loads(line)
        with contextlib.redirect_stdout(sys.stderr):
            result = function(argument)
        wire.write(json.dumps({"value": result}, allow_nan=False) + "\n")
        wire.flush()
except BaseException as exc:
    wire.write(json.dumps({"error": type(exc).__name__}) + "\n")
    wire.flush()
'''


class BoundedPipe:
    def __init__(self, process: subprocess.Popen, limit: int = 256_000):
        self.process = process
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ, "out")
        self.selector.register(process.stderr, selectors.EVENT_READ, "err")
        self.buffer = bytearray()
        self.total = 0
        self.limit = limit

    def line(self, timeout: float) -> bytes:
        end = time.monotonic() + timeout
        while True:
            if b"\n" in self.buffer:
                line, _, tail = self.buffer.partition(b"\n")
                self.buffer = bytearray(tail)
                return bytes(line)
            left = end - time.monotonic()
            if left <= 0:
                raise EngineError("Subprocess response timed out")
            if not self.selector.get_map():
                raise EngineError("Subprocess ended without a valid response")
            for key, _ in self.selector.select(min(left, 0.1)):
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    self.selector.unregister(key.fileobj)
                    continue
                self.total += len(chunk)
                if self.total > self.limit:
                    raise EngineError("Subprocess output limit exceeded")
                if key.data == "out":
                    self.buffer.extend(chunk)

    def close(self):
        self.selector.close()


def stop(process: subprocess.Popen):
    # The leader may already have exited while descendants still hold its pipes.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream:
            stream.close()


def send(process: subprocess.Popen, raw: bytes, timeout: float):
    """Bound stdin writes too: a candidate may never read the next request."""
    fd = process.stdin.fileno()
    os.set_blocking(fd, False)
    pending = memoryview(raw)
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_WRITE)
        while pending:
            left = deadline - time.monotonic()
            if left <= 0:
                raise EngineError("Subprocess input timed out")
            if selector.select(min(left, 0.1)):
                try:
                    count = os.write(fd, pending)
                except BlockingIOError:
                    continue
                pending = pending[count:]


class DockerSession:
    def __init__(self, image: str, code: str, function: str, timeout: float):
        self.name = "rsi-" + uuid.uuid4().hex
        self.timeout = timeout
        self.closed = False
        command = [
            "docker", "run", "--rm", "--name", self.name, "--pull=never", "-i",
            "--network=none", "--read-only", "--user", "65534:65534",
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=32", "--memory=128m", "--memory-swap=128m", "--cpus=0.5",
            "--ulimit", "nofile=64:64", "--ulimit", "fsize=1048576:1048576",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=8m", "--workdir", "/tmp",
            "--log-driver=none", "--entrypoint", "python3",
            image, "-I", "-S", "-u", "-c", WORKER,
        ]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, start_new_session=True)
        self.pipe = BoundedPipe(self.process)
        try:
            send(self.process, canonical({"source": code, "function": function}) + b"\n", timeout)
        except BaseException:
            self.close()
            raise

    def call(self, argument: dict, timeout: float | None = None):
        raw = canonical(argument)
        if len(raw) > 128_000:
            raise EngineError("Candidate input limit exceeded")
        deadline = time.monotonic() + min(self.timeout, timeout or self.timeout)
        try:
            send(self.process, raw + b"\n", max(0.001, deadline - time.monotonic()))
            response = decode(self.pipe.line(max(0.001, deadline - time.monotonic())))
        except (BrokenPipeError, OSError) as exc:
            raise EngineError("Candidate process communication failed") from exc
        if not isinstance(response, dict) or set(response) != {"value"}:
            raise EngineError("Candidate returned an invalid response or raised an exception")
        return response["value"]

    def close(self):
        if self.closed:
            return
        self.closed = True
        stop(self.process)
        self.pipe.close()
        # A killed Docker client can leave its container running. Always remove our
        # uniquely named container, even when the client exits normally.
        try:
            subprocess.run(["docker", "rm", "--force", self.name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=8, check=False)
        except subprocess.TimeoutExpired:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class DockerRunner:
    def __init__(self, image: str = "python:3.12-slim", timeout: float = 10):
        if not isinstance(image, str) or not image or image.startswith("-"):
            raise EngineError("Invalid runner image")
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", image],
                capture_output=True, timeout=15, check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise EngineError("Docker and a locally available Python image are required; "
                              "run docker pull python:3.12-slim explicitly") from exc
        image_id = result.stdout.decode().strip()
        if not image_id.startswith("sha256:") or len(image_id) != 71:
            raise EngineError("Could not resolve an immutable container image identity")
        self.image = image_id
        self.timeout = timeout
        self.identity = {
            "kind": "docker", "image_id": image_id,
            "network": "none", "host_mounts": [], "read_only": True,
            "user": "65534:65534", "memory_mb": 128, "cpu_limit": 0.5,
            "response_timeout_seconds": timeout,
        }

    def open(self, code: str, function: str) -> DockerSession:
        return DockerSession(self.image, code, function, self.timeout)
