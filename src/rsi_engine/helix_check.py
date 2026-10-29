"""Trusted AutoHelix check command: read a host receipt, never execute candidate code.

This file is also run as an isolated standalone Python script (-I -S).
Keep it standard-library-only and independent of worktree imports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def read_regular(path: Path, maximum: int):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("Missing, linked or oversized evaluation input")
    return path.read_bytes()


def inspect_receipt(control: Path, worktree: Path):
    name = worktree.name
    if not re.fullmatch(r"iter-[1-9][0-9]*", name):
        raise ValueError("Invalid iteration directory")
    receipt = json.loads(read_regular(control / (name + ".json"), 64_000))
    if (receipt.get("schema") != 1 or receipt.get("worktree") != str(worktree.resolve())
            or type(receipt.get("allowed")) is not bool):
        raise ValueError("Receipt does not identify this worktree")
    hashes = {
        module: hashlib.sha256(read_regular(worktree / (module + ".py"), 32_000)).hexdigest()
        for module in ("task", "improver")
    }
    if hashes != receipt.get("source_hashes"):
        raise ValueError("Candidate changed after isolated evaluation")
    metrics = receipt.get("metrics", {})
    if (set(metrics) != {"correct", "tool_calls"} or
            any(type(v) is not int or not 0 <= v <= 10_000_000 for v in metrics.values())):
        raise ValueError("Invalid receipt metrics")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", required=True, type=Path)
    parser.add_argument("phase", choices=("check", "metrics"))
    args = parser.parse_args(argv)
    try:
        receipt = inspect_receipt(args.control.resolve(), Path.cwd())
        if not receipt["allowed"]:
            print("Isolated evaluator rejected this proposal")
            return 1
        if args.phase == "metrics":
            for name, value in receipt["metrics"].items():
                print(f"##autohelix[{name}={value}]")
        else:
            print("Candidate matches the isolated evaluation receipt")
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        print("Invalid or unavailable isolated evaluation receipt", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
