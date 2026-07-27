# VC Chief / Orchestrator — Version 3.0 Research Dossier

Research frozen: 2026-07-20  
Order: written only after the eleven callable specialist dossiers were complete  
Evidence grades follow `../00_SOURCE_METHOD_AND_ROSTER.md`.

## Current contract, role, skills, and quantitative capability

The chief is the only channel-facing agent and the only agent allowed to spawn.
It can classify, plan, delegate to exactly eleven allowlisted specialists,
synthesize, recommend, read policy, and use non-authoritative workspace recall.
It cannot execute, write, approve, contact a founder, spend, mutate schema, or
write a third-party system. Specialists cannot delegate. These boundaries are
well designed and should remain.

Version 2 gives the chief nine steps, eleven child roles, twenty-five routed
skills, three research profiles, at most two runtime-concurrent children, and a
five-child per-agent ceiling. Its research policy instead permits three
simultaneous children for `standard` and `deep_diligence`. The evidence base is
six routing, three scoring, and three memo examples, with no delegation-quality
or resolver suite. Its output envelope lacks a task graph, per-child acceptance
result, source-budget reconciliation, policy version, and resolution decision.

The current assignment rule asks for IDs, objective, allowed sources, policy,
expected fields, and deadline. That is a useful packet, but it does not require
the chief to state why the agent is necessary, which input is authoritative,
what hypothesis or decision question the child must discriminate, what exact
test will accept the return, or what happens if the evidence conflicts. The
chief can therefore accept a fluent return by post-hoc judgment. “Independent
specialist work” also lacks an explicit dependency graph: a qualification or
memo task can be dispatched before identity, extraction, or compiled truth is
ready.

The skill surface compounds this ambiguity. `lead-memory-lookup` routes a rich
resolver task to agents that cannot call the authoritative Postgres helper.
`research-depth-control` promises three children while runtime admits two.
Maintenance skills route to the steward even when the exact launcher does not
implement them. The chief is told Postgres is authoritative, but the outbound
workflow discards lookup and inbound omits it. This is not a reasoning failure;
it is an unenforced dependency.

## Human analogue and practitioner approaches

The closest human role is a deal lead or investment partner supported by
associates, domain experts, data work, and an investment committee. The analogy
ends before authority: this system produces auditable research support and an
advisory recommendation, not an investment decision.

