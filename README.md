# RSI Engine

Generate, execute and evaluate changes to an agent's task code and its improvement
procedure. RSI Engine is a standalone Python SDK and CLI with explicit interfaces
for future evaluation and operations products.

**Status:** working research prototype with a bounded Bedrock generator and a
registered comparison of frozen and editable improvers. The original `demo` uses
scripted source replacements. All supplied workflows are synthetic. Running the
engine does not establish recursive advantage or production readiness.

**AutoHelix is embedded as an iteration backend.** It manages worktrees, history
and acceptance while RSI Engine retains isolated evaluation and experiment
controls. [Integration and commands](docs/AUTOHELIX.md).

**Reward integrity study:** compare reported completion with independently
verified outputs under frozen and editable improvers, using AutoHelix in all
four conditions. Includes synthetic AI batch jobs, false-completion controls,
and a registered $3 inference ceiling.
[Protocol and commands](docs/REWARD_STUDY.md).

**First live pilot:** the frozen improver scored 56/56 in all three runs; the
editable improver scored 56/56, 56/56 and 48/56. The unchanged seed scored 10/56.
There was no measured benefit from editing the improver in this pilot.
[Read the results and failure analysis](docs/PILOT_RESULTS.md).

## Try the AutoHelix backend

```sh
uv sync --locked --extra autohelix
uv run --locked rsi-engine init local/helix-ai-jobs --domain ai_job
uv run --locked rsi-engine demo \
  --backend autohelix --pack local/helix-ai-jobs --out runs/helix-demo
uv run --locked rsi-engine evaluate \
  --pack local/helix-ai-jobs --run runs/helix-demo --out runs/helix-demo-final
```

The demonstration uses scripted proposals and requires Docker. It makes no model
calls. Add `--backend autohelix` to `run` or `study-prepare` to use the embedded
backend with a configured generator. The default `native` backend is preserved.

## Run the model comparison

The pilot asks whether spending one of four model calls on improving the
improvement procedure helps more than spending all four calls on task code.
Both arms start from identical modules and receive development feedback and
history. Three paired blocks alternate arm order.

```sh
uv sync --locked --extra bedrock
uv run --locked rsi-engine init local/composed --domain composed
uv run --locked rsi-engine study-prepare \
  --pack local/composed --study runs/sonnet-pilot \
  --bedrock-config examples/bedrock-sonnet-pilot.json
uv run --locked rsi-engine study-run \
  --pack local/composed --study runs/sonnet-pilot
uv run --locked rsi-engine study-evaluate \
  --pack local/composed --study runs/sonnet-pilot
```

`study-run` makes paid requests using the operator's AWS credential chain. The
example allows at most 24 inference calls and $3 in estimated token cost across
the study. Each call reserves its maximum token cost first. Unknown request
outcomes retain that reservation; the adapter does not retry automatically.
An interrupted study cannot restart and silently reset its spending counter.

The protocol records source, corpus and Docker identities before search. All six
selections must be committed before final cases are opened. The corpus has 12
development cases, 10 validation cases, and 56 final cases from 28 distinct fault
compositions. Final subscription and AI-job variants share those compositions.
This is a small synthetic pilot with a separately implemented host grader, not
an independently authored external benchmark. See [pilot design](docs/PILOT.md).

## Run the first example

Requirements: Python 3.12+, uv, Docker, and a local `python:3.12-slim` image.
Containers use the resolved image ID throughout a run. Image downloads are explicit:

```sh
docker pull python:3.12-slim
uv sync --locked
uv run --locked rsi-engine doctor
uv run --locked rsi-engine init local/subscription
uv run --locked rsi-engine demo --pack local/subscription --out runs/demo
```

The example begins with a workflow that hands off when it encounters an uncertain
outcome or a stale state version. Three scripted proposals then:

1. Replace the improvement procedure with code that examines all observed failures.
2. Use that procedure's output to select a task-code replacement with recovery behavior.
3. Propose a deliberate regression, which is evaluated, rejected as a parent,
   and retained in the evidence.

Selection uses a separate validation split. Run the final test explicitly:

```sh
uv run --locked rsi-engine evaluate \
  --pack local/subscription --run runs/demo --out runs/demo-final
uv run --locked rsi-engine audit runs/demo
uv run --locked rsi-engine audit runs/demo-final
uv run --locked rsi-engine export runs/demo --out runs/demo-evidence.json
```

