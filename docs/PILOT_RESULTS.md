# First live-model pilot

29 October 2026 · Sonnet 4.6 through Bedrock · Synthetic subscription and AI-job workflows

**Generated task code improved substantially over the seed. Editing the improver
did not improve the result in this pilot.**

## Final results

Each selected candidate was evaluated on the same 56 final cases, grouped into
28 fault-composition families. All six selections were committed before final
evaluation began.

| Strategy | Run 1 | Run 2 | Run 3 | Mean correctness |
|---|---:|---:|---:|---:|
| Frozen improver with history | 56/56 | 56/56 | 56/56 | 100% |
| Editable improver with history | 56/56 | 56/56 | 48/56 | 95.24% |
| Unchanged seed, evaluated once | 10/56 | — | — | 17.86% |

The paired differences, editable minus frozen, were **0, 0 and −8 correct
outcomes**. The mean difference was **−4.76 percentage points**. Three paired
runs do not establish that editable improvers are generally worse, and they
provide no evidence of a recursive advantage.

A correct outcome includes either completed work or a required handoff with the
right committed effects. Each perfect run completed 38 cases and correctly
handed off 18. The weaker editable run completed 38, correctly handed off 10,
and left 8 unresolved. The seed completed none and correctly handed off 10.

## What failed

The last editable run generated a task policy that retried permanent outages
without a terminal handoff. After repeated `unavailable` responses it looked
for a receipt; after `not_found` it submitted again. That cycle exhausted the
24-action limit.

This affected four final fault families, each represented by a subscription and
an AI-job variant. The eight cases are correlated variants, not eight independent
discoveries. The same failure appeared in two validation cases; the best eligible
candidate produced by that run still had the defect. It was not repaired after
final results were observed.

There were no unsafe effects, duplicate effects or false completions among the
selected candidates. Authorization and idempotency were enforced by the fixed
host simulator; these zeros do not demonstrate that the model learned safety.

## What actually ran

This used live model calls, not the scripted demonstration. Each frozen run had
four task-edit calls. Each editable run had one improver-edit call followed by
three task-edit calls, with the same history access and resource limits.

All three generated improvers passed their execution probe and executed on the
three subsequent search iterations: nine uses during search plus three probes.
The corrected pilot had 24 inference calls and no malformed-proposal failures.
Duplicate proposals were retained in the evidence and consumed their call cost.

| Inference cost scope | Estimate |
|---|---:|
| Three frozen runs | $0.300716 |
| Three editable runs | $0.332112 |
| Completed pilot | $0.632828 |
| Known cost across both attempts | $0.717192 |
| Conservative total, including the interrupted request reservation | $0.764211 |

These are provider-token counts multiplied by the registered rates, not billing
records. Local Docker compute and engineering time are excluded.

An initial attempt used strict parsing of free-text JSON. Four responses included
prose and were rejected. The attempt was stopped while a fifth request was in
flight; its cost remains unknown, with its maximum reservation retained.
The replacement protocol used a forced structured proposal response and a $2.80
ceiling. Both attempts remained below the original $3 combined allowance.
No final cases were opened during the stopped attempt.

## Evidence and reproduction

Implementation commit: `b6679ce`.

The engine audited **13 archives, 353 events and 180 artifacts** for the completed
study. The machine-readable [result record](results/sonnet-pilot-2026-10-29.json)
contains the registered protocol, source and corpus hashes, every selected
candidate identity, per-run outcomes, token counts, costs, timings and the
excluded-attempt accounting.

Full local archives and six portable evidence exports are retained under:

```text
runs/sonnet-pilot-structured-2026-10-29/
runs/sonnet-pilot-structured-2026-10-29/exports/
runs/sonnet-pilot-2026-10-29/
```

These directories are ignored by Git. The committed result record is a summary;
it does not contain the complete generated source and trace archive. Hashes
establish internal consistency, not external authenticity.

The [pilot design](PILOT.md) and README commands reproduce the procedure. Model
sampling is not deterministic, so a new run need not reproduce these scores.
The final cases are now exposed material and must not become a supposedly fresh
holdout in a follow-up study.

## Next research step

Test whether a changed improver helps on independently authored interfaces and
fault models, with more repeated runs and a registered minimum useful effect.
This pilot supports model-generated task-code improvement on the supplied
simulator. It establishes neither independent transfer nor open-ended RSI.