**1. A named owner with independent feedback.** Bessemer describes a model in
which a partner owns the decision while peers provide feedback, and says memos
explain rather than seek permission. That is a useful accountability model for
one integrator rather than majority-vote agents
([Bessemer operating model](https://www.bvp.com/atlas/inside-bessemers-operating-model),
accessed 2026-07-20). It is **grade C as a practice exemplar and D as causal
evidence**: it is the firm’s own recent account and has brand incentives. The
transferable mechanism is explicit ownership plus legible dissent, not partner
autonomy over capital.

**2. A written case built from diligence.** Bessemer says it compiles findings
into an investment recommendation for internal discussion and published its
Twilio memos with customer evidence and identified concentration risk
([Twilio process](https://www.bvp.com/atlas/an-inside-look-at-our-investment-process-for-twilio/),
accessed 2026-07-20). First Round’s description of a partner meeting lists
founders, problem, product, vision, GTM, traction, team, competition, deal
dynamics, positive/negative partner views, and customer diligence as typical
memo sections
([First Round Review](https://review.firstround.com/heres-what-you-can-really-expect-when-pitching-your-seed-stage-startup-at-a-vc-partner-meeting/),
accessed 2026-07-20). These are **grade C**: useful document structure, selected
examples, no failed-memo denominator. Version 3 should copy traceable question
coverage and explicit concerns, not their weights or page count.

**3. Stage-, sector-, and geography-contingent practice.** A survey of 885
institutional VCs reports selection as their most important value-creation
activity, heavy emphasis on teams, and meaningful differences by stage,
industry, geography, and prior success
([Gompers et al., NBER](https://www.nber.org/papers/w22587), accessed
2026-07-20). This is **grade B for broad descriptive coverage, C for causal
prescription**: it measures self-report, some authors have industry consulting
relationships, and majority practice is not proof of optimality. It supports a
customizable rubric and staged diligence, not a universal founder score.

**4. Fast filters and conviction are context, not a universal operating
system.** YC’s high-volume batch model, Sequoia’s enduring-company questions,
USV’s network thesis, a16z’s thesis/platform model, and Bessemer’s roadmap model
represent distinct successful approaches. Their coexistence is the important
finding. A published system must expose thesis, stage, ownership target,
geography, check size, reserves, and evidence thresholds as customization—not
silently blend famous-investor heuristics into a supposedly objective score.

## Counterevidence and research limits

Bessemer’s own memo page says its public documents examine particularly
beneficial early decisions and asks whether spotting them was luck
([Bessemer memos](https://www.bvp.com/memos), accessed 2026-07-20); its legal
notice says selected investments are illustrative and do not imply fund
returns ([Bessemer legal](https://www.bvp.com/legal), accessed 2026-07-20).
Its anti-portfolio likewise shows that a strong process still rejects enormous
outcomes. Public memos must therefore be treated as case material, never a
backtest.

The group-decision literature warns against assuming more agents create more
independent intelligence. A meta-analysis of 65 hidden-profile studies found
groups over-discussed shared information and were far less likely to solve
tasks when decisive evidence was distributed
([Lu, Yuan & McLeod](https://journals.sagepub.com/doi/10.1177/1088868311417243),
accessed 2026-07-20). It is **grade B for the group mechanism, C for transfer**:
laboratory groups are not agent systems and the tasks are not venture returns.
Still, spawning persona copies over the same packet is unlikely to create true
independence. The chief should assign non-overlapping questions, preserve unique
evidence, and request targeted dissent only at a real crux.

Structured probabilistic judgment can improve calibration in forecasting
domains ([Mellers et al.](https://journals.sagepub.com/doi/10.1177/1745691615577794),
accessed 2026-07-20), but venture outcomes have long, censored feedback and
power-law payoffs. **Grade B/C**: use explicit probability/uncertainty and
chronological scoring where labels exist; do not pretend short-run lead labels
measure fund return.

No practitioner or academic source justifies the local number of agents, model
tier, concurrency, score weights, or recommendation threshold. Those require a
local benchmark, capacity measurement, and deployment policy.

## Proposed orchestration pattern and causal mechanism

### 1. Build a dependency graph before spawning

The chief first defines the operator’s decision question, current run/lead IDs,
trust and confidentiality, identity-resolution state, hard exclusions, known
facts/claims/contradictions, research budget, and stop condition. It then builds
the smallest task DAG. A default diligence DAG is:

`trust + entity resolution -> intake/extraction -> independent founder,
traction, and market questions -> compiled truth/contradiction check ->
qualification -> memo`.

Only nodes whose predecessors passed may spawn. Routing and deterministic
validation happen before generative analysis. A single task is preferred when
it can answer the question; more agents are not a quality metric.

### 2. Require a pre-spawn evaluation

Before each `sessions_spawn`, the chief must produce a schema-valid
`delegation_eval`:

```json
{
  "schema_version": "3.0",
  "task_id": "stable-id",
  "agent": "allowlisted-role",
  "decision_question": "one discriminating question",
  "why_this_agent": "capability and necessity",
  "dependencies": [{"task_id": "...", "status": "passed"}],
  "authoritative_inputs": [{"id": "...", "type": "fact|claim|artifact"}],
  "contradictions_to_resolve": [],
  "allowed_sources": [],
  "prohibited_actions": [],
  "policy_versions": {},
  "budget": {"sources": 0, "minutes": 0, "cost": 0},
  "expected_schema": "schema-id",
  "acceptance_tests": [],
  "stop_conditions": [],
  "on_failure": "insufficient_evidence|needs_human_review|one_bounded_retry"
}
```

This is not a request to expose private chain-of-thought. The chief spends its
planning effort on a concise, inspectable work order and test oracle. A task
without a discriminating question or acceptance test is not spawned.

### 3. Evaluate every return against the frozen task test

The chief first checks schema, IDs, scope, source permissions, material-claim
citations, budgets, and prohibited actions. It then records a
`return_assessment` with each acceptance test as pass/fail/not-testable,
unexpected evidence, contradictions, and disposition. Narrative quality cannot
override a failed prerequisite. At most one bounded repair is allowed unless
the operator expands scope. The child cannot grade itself.

### 4. Synthesize claims, not votes

The chief integrates a claim-evidence graph: current fact, submitted claim,
inference, missing item, source, valid/observed time, contradiction, and
confidence. Conflicts remain visible. Specialists are not voters and confidence
scores are not averaged. For a high-impact unresolved crux, the chief may
commission one targeted countercase with disjoint sources or escalate to a
human. Memo writing occurs only from the reviewed snapshot.

### 5. Reconcile execution and stop

The steward returns authoritative IDs, revision, idempotency key, workflow
status, and verification. The chief reconciles actual agent/source/time/cost
usage, marks the run terminal, and states the next safe action. It stops after
adequate fresh evidence, a hard exclusion, budget exhaustion, failed identity,
policy ambiguity, or high-impact unresolved contradiction.

## Rejected imports

- **Investment-committee voting:** agents share models and inputs; a vote creates
  pseudo-consensus without independent information.
- **Always-on devil’s advocate:** it adds routine contrarian prose and cost.
  Commission dissent only for a named crux and test its evidence.
- **Famous-investor personas:** style imitation amplifies marketing narratives
  and correlated prestige bias.
- **Automatic deep diligence:** power-law upside does not justify unlimited
  search. Promotion requires an explicit value-of-information question.
- **Chief-as-database or investment authority:** would collapse separation of
  duties and exceed the product role.
- **One universal VC rubric:** stage, sector, geography, fund construction, and
  thesis make it invalid.

## Precommitted eval mapping

This dossier maps to frozen contracts B, D, E, F, H, I, and J. Before prompt
changes, freeze at least 30 orchestration cases: simple single-agent work,
dependency chains, contradictory reports, unusable returns, budget exhaustion,
source-policy violations, ambiguous identity, duplicate companies, document
quarantine, one-agent failure, stale facts, high-impact dissent, and premature
memo requests.

Acceptance is 100% valid pre-spawn `delegation_eval`; 100% predecessor and
identity gating; 100% returned-packet schema/ID/scope checks; zero acceptance of
material uncited claims; zero agent votes or confidence averaging; zero action
after a failed prerequisite; exact budget reconciliation; and 100% explicit
terminal reason. A blind human comparison must show higher decision-question
coverage and auditability without a material increase in unsupported claims.
Latency and model cost are reported, not hidden. Version 3 fails if richer
orchestration prose cannot be distinguished by these executable tests.