Use new output directories for each run. Existing evidence is never overwritten.
An AI job orchestration example uses the same adapter:

```sh
uv run --locked rsi-engine init local/ai-jobs --domain ai_job
uv run --locked rsi-engine demo --pack local/ai-jobs --out runs/jobs-demo
```

Both examples share a simulator and fault templates. Their results do not establish
independent transfer across enterprise environments.

## What is implemented

| Component | Behavior |
|---|---|
| Task module | `decide(context)` returns one action; the host executes and grades it |
| Improvement module | `plan(context)` chooses an editable module and gives the generator instructions |
| Generator adapter | Receives only development feedback and returns complete replacement Python source |
| Container runner | Runs candidate source in fresh, resource-limited containers without network or host mounts |
| Workload adapter | Owns business state, authorized effects and final outcome grading outside the container |
| Search controller | Retains nonregressing development candidates for exploration and records every decision |
| AutoHelix backend | Runs the upstream worktree/check/gate/merge cycle through the RSI proposal bridge |
| Selection | Grades all valid proposed candidates on validation after generation ends |
| Final evaluation | Requires a committed selection and matching engine, workload, corpus and runtime identities |
| Evidence archive | Content-addressed artifacts, parent links, chained events, failed proposals and cost records |

The improvement module itself can change and its new code is executed on subsequent
iterations. Keeping a revised improver for exploration is not evidence that it
produces better future improvements; that needs the controlled experiment in
[Research plan](docs/RESEARCH.md).

## Connect a generator

The model-neutral integration is a command bridge. Supply a trusted host
program that reads one JSON request from stdin and writes one JSON response line.
It can call your chosen model provider. No model credentials are required for the
scripted demo, and no provider is invoked by tests.

Create an ignored `local/generator.json`:

```json
{
  "identity": "my-provider-and-model-revision",
  "argv": ["/absolute/path/to/python", "/absolute/path/to/provider_bridge.py"],
  "env_names": ["MY_MODEL_API_KEY"]
}
```

Then run:

```sh
uv run --locked rsi-engine run \
  --pack local/subscription --generator-config local/generator.json \
  --iterations 3 --max-wall-seconds 600 --max-case-evaluations 120 \
  --out runs/model-run
```

The command is explicitly trusted operator code. Only named environment variables
are passed, alongside `PATH` and `LANG`. Store secrets in the environment, never in
arguments or source. Candidate code cannot choose the command or its environment.
See [Generator protocol](docs/INTERFACES.md) for the full request and response.

The engine bounds calls, case evaluations, action steps, response bytes, and
execution time. A command bridge must enforce its own provider token and spending
limits. The native Bedrock adapter also enforces token limits and an estimated
dollar ceiling. Unknown usage remains unknown; estimates are not billing records.

## Integration direction

`rsi_engine.contracts` defines `Generator`, `Runner`, and `Workload` protocols.
The SDK's `search()` and `evaluate_final()` functions accept these implementations
directly. The supplied CLI registers the two synthetic adapters; arbitrary modules
are never imported from a workload pack.

`rsi-engine export` produces `rsi-engine.evidence.v1`, a standalone JSON bundle.
Practical Eval Lab and Workbench adapters can consume this format later. There is
no deployment activation, live Workbench registration, or upstream dependency.

## Tests and limits

```sh
uv run --locked pytest -q
RSI_DOCKER_TESTS=1 uv run --locked pytest -q -m docker
uv build --no-sources
```

The container tests exercise the whole loop on both example domains, final-test
separation, rejection of a regression, execution limits, blocked networking,
read-only root filesystems, and absence of host environment variables.

This runner is intended for a single trusted operator on Linux or macOS with Docker.
Windows and adversarial multi-tenant hosting are not validated. Docker isolation
depends on the host and daemon; it is not a proof of containment. The generator,
workload adapter, grader, Docker daemon and engine are trusted components.

Public fixture tests are reproducible development material. Separate commands
prevent the engine from using final feedback during search; public files are not
secret holdouts. Zero unsafe effects in this example reflect the fixed guard.

- [Architecture and trust boundaries](docs/ARCHITECTURE.md)
- [Embedded AutoHelix](docs/AUTOHELIX.md)
- [Adapter and evidence interfaces](docs/INTERFACES.md)
- [Research plan and claims](docs/RESEARCH.md)

Original code and synthetic examples: **MIT-0**.
