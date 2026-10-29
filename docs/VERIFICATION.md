# Initial verification

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
