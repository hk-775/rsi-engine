# Interfaces

## Python SDK

```python
from pathlib import Path
from rsi_engine.budget import Limits
from rsi_engine.engine import search
from rsi_engine.examples import ScriptedGenerator
from rsi_engine.sandbox import DockerRunner
from rsi_engine.workload import Pack, StatefulWorkload

result = search(
    Pack(Path("local/subscription")),
    ScriptedGenerator(),
    DockerRunner(),
    StatefulWorkload(),
    Path("runs/example"),
    Limits(proposals=3, case_evaluations=120, wall_seconds=600),
)
```

`Generator.generate(request, timeout)` returns JSON data. `Runner.open(source,
function)` opens an isolated session implementing `call(argument, timeout)`.
`Workload.evaluate(candidate, cases, runner, budget)` executes and grades cases.
The workload implementation is trusted host code, registered explicitly through
the SDK. Its `identity` must change when its behavior changes.

A custom workload can use the existing pack loader with explicit registration:

```python
pack = Pack(
    Path("local/my-workload"),
    adapter="my-workload-v1",
    case_validator=validate_my_case,
)
# Pass pack and your trusted workload instance to search().
```

The manifest's `adapter` and the workload's `identity["adapter"]` must match.
All cases retain `id` and `family`; the trusted validator defines the remaining
schema. It should reject ambiguous or contradictory references. The loader
enforces file hashes, size bounds, duplicate IDs and split-family separation
through the controller. No validator path is loaded from case data.

A workload report supplies `candidate_id`, `case_count`, `correct`, `completed`,
`correct_handoff`, `unresolved`, `unsafe_effects`, `duplicate_effects`,
`false_completions`, `candidate_errors`, `tool_calls`,
`evaluation_wall_seconds`, and `results`. The controller's selection policy uses
those fields. Per-case `results` supply `correct` and a `trace` with action and
response records for the default improver; another improver can consume a
different result detail shape.

## Generator protocol

The trusted generator command reads one JSON line. Requests include:

- `schema_version: 1`, `iteration`, and `parent_id`.
- `candidate`, containing both complete source modules.
- `plan`, containing `target` and `instruction` from the current improver.
- `development`, containing the current development report and traces.
- `contract`, describing available tools and observations.
- `allowed_targets` and the required `response_contract`.

It writes one JSON response line:

```json
{
  "proposal": {
    "target": "task",
    "source": "def decide(context):\n    return {\"action\": \"handoff\"}\n",
    "hypothesis": "Explain which observed failure this change should address."
  },
  "usage": {
    "input_tokens": null,
    "output_tokens": null,
    "estimated_usd": null
  }
}
```

Return actual provider usage if available. Never use zeros as placeholders for
unknown usage. `estimated_usd` is finite nonnegative Decimal text in US dollars,
not a floating-point JSON number. Return `null` when the cost is unknown.

Only the module named in the plan may change. The source must define `decide`
for a task or `plan` for an improver. It is limited to 32000 UTF-8 bytes.
Requests are bounded to 128000 bytes; combined subprocess output is bounded to
256000 bytes. Return a response newline and avoid verbose logging.

The command bridge does not validate the claims of an external model provider.
The provenance label is `external_generator`, not automatically `live_model`.
A provider integration should declare an exact model revision in its identity
and supply its own provider limits.

## Native model adapter and comparison

The native `BedrockGenerator` accepts a validated `BedrockConfig` and an optional
shared `CostLedger`. Install it with `uv sync --locked --extra bedrock`. Its
`settings` are archived, and `last_call` preserves provider evidence on success
and failure. Credentials resolve through the SDK credential chain and never
enter candidate containers.

`SearchPolicy` can enforce the requested edit target and enable history with
compact development feedback. The `frozen_history` and `evolving_history`
policies give equal history access; their edit schedules differ. A changed
improver must honor the registered target and execute in Docker before it can
be retained.

`study.prepare()`, `study.run_study()` and `study.evaluate_study()` implement the
fixed pilot protocol. They are intentionally separate operations. Interrupted
paid execution fails closed; there is no automatic spending-budget reset.

## Evidence export

`rsi-engine export` emits `rsi-engine.evidence.v1` with:

- Engine version, frozen source identity and runtime identity.
- Workload manifest and split hashes.
- Committed candidate identity and validation outcome.
- Full artifact map and ordered event chain.
- Budget consumption, generator provenance and uncertainty about usage.

An importing product should verify hashes, require a supported schema, preserve
the provenance and evidence limitations, and display completed, correct handoff,
and unresolved outcomes separately. It must not infer deployment authorization
or proof of RSI improvement from a successful import.

There is no Workbench or Eval Lab importer in this release. Those projects can
add adapters without becoming dependencies of the engine.
