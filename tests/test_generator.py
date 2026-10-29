import sys

import pytest

from rsi_engine.contracts import EngineError
from rsi_engine.generators import CommandGenerator


def test_bridge_is_json_and_environment_is_explicit(monkeypatch):
    monkeypatch.setenv("RSI_TEST_PRIVATE", "must-not-be-inherited")
    code = ("import json,sys,os; request=json.loads(sys.stdin.readline()); "
            "print(json.dumps({'seen':request['value'],'secret':os.environ.get('RSI_TEST_PRIVATE')}))")
    generator = CommandGenerator([sys.executable, "-c", code], "test-command")
    assert generator.generate({"value": "$(never-a-shell)"}, 3) == {
        "seen": "$(never-a-shell)", "secret": None,
    }


def test_explicit_environment_references_are_resolved_at_runtime(monkeypatch):
    monkeypatch.setenv("RSI_TEST_ALLOWED", "fixture")
    code = "import os,json; print(json.dumps({'value':os.environ['RSI_TEST_ALLOWED']}))"
    generator = CommandGenerator([sys.executable, "-c", code], "fixture", ["RSI_TEST_ALLOWED"])
    assert generator.generate({}, 3) == {"value": "fixture"}


def test_nonresponding_generator_is_stopped():
    generator = CommandGenerator([sys.executable, "-c", "while True: pass"], "hang")
    with pytest.raises(EngineError, match="timed out"):
        generator.generate({}, 0.2)


def test_output_flood_is_bounded():
    generator = CommandGenerator([sys.executable, "-c", "print('x'*1000000)"], "flood")
    with pytest.raises(EngineError, match="limit"):
        generator.generate({}, 3)
