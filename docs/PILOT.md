# Frozen versus editable improver pilot

## Engineering question

Does allocating one of four model calls to changing the improvement procedure
increase selected-agent correctness on unseen workflow compositions, compared
with allocating all four calls to task code?

The treatment is a scheduled editing strategy. It includes the opportunity cost
of the improver edit. It does not isolate the improver's quality independently
of the number of task revisions.

## Registered comparison

| Dimension | Frozen improver | Editable improver |
|---|---|---|
| Initial task and improver | Identical seed | Identical seed |
| Development feedback and history | Same format and access | Same format and access |
| Model calls per run | Four task proposals | One improver proposal, then three task proposals |
| Maximum estimated cost per run | $0.50 | $0.50 |
| Maximum evaluated cases per run | 110 | 110 |
| Search wall ceiling | 1,200 seconds | 1,200 seconds |
| Action ceiling per case | 24 | 24 |
| Selection | Validation correctness, then fewer actions, then earlier revision | Same |

There are three paired blocks, with alternating execution order. Bedrock's
sampling seed is not controlled. These are repeated runs, not perfectly matched
random draws. The primary metric is the paired difference in final correctness.
The pilot does not have enough repeated runs to support a general superiority
claim.

The immutable protocol records the model configuration, source identity, corpus
identity, runtime, edit schedule, limits, metric and stopping rule. All six
selection archive heads are recorded in a barrier before final data are loaded.
Final evaluation uses each committed candidate and the unchanged seed.

## Corpus and grading

Two ordered operations represent a subscription change or AI job workflow.
Injected conditions include repeated stale versions, repeated transient outages,
uncertain outcomes before and after a commit, hidden receipts, permanent outages
and withdrawn authority. The public contract describes the recovery behavior;
the model learns no production API or confidential business rule.

The 50 reachable full fault compositions are deterministically split into:

- 12 development cases.
- 10 validation cases.
- 28 final families, each with a subscription and AI-job variant: 56 cases.

Unreachable second-stage variants after a permanent first-stage stop are
canonicalized. This avoids counting identical execution paths as distinct
families. Domain variants remain correlated. Repeating 56 cases across several
model runs does not create additional independent task families.

The fixed host simulator executes permitted actions. A separate host module
compares actual effects with authored references. Neither task code nor improver
code can edit the simulator, grader, archive or split definitions. Candidate
source runs only in constrained Docker containers.

This separation protects measurement from candidate edits. The corpus and
simulator still have the same author; external independent validation remains
future work. Authorization and idempotency are fixed host controls. Zero unsafe
or duplicate effects primarily demonstrate those controls, not learned safety.

## Model and spending controls

The example uses the public US Sonnet 4.6 inference profile. `CountTokens` uses
the base model ID, because this profile rejected token-count requests during
preflight. Model generation uses the inference profile.

The configured rates were checked on 29 October 2026 against the AWS Bedrock
pricing page's public pricing data:

```text
https://aws.amazon.com/bedrock/pricing/
https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/bedrockfoundationmodels/USD/current/bedrockfoundationmodels.json
```

For the US West (Oregon) entries in the Sonnet 4.6 geo/in-region table, the input
key `1df5eW363G_S2ASEO4Y3hQsj10sRzHapFTYH180h5-E` was $3.30 per million tokens;
the output key `B1t1ZXQVLVtikRcOJlLBuqAgzAG6JyKlrtND3CoXwrg` was $16.50 per
million. Rates are a dated estimate, not a live pricing guarantee or invoice.
Recheck them before a new study.

The adapter counts the complete request and reserves input cost plus maximum
output cost before inference. It records response IDs, raw model output,
provider token usage, termination reason, wall time and estimated cost.
The response uses a forced `submit_proposal` tool call as a structured channel;
the tool is never executed. A text preamble is retained in evidence. The adapter
accepts exactly one named proposal with a normal tool-use stop. Malformed,
ambiguous or truncated responses retain their usage and are rejected.
Transport failures retain the entire reservation. Unexpected usage also retains
the reservation. Automatic retries and caching are disabled.

The study permits at most $3 in estimated inference cost and 24 inference
requests. Engineering time, Docker compute, taxes and other AWS services are
excluded. A one-shot execution marker prevents an interrupted run from silently
restarting with a new cost allowance.

## Interpretation

A generated task can improve substantially over the deliberately weak seed
without demonstrating a benefit from editing the improver. If both arms solve
every final case, report a ceiling result. A harder, independently authored
corpus and more repeated runs would then be needed.

Before a stronger study, freeze a minimum useful effect and power analysis,
include a frozen improver without history as an additional control, and evaluate
transfer to unfamiliar interfaces with separately budgeted adaptation. Do not
reuse an inspected final set as a fresh holdout.
