# AutoHelix adoption assessment

Reviewed 29 October 2026.

## Recommendation

Adopt AutoHelix as the improvement-loop backend. Reduce this project to workload
adapters, controlled RSI experiments, isolated evaluation and evidence export.
Preserve the completed pilot as an archived baseline.

This records the pre-implementation source assessment. At that point AutoHelix
had not been installed or run. Version 0.3 subsequently implemented an embedded
RSI proposal bridge; see [the integration](AUTOHELIX.md).

## Reviewed source

The published `autohelix==0.1.0` source distribution was downloaded from PyPI
without installation or execution. Its SHA-256 matched both the published
metadata and the downloaded bytes:

```text
d97d3779efd5c732fb113d20c01ed17c29acc827e0fac80e744e815083772e84
```

Public source records:

```text
https://pypi.org/project/autohelix/0.1.0/
https://pypi.org/pypi/autohelix/0.1.0/json
```

Package metadata declares Apache-2.0 and identifies `awslabs/AutoHelix` as its
repository. This assessment concerns that exact published distribution.

## Division of responsibility

| Responsibility | Proposed owner |
|---|---|
| Agent invocation and iterative edits | AutoHelix |
| Worktrees, accepted commits and rejected iterations | AutoHelix |
| Improvement history, persistent notes and metric gates | AutoHelix |
| Subscription and AI-job workload definitions | Our workload adapters |
| Execution of generated task code and effect grading | Our isolated runner and external evaluator |
| Development, selection and final-test separation | Our experiment controller |
| Frozen versus evolving comparisons and transfer studies | Our experiment definitions |
| Provider spending enforcement and unknown-cost accounting | A verified provider boundary |
| Portable, verifiable evidence for future product integrations | Our evidence adapter |

This would replace the orchestration responsibilities in `engine.search()`.
The useful research assets include `composed.py`, `grading.py`, `sandbox.py`,
the split and comparison rules, and `archive.py`. They can become adapters or
small independent services instead of growing another general optimizer.

## Findings that affect integration

### Iteration mechanics are already implemented

`src/autohelix/harness.py:715` implements the edit, scope-reversion, constraint,
observable, review and acceptance sequence.
`src/autohelix/sandbox.py:367` prepares agent-facing history and notes;
`sandbox.py:429` saves notes, including after rejected attempts.
`harness.py:203` implements optional metric regression gates.

### Execution needs an external boundary

`src/autohelix/sandbox.py:80` manages Git worktrees.
`checks.py:118` and `checks.py:263` execute configured check and observable
commands through subprocesses in a worktree. These mechanisms provide revision
separation and process execution, without supplying our Docker isolation.

The published Claude Code and Codex adapters also construct commands with
permission-bypass options (`agents/claudecode.py:47` and `agents/codex.py:91`).
The initial integration should therefore run AutoHelix in a disposable,
restricted environment and retain an external evaluator for generated code.
Final cases and authoritative grading state should be inaccessible to the
editing agent. No generated candidate source should execute on our host.

### The cost limit has different semantics

`src/autohelix/harness.py:1105` restores cumulative reported usage from history.
At `harness.py:1127`, it checks the cost limit after an iteration has completed.
Missing `cost_usd` is treated as zero in that accumulation. This does not provide
our pre-request reservation or unknown-cost handling.

Use a backend whose spending can be bounded and whose usage can be recorded
reliably. Our existing Bedrock reservation ledger cannot simply control requests
made internally by an unrelated coding-agent CLI.

### The Bedrock adapter needs deliberate integration

`src/autohelix/agents/__init__.py:134` registers Claude Code, Codex, OpenCode and
a mock backend. It does not register our native Bedrock Converse generator.
An AutoHelix backend edits a worktree and returns an `AgentRunResult`; our
generator returns a source proposal. A supported backend or an explicit bridge
is required.

### Final evaluation remains a separate experiment step

AutoHelix observables produce feedback for the improvement loop. Connect them
to development evaluation. Commit selection before running final evaluation
outside that loop. Keep the existing final corpus as exposed historical
material for future studies.

An AutoHelix iteration is an agent run, potentially involving several model
requests. Compare actual provider usage, evaluated cases, elapsed time and
outcomes; a four-iteration AutoHelix run is not equivalent to our four-call pilot.

### Evidence needs a small adapter

`src/autohelix/history.py` records iteration results in JSONL and saves
observation output. Preserve those records and map them into our evidence
format, including failed attempts, unknown usage and the selected revision.
Its ordinary history file does not replace our content-addressed archive.

## First integration milestone

1. Pin the reviewed AutoHelix version and record the package digest.
2. Connect one synthetic workload to development-only constraint and metric
   commands through the external evaluator.
3. Verify isolation, selection separation and usage reporting with an offline
   backend before making paid requests.
4. Run a bounded live comparison with measured resource allowances and a newly
   registered final set.
5. Retire the duplicated search loop after equivalent controls are demonstrated.

Adoption reduces orchestration maintenance. The research contribution remains
whether a learned improvement strategy transfers to unfamiliar agent failures
and improves subsequent repairs under a matched resource allowance.
