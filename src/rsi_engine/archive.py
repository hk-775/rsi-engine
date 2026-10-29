"""Content-addressed records and a verifiable, append-only event chain."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re

from .contracts import EngineError, canonical, decode, digest

HEX = re.compile(r"[0-9a-f]{64}")


def write_new(path: Path, data: bytes, mode: int = 0o600):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


class Archive:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, mode=0o700, exist_ok=False)
        (root / "artifacts").mkdir(mode=0o700)
        write_new(root / "events.jsonl", b"")
        self.seq = 0
        self.previous = None
        self.objects = set()

    def event(self, kind: str, data: dict):
        record = {
            "sequence": self.seq, "previous": self.previous,
            "time": datetime.now(timezone.utc).isoformat(),
            "kind": kind, "data": data,
        }
        record["hash"] = digest(record)
        with (self.root / "events.jsonl").open("ab") as stream:
            stream.write(canonical(record) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.seq += 1
        self.previous = record["hash"]
        return record["hash"]

    def put(self, kind: str, content):
        value = {"kind": kind, "content": content}
        identity = digest(value)
        if identity not in self.objects:
            write_new(self.root / "artifacts" / f"{identity}.json", canonical(value) + b"\n", 0o400)
            self.objects.add(identity)
            self.event("artifact", {"id": identity, "type": kind})
        return identity

    def select(self, content):
        identity = self.put("selection", content)
        self.event("selection_committed", {"artifact": identity})
        write_new(self.root / "selection.json", canonical({"artifact": identity}) + b"\n")
        return content


def read_artifact(root: Path, identity: str):
    if not isinstance(identity, str) or not HEX.fullmatch(identity):
        raise EngineError("Invalid artifact identity")
    path = root / "artifacts" / f"{identity}.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_000_000:
        raise EngineError("Missing, oversized, or linked artifact")
    value = decode(path.read_bytes(), 16_000_000)
    if digest(value) != identity:
        raise EngineError("Artifact digest mismatch")
    return value


def audit(root: Path, require_selection: bool = False):
    event_path = root / "events.jsonl"
    if event_path.is_symlink() or not event_path.is_file() or event_path.stat().st_size > 32_000_000:
        raise EngineError("Missing or invalid event stream")
    previous = None
    events, objects = [], {}
    for seq, line in enumerate(event_path.read_bytes().splitlines()):
        record = decode(line)
        if not isinstance(record, dict) or set(record) != {"sequence", "previous", "time", "kind", "data", "hash"}:
            raise EngineError("Malformed event")
        expected = record.pop("hash")
        if type(record["sequence"]) is not int or record["sequence"] != seq or record["previous"] != previous:
            raise EngineError("Event chain is out of order")
        if digest(record) != expected:
            raise EngineError("Event hash mismatch")
        previous = expected
        record["hash"] = expected
        events.append(record)
        if record["kind"] == "artifact":
            obj = read_artifact(root, record["data"]["id"])
            if obj["kind"] != record["data"]["type"]:
                raise EngineError("Artifact type mismatch")
            objects[record["data"]["id"]] = obj
    if not events:
        raise EngineError("Empty event stream")
    actual = {p.stem for p in (root / "artifacts").iterdir()}
    if actual != set(objects):
        raise EngineError("Unregistered or missing artifacts")
    selection = None
    commits = [e for e in events if e["kind"] == "selection_committed"]
    if commits:
        if len(commits) != 1 or events[-1] != commits[0]:
            raise EngineError("Events changed after selection")
        pointer_path = root / "selection.json"
        if pointer_path.is_symlink():
            raise EngineError("Linked selection pointer")
        pointer = decode(pointer_path.read_bytes())
        if pointer != commits[0]["data"]:
            raise EngineError("Selection pointer does not match its committed event")
        identity = pointer["artifact"]
        if identity not in objects or objects[identity]["kind"] != "selection":
            raise EngineError("Selection artifact is missing")
        selection = objects[identity]["content"]
    elif require_selection:
        raise EngineError("This run has no committed selection")
    return {"events": events, "objects": objects, "selection": selection, "chain_head": previous}
