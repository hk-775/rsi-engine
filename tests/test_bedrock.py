from dataclasses import replace
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError
from botocore.stub import Stubber
import pytest

from rsi_engine.bedrock import BedrockConfig, BedrockGenerator, CostLedger
from rsi_engine.contracts import BudgetExceeded, EngineError, Generated, canonical


@pytest.fixture
def config():
    return BedrockConfig("us.anthropic.claude-sonnet-4-6", "us-west-2", "3.30", "16.50",
                         "https://aws.amazon.com/bedrock/pricing/", "2026-10-29")


class Client:
    def __init__(self, *, output=None, stop="tool_use", usage=None, error=None, on_call=None):
        self.output = output if output is not None else canonical({
            "target": "task", "source": "def decide(context):\n    return {'action': 'handoff'}\n",
            "hypothesis": "fixture",
        }).decode()
        self.stop = stop
        self.usage = usage or {"inputTokens": 90, "outputTokens": 50}
        self.error = error
        self.on_call = on_call
        self.calls = 0

    def count_tokens(self, **kwargs):
        return {"inputTokens": 100}

    def converse(self, **kwargs):
        self.calls += 1
        if self.on_call:
            self.on_call()
        if self.error:
            raise self.error
        import json
        if self.stop == "tool_use":
            content = [{"text": "Explanatory text must not break structured output."},
                       {"toolUse": {"toolUseId": "fixture", "name": "submit_proposal",
                                    "input": json.loads(self.output)}}]
        else:
            content = [{"text": self.output}]
        return {"output": {"message": {"role": "assistant", "content": content}},
                "stopReason": self.stop, "usage": self.usage,
                "ResponseMetadata": {"RequestId": "synthetic-request-id"}}


def test_cost_reserved_before_inference_and_settled(config):
    shared = CostLedger("1")
    client = Client(on_call=lambda: (
        pytest.fail("No reservation before inference") if shared.charged <= 0 else None))
    generator = BedrockGenerator(config, client=client, shared_ledger=shared)
    result = Generated.parse(generator.generate({"synthetic": True}, 180))
    expected = (Decimal(90) * Decimal("3.30") + Decimal(50) * Decimal("16.50")) / 1000000
    assert Decimal(result.usage.estimated_usd) == expected
    assert shared.charged == expected
    assert shared.snapshot()["unknown_call_costs"] == 0
    assert generator.last_call["request_id"] == "synthetic-request-id"
    assert generator.last_call["response_blocks"][0]["text"].startswith("Explanatory")


def test_unknown_outcome_is_charged_conservatively_and_not_retried(config):
    client = Client(error=ClientError(
        {"Error": {"Code": "ModelTimeoutException", "Message": "private request detail"}},
        "Converse"))
    generator = BedrockGenerator(config, client=client)
    with pytest.raises(EngineError, match="ModelTimeoutException") as error:
        generator.generate({}, 180)
    assert "private" not in str(error.value)
    assert client.calls == 1
    assert generator.ledger.snapshot()["unknown_call_costs"] == 1
    assert generator.ledger.charged == generator.cost(100, config.max_output_tokens)


@pytest.mark.parametrize("output,stop", [("not JSON", "end_turn"), ('{"target":', "max_tokens")])
def test_rejected_output_retains_provider_usage(config, output, stop):
    generator = BedrockGenerator(config, client=Client(output=output, stop=stop))
    raw = generator.generate({}, 180)
    assert raw["usage"]["input_tokens"] == 90
    assert generator.ledger.snapshot()["unknown_call_costs"] == 0
    with pytest.raises(EngineError):
        Generated.parse(raw)
    assert generator.last_call["raw_text"] == output


def test_caps_prevent_inference(config):
    client = Client()
    generator = BedrockGenerator(replace(config, max_estimated_usd="0.0001"), client=client)
    with pytest.raises(BudgetExceeded):
        generator.generate({}, 180)
    assert client.calls == 0
    generator = BedrockGenerator(replace(config, max_calls=1), client=client)
    generator.generate({}, 180)
    with pytest.raises(BudgetExceeded):
        generator.generate({}, 180)
    assert client.calls == 1
    with pytest.raises(BudgetExceeded):
        BedrockGenerator(config, client=client).generate({}, 10)


@pytest.mark.parametrize("usage", [
    {"inputTokens": 101, "outputTokens": 50},
    {"inputTokens": 90, "outputTokens": 50, "cacheReadInputTokens": 10},
    {"inputTokens": True, "outputTokens": 50},
])
def test_unexpected_usage_keeps_reservation(config, usage):
    generator = BedrockGenerator(config, client=Client(usage=usage))
    with pytest.raises(EngineError, match="Unexpected provider usage"):
        generator.generate({}, 180)
    assert generator.ledger.snapshot()["unknown_call_costs"] == 1


def test_ledgers_reject_nan_overcommit_and_oversettlement():
    ledger = CostLedger("0.10")
    with pytest.raises(BudgetExceeded):
        ledger.reserve(Decimal("NaN"))
    index = ledger.reserve(Decimal("0.08"))
    with pytest.raises(BudgetExceeded):
        ledger.reserve(Decimal("0.03"))
    with pytest.raises(EngineError):
        ledger.settle(index, Decimal("0.09"))
    ledger.settle(index, Decimal("0.02"))
    assert ledger.reserve(Decimal("0.08")) == 1


def test_sdk_schema_is_valid_without_network(config):
    # Explicit fixture credentials and Stubber mean neither credential discovery
    # nor a paid provider call occurs in this test.
    client = boto3.client("bedrock-runtime", region_name="us-west-2",
                          aws_access_key_id="fixture", aws_secret_access_key="fixture")
    with Stubber(client) as stub:
        stub.add_response("count_tokens", {"inputTokens": 100})
        stub.add_response("converse", {
            "output": {"message": {"role": "assistant", "content": [{"text": "{}"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 90, "outputTokens": 10, "totalTokens": 100},
            "metrics": {"latencyMs": 1},
        })
        result = BedrockGenerator(config, client=client).generate({}, 180)
        assert result["usage"]["output_tokens"] == 10
        stub.assert_no_pending_responses()


def test_token_counter_can_use_base_model_while_inference_uses_profile(config):
    class RecordingClient(Client):
        def count_tokens(self, **kwargs):
            assert kwargs["modelId"] == "anthropic.claude-sonnet-4-6"
            return super().count_tokens(**kwargs)
        def converse(self, **kwargs):
            assert kwargs["modelId"] == "us.anthropic.claude-sonnet-4-6"
            return super().converse(**kwargs)
    BedrockGenerator(replace(config, token_count_model_id="anthropic.claude-sonnet-4-6"),
                     client=RecordingClient()).generate({}, 180)


def test_multiple_proposals_are_rejected_with_usage_preserved(config):
    class Multiple(Client):
        def converse(self, **kwargs):
            result = super().converse(**kwargs)
            blocks = result["output"]["message"]["content"]
            blocks.append(blocks[-1])
            return result
    result = BedrockGenerator(config, client=Multiple()).generate({}, 180)
    assert result["usage"]["output_tokens"] == 50
    with pytest.raises(EngineError):
        Generated.parse(result)
