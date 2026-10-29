# RSI Engine

This is a standalone research engine. Keep integrations with Practical Eval Lab,
Workbench, AxonLLM and Ostiari behind explicit interfaces. Do not modify those
projects to make this one work.

- Use `uv sync --locked` and `uv run --locked`.
- Original code and synthetic examples use MIT-0.
- Never execute candidate task or improver source in the host Python process.
  Docker is mandatory for the supplied production runner; no automatic fallback.
- The workload adapter, effect simulator, grader, resource controls and archive
  live outside candidate containers. Candidate output is untrusted.
- Generator commands are explicitly configured, trusted host programs. They are
  not candidate code. Do not invoke a paid provider during tests.
- Scripted proposals demonstrate plumbing, not learned improvement. Keep this
  provenance visible in every report. Missing token usage or cost is unknown.
- Selection uses development and validation only. Final evaluation is a separate
  command against a committed selection. Public synthetic cases are not a secret
  or an independent production sample.
- Preserve failed proposals, rejected revisions and actual cost/timing records.
  Artifact hashes detect modification; they are not authenticity signatures.
- Keep credentials, private traces, generated runs and local provider settings
  out of Git. No automatic publication or deployment.

Verify with `uv run --locked pytest -q`. Real container checks are opt-in:
`RSI_DOCKER_TESTS=1 uv run --locked pytest -q -m docker`.
