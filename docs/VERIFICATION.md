# Verification

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
