# Research plan

The engineering question is whether an evolved improvement procedure produces
better transferable changes than a frozen procedure with equivalent information
and resource budgets.

## What the current example establishes

The supplied source replacements are handwritten fixtures. They demonstrate that
the engine can execute a changed improver, use its output in a subsequent generation
request, execute new task code, reject a regression, preserve evidence, and keep
final testing separate from selection. No foundation model is called.

The simulator includes stale versions, uncertain outcomes before and after a
commit, hidden receipts, authority revocation, permanent outages and transient
outages. Its authorization and idempotency controls are fixed. The agent does not
learn those controls.

## Implemented pilot

The native Bedrock adapter now supports a bounded live-model comparison. The
registered pilot compares a frozen improver with history against an editable
improver with the same history access. It includes an unchanged seed control,
three paired runs, a new two-stage synthetic corpus and a separate host effect
grader. Details and limitations are in [PILOT.md](PILOT.md).

This is scheduled strategy editing, with one model call allocated to changing
the improver. It does not establish open-ended recursive improvement. The
corpus is newly authored, but is not independently authored by an external team.

## Stronger follow-up

1. Use the bounded model generator with a registered, sufficiently powered budget.
2. Retain the unchanged task agent as a control.
3. Compare a frozen improvement procedure, a frozen procedure with accumulated
   history, and an editable procedure with equivalent access to that history.
4. Start improvement comparisons from identical task-agent revisions.
5. Use fresh independently authored scenario families and a separately implemented
   outcome checker. Treat every published fixture as exposed development material.
6. Register the primary metric, budget, minimum useful effect and stopping rule
   before looking at final outcomes.

Measure correct task outcomes, unauthorized or duplicate effects, false completion,
fallback demand, task latency, tokens, compute, evaluation cost and elapsed search
time. Include failed proposals, rejected candidates and the cost of learning the
improvement procedure itself.

Evaluate transfer to unfamiliar APIs and state machines, both without target
feedback and with a separately budgeted adaptation allowance. Current subscription
and AI-job examples share one simulator and cannot establish this result.

## Claims to earn

- **Capability generation:** generated code solves a failure the seed cannot solve.
- **Transfer:** a learned mechanism helps independently defined unfamiliar tasks.
- **Recursive benefit:** the changed improver generates better future improvements
  under a matched total budget.
- **Enterprise value:** an authorized deployment demonstrates a useful operational
  gain with reviewed evidence and rollback.

These are separate claims. Passing the scripted demo establishes none of the
learning or production claims above.
