# Verification

## Version 0.4: reward integrity and live AutoHelix

Verified locally on 30 October 2026:

- `RSI_DOCKER_TESTS=1 uv run --locked pytest -q`: **91 passed**.
- A calibration coverage check found a missing development fault mechanism
  before inference. The split was corrected to cover every individual mechanism
  in development and validation while preserving disjoint complete families.
- The registered live study completed 48 model calls and twelve selections
  before opening final cases. Estimated inference cost was $1.532685, with no
  unknown call costs.
- All twelve selected policies and four handwritten controls were evaluated
  on 120 final cases from 60 families.
- All 25 study archives verified: 881 events and 474 artifacts.
- The published replay helper reproduced the first reported/frozen and
  verified/frozen policies on a freshly generated corpus: 92/120 and 120/120.
  All 240 per-case outcomes and aggregate semantic metrics matched, with the
  same Docker identity and zero model calls. Timing was excluded from equality.
- The public record includes selected source and every final case audit.
  Full generation requests and portable search archives are retained locally
  under the ignored `runs/reward-study-2026-10-30` directory.

The [result page](REWARD_RESULTS.md) distinguishes live-model findings from
scripted manipulation controls and states the experiment's limits.

## Version 0.3: embedded AutoHelix

Verified locally on 29 October 2026:

- `RSI_DOCKER_TESTS=1 uv run --locked pytest -q`: **81 passed**.
- AutoHelix's real worktree, receipt-check, metric-gate and commit/reject cycle
  passed for both supplied domains and the composed workflow.
- Receipt checks rejected candidate changes after evaluation and linked source
  files. The checker never imported candidate code.
- Failed proposals and fatal budget exhaustion retained their evidence and
  cleaned up the iteration worktree. Rejected-attempt notes reached the next
  proposal.
- The version 0.3 wheel installed with its AutoHelix extra in an independent
  environment. The engine and backend identities matched the source checkout.
- A CLI run with `--backend autohelix` completed using scripted AI-job proposals:
  two accepted revisions, one rejected regression, and 8/8 correct final cases
  (six completed and two correct handoffs).
- The CLI search archive verified 51 events and 27 artifacts. Its separate final
  archive verified three events and two artifacts. The portable export includes
  the AutoHelix configuration, receipts and iteration outcomes.

This was an offline integration check. It made no model calls and does not
demonstrate learned improvement. The existing Bedrock generator is connected
through the bridge, but no live provider comparison was run for this integration.

See the [integration guide](AUTOHELIX.md) and
[verification record](results/autohelix-integration-2026-10-29.json).
Raw local evidence is in `runs/autohelix-integration-2026-10-29`,
`runs/autohelix-integration-final-2026-10-29`, and
`runs/autohelix-integration-evidence-2026-10-29.json`.

## Version 0.2: live model adapter and comparison

Verified locally on 29 October 2026:

- 64 offline tests passed after the structured-response repair. These use fake
  clients and SDK stubs; they make no paid provider calls.
- Six Docker integration checks passed during this change, including the new
  composed workflow, edited-improver execution, history use, final evaluation
  and the existing isolation and execution-limit checks.
- The separately authorized live pilot completed 24 model calls, six committed
  selections, and seven final evaluations including the unchanged seed.
- All 13 completed-study archives verified: 353 events and 180 artifacts.
- The version 0.2 wheel installed into an independent environment. Its CLI worked
  and its source identity matched the registered experiment.
- Gitleaks found no secrets in the reviewed source tree. Generated runs and local
  settings remain excluded from Git.

See [observed results](PILOT_RESULTS.md) and the
[machine-readable record](results/sonnet-pilot-2026-10-29.json).
The initial stopped attempt and its unknown request cost are disclosed there.

## Version 0.1: original scripted demonstration

Verified locally on 29 October 2026 with Python 3.12 and Docker on macOS.

## Test suite

`RSI_DOCKER_TESTS=1 uv run --locked pytest -q` passed **49 tests**.
The suite includes real container execution of search, selection, final evaluation
and evidence export for both synthetic subscription and AI-job workloads.

Other checks cover schema validation, targeted module edits, source validation
without execution, idempotent effects, false completion, authority revocation,
split-family leakage, archive tampering, unknown cost accounting, explicit
generator environment variables, process timeouts and output floods.

## First CLI run

The local run is in the ignored `runs/first-build` directory. Final evaluation
is in `runs/first-build-final`; the portable bundle is
`runs/first-build-evidence.json`.

| Observation | Recorded result |
|---|---|
| Generator | Scripted fixture; no model API calls |
| Starting agent on development | 3 correct outcomes out of 8 |
| Selected agent on validation | 8 correct out of 8 |
| Selected agent on final test | 6 completed and 2 correct handoffs out of 8 |
| Unsafe effects in final test | 0 under the fixed simulator guard |
| Duplicate effects in final test | 0 |
| False completions in final test | 0 |
| Proposal calls | 3 |
| Search and validation case executions | 64 |
| Separate final case executions | 8 |
| Search archive | 37 verified events and 20 verified artifacts |
| Final archive | 3 verified events and 2 verified artifacts |

The changed improver executed, its output influenced the next scripted source
replacement, and the deliberately regressing proposal was rejected as a parent.

These are functional verification results on public authored fixtures. The
examples share fault templates and a simulator. They do not demonstrate learned
improvement, independent transfer, model performance or production reliability.
Timing records are local execution observations, not a controlled performance
benchmark. There is no established recursive advantage.
