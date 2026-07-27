# Research Depth Policy

> [MUST_CUSTOMIZE] Re-benchmark source, child, time, and cost limits against
> local decision quality and infrastructure capacity. Active-child concurrency
> must remain aligned with `config/openclaw.json`.

Policy version: `3.0`

Every run starts with the smallest profile that answers the decision question.

| Profile | Max simultaneous children | Max sources | Runtime | Paid connectors | Approval |
|---|---:|---:|---:|---|---|
| `triage` | 1 | 8 | 15 min | no | no |
| `standard` | 3 | 25 | 45 min | no by default | only for sensitivity/cost |
| `deep_diligence` | 3 | 60 | 240 min overall; 45 min per child | within exact approved budget | yes |

More than three specialist roles are executed in sequential waves; the runtime and this policy both cap active children at three. The default child timeout is 45 minutes; deep diligence uses bounded waves inside its 240-minute overall budget rather than one four-hour child. Authoritative entity resolution, no hard exclusion, and a clear decision question precede promotion. Paid/login-gated connectors, sensitive data, cost, and deep-diligence expansion require a scoped unexpired single-use approval.

Before every spawn, freeze the canonical `delegation_eval`. The budget is per task, acceptance is measured after return, and a task stops when its discriminating question is answered. Agent count and source count are ceilings, never targets. Promotion must name the decision that additional information could change and the evidence likely to discriminate it.

Record the requested/approved profile, task DAG, pre-spawn evaluations, wave plan, source/agent/runtime/cost limits, actual usage, approval ID, return assessments, and terminal status when a fixed reviewed workflow supports it. Otherwise label the persistence request `operator_only`; do not imply the steward can execute it. Stop on any exceeded limit; do not continue broad work after a hard exclusion or adequate fresh answer.
