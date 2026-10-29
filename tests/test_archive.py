import os

import pytest

from rsi_engine.archive import Archive, audit
from rsi_engine.contracts import EngineError


def test_archive_verifies_then_detects_object_tampering(tmp_path):
    archive = Archive(tmp_path / "run")
    identity = archive.put("candidate", {"task": "example"})
    archive.select({"candidate": identity})
    assert audit(archive.root, True)["selection"]["candidate"] == identity
    path = archive.root / "artifacts" / f"{identity}.json"
    path.chmod(0o600)
    path.write_text('{"kind":"candidate","content":{"task":"changed"}}')
    with pytest.raises(EngineError, match="digest"):
        audit(archive.root, True)


def test_aborted_runs_are_auditable_but_not_selected(tmp_path):
    archive = Archive(tmp_path / "run")
    archive.event("run_aborted", {"reason": "budget"})
    assert audit(archive.root)["selection"] is None
    with pytest.raises(EngineError, match="no committed"):
        audit(archive.root, True)


def test_event_reordering_is_detected(tmp_path):
    archive = Archive(tmp_path / "run")
    archive.event("first", {})
    archive.event("second", {})
    path = archive.root / "events.jsonl"
    path.write_bytes(b"\n".join(reversed(path.read_bytes().splitlines())) + b"\n")
    with pytest.raises(EngineError, match="order"):
        audit(archive.root)


def test_selection_pointer_cannot_be_replaced(tmp_path):
    archive = Archive(tmp_path / "run")
    archive.select({"value": 1})
    (archive.root / "selection.json").write_text('{"artifact":"wrong"}')
    with pytest.raises(EngineError, match="pointer"):
        audit(archive.root, True)


def test_existing_runs_are_not_overwritten(tmp_path):
    Archive(tmp_path / "run")
    with pytest.raises(FileExistsError):
        Archive(tmp_path / "run")
