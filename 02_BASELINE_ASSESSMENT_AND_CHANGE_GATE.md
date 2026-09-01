# Version 2 baseline assessment and change gate

Status: frozen before Version 3.0 implementation  
Baseline reviewed: `Version_2/complete_update`  
Purpose: decide whether a proposed amendment is likely to improve an observed
failure, not merely make the system longer or more opinionated.

## Executive assessment

Version 2 has unusually strong safety primitives for an agent research system:
only the chief can delegate, specialists cannot spawn, external writes require
approval, Postgres is declared authoritative, untrusted documents are bounded,
claims are separated from verified facts, temporal provenance is modeled, and
mutations are confined to four reviewed workflows. Those controls should be
preserved.

The system is not yet reliable as a published lead-research product. Its prose
contracts exceed its executable capabilities. Most importantly, authoritative
identity retrieval is incomplete and bypassed; agent output contracts drift;
the orchestrator does not pre-register a machine-checkable evaluation for each
delegation; specialist memory tools point to empty, read-only stores; several
documented maintenance routes are not callable; and the evidence fixtures are
too small to justify the release claims.

The correct Version 3.0 direction is therefore a narrower executable contract,
not a larger autonomous investment committee. It should improve research
precision, outlier recall, identity safety, evidence entailment, calibration,
and operator review while retaining the current side-effect boundary.

## Quantitative baseline

| Surface | Baseline | Consequence |
|---|---:|---|
| Agents | 12 total: 1 chief, 11 specialists | Useful role separation, but hard-coded counts make publication customization brittle. |
| Shared skills | 25 | Broad policy surface; several skills lack an executable path or meaningful fixtures. |
| Fixed mutable workflows | 4 | Strong allowlist, but only a subset of documented persistence/maintenance promises is implementable. |
| Routing fixtures | 6 | Too small for 12 roles and ambiguous multi-skill cases. |
| Scoring fixtures | 3 | Cannot establish calibration, missing-data behavior, or rubric stability. |
| Memo fixtures | 3 | Cannot establish citation entailment, countercase quality, or snapshot consistency. |
| Resolver fixtures | 0 | Retrieval correctness is untested. |
| Default child concurrency | 2 | Conflicts with the documented 3-child standard/deep profile. |
| Steward exec timeout | 120 s | Conflicts with a 360 s workflow boundary; valid runs can be cut off by the outer tool. |
| Distinct default model tiers | 1 | `VC_FAST_MODEL` and `VC_PRIMARY_MODEL` both default to `openai/gpt-5.6`; tier labels do not create a cost/quality tradeoff. |
| Specialist operational-memory corpora | 0 seeded, writable | Eleven agents expose recall over empty read-only workspaces. |
| Intake workflows enforcing identity resolution | 0 of 2 | Outbound ignores its lookup result and inbound omits lookup. |

## Qualitative assessment by system property

### 1. Authority and side effects — preserve

Strengths:

- Only `vc-chief` can spawn an allowlisted child.
- Specialists cannot delegate or write.
- Only `data-steward` can use the exact executable allowlist.
- Agent-mode mutation is limited to fixed workflows; arbitrary SQL, Lobster,
  shell text, resume tokens, and approval decisions are not passed through.
- Approval is scoped, expiring, hash-bound, single-use, and intended to be
  consumed atomically with the governed action.

These are real controls with negative tests. Version 3.0 must not weaken them in
the name of convenience or greater autonomy.

### 2. Identity and retrieval — redesign

The `lead-memory-lookup` skill promises typed identifiers, aliases, domain,
person, URL, artifact hash, permalink, reviewable fuzzy candidates, prior
decisions, stale evidence, and a fail-closed creation decision. The actual
`vcops memory-lookup` implementation searches company-name substrings, an exact
domain, lead-title substrings, and recent related facts. It does not search
exact entity IDs, legal names, aliases, source/event/message IDs, artifact SHA,
people, decisions, memos, or workflow history.

Two different products are both called “memory”:

1. Postgres lookup, which is authoritative but incomplete.
2. Per-agent Markdown retrieval, which is non-authoritative and initially empty
   for every specialist.

The outbound workflow calls Postgres lookup and discards the result; inbound
does not call it. Therefore identity safety is documentary, not enforced.
This is the highest-priority Version 3.0 defect.

### 3. Agent contracts — consolidate

The same output is described independently in an agent `AGENTS.md`, a shared
`SKILL.md`, templates, and sometimes workflow code. They have drifted:

- Signal action enums differ: `capture_lead`/`update_existing` versus
  `capture_candidate`/`update_candidate`.
- The routing skill requires `required_skills`; the agent result omits it.
- The inbound skill expects trust, consent, and lawful-basis handling that the
  agent result does not structurally expose.
- Traction policy requires cohort and fact-status details absent from the agent
  output contract.
- Memo policy describes structured citations while the agent output is less
  precise.

Version 3.0 needs one canonical schema per boundary and conformance tests; prose
should explain that schema rather than redefine it.

### 4. Orchestration — require an evaluation before delegation

Version 2 tells the chief to pass stable IDs, bounded packets, and output
contracts. It does not require a structured, persisted-in-run pre-spawn
evaluation describing why the child is needed, what would count as success,
which inputs are authoritative, what contradictions matter, what sources and
actions are permitted, the budget/deadline, and how the result will be checked.

This permits plausible but unusable child reports and post-hoc goal shifting.
Version 3.0 should require a `delegation_eval` object before every spawn and a
matching `return_assessment` after it. The chief remains accountable for
integration and cannot average specialist opinions as votes.

### 5. Role design — narrow overloaded agents

Several specialists own skills not needed for their core task. The data steward
is described as database executor, governance auditor, resolver checker, health
checker, schema proposer, notification auditor, and eval runner, although the
agent launcher cannot execute all of those routes. The memo writer and
qualification analyst also carry policy duties that belong in deterministic
predecessors or the chief’s integration step.

Version 3.0 should remove irrelevant tools/skills, not grant new privileges.
Rules that can be deterministic—normalization, numeric recomputation, schema
validation, routing of unambiguous cases, and retrieval exact matches—should be
implemented or tested deterministically.

### 6. Evidence and investment practice — triangulate, do not imitate

The research dossier treats public VC advice as a source of hypotheses, not
ground truth. Fund blogs optimize brand and deal flow as well as instruction;
portfolio logos do not prove process quality; survivor cases omit misses; and
academic studies often measure narrower constructs than venture performance.

Practitioner methods are adopted only when they improve this system’s actual
decision support: customer/problem intensity, founder learning speed, market
structure, metric quality, distribution, countercases, cruxes, and next
diligence. No named investor’s rubric becomes an automatic weight without a
local labeled backtest.

### 7. Publication and customization — make policy explicit

Version 2 repeatedly requires exactly 12 agents and 25 skills. That is useful
for release integrity but conflates immutable security invariants with a sample
fund’s thesis, stages, source allowlist, scoring weights, approval roles,
retention, costs, and deployment integrations.

Version 3.0 needs a customization map with three classes:

- **Must customize:** organization/thesis/stage/geography, approvers, connectors,
  confidentiality/retention/legal policy, model/provider, budget, source list,
  scoring rubric and recommendation thresholds.
- **Review and usually customize:** agent roster, research depth, operating
  hours, outbound discovery criteria, memo template, notification targets.
- **Do not weaken:** side-effect approvals, typed commands, idempotency,
  provenance, claim/fact separation, untrusted-input boundaries, secret
  handling, audit logs, fail-closed identity review.

## Candidate change register

An implementation change is admitted only if it passes this register and maps
to a frozen eval in `01_PRECOMMITTED_EVALS.md`.

| ID | Observed failure | Proposed mechanism | Expected measurable effect | Regression/rollback trigger | Verdict |
|---|---|---|---|---|---|
| C01 | Resolver contract exceeds lookup and workflows bypass it | Exact-first entity resolver, review-only fuzzy candidates, persisted resolution decision consumed by create | Exact P/R 100%; alias recall ≥95%; no workflow bypass or fuzzy auto-merge | Any privacy leak, duplicate created concurrently, or automatic fuzzy merge | Admit |
| C02 | Specialist Markdown memory is empty/read-only and can fail on compaction | Remove specialist memory tools; define chief recall as sanitized operational notes only | No specialist memory-write errors; no factual claim sourced from operational recall | Loss of authoritative Postgres retrieval or cross-peer leak | Admit |
| C03 | Output definitions drift | Canonical JSON Schemas plus contract tests and prose references | 100% schema conformance; no enum divergence | Schema blocks required safe abstention or workflow compatibility | Admit |
| C04 | Chief delegates without precommitted acceptance | Mandatory `delegation_eval` and `return_assessment` | 100% delegation fixture compliance; lower unusable-return rate | Meaningful latency/cost increase without quality gain in benchmark | Admit |
| C05 | Concurrency and timeout policy contradict runtime | Align one declared concurrency value; outer timeout exceeds inner workflow boundary | No policy/config mismatch; long-boundary test completes/cleans up | Increased overload or unbounded run duration | Admit |
| C06 | Fast/primary tiers are nominal | Mark both model variables as required deployment choices and provide benchmark guidance, not a universal vendor claim | Customization validator catches unreviewed equal tiers; benchmark records cost/quality | Forced cheaper model lowers critical-task eval below threshold | Admit as customization, not hard-coded model |
| C07 | `.xls` is promised but rejected | Correct contract to supported PDF/XLSX/CSV; treat `.xls` as explicit conversion/quarantine case | Contract and helper agree; unsupported file fails safely | Parser attack surface increases or provenance is lost | Admit |
| C08 | Fixed 12/25 assertions block safe customization | Separate sample-profile inventory from security invariants; generate/validate configured inventory | Alternate roster fixture validates without orphan routes | Missing mandatory safety role/route passes validation | Admit |
| C09 | Maintenance skills are assigned without callable implementation | Narrow steward contract to implemented commands; classify operator-only maintenance explicitly | Every route has a callable owner or explicit operator-only state | New generic exec/write authority appears | Admit |
| C10 | Specialist roles mirror VC rhetoric more than measurable outputs | Add cruxes, falsifiers, source yield, metric comparability, uncertainty, and missing-vs-negative distinctions | Agent-specific benchmark thresholds in frozen evals improve | Extra fields increase verbosity without benchmark gain | Admit only after dossier-to-eval mapping |
| C11 | Broader autonomy could reduce operator burden | Let agents contact founders, purchase data, or write CRM directly | Potential latency reduction | Violates explicit product boundary and raises irreversible risk | Reject |
| C12 | More agents could increase perspective diversity | Add multiple investor-persona voters | Potential viewpoint breadth | Correlated verbosity, pseudo-consensus, greater cost, no independent information | Reject |
| C13 | Embeddings could improve fuzzy entity recall | Add semantic matching to identity resolver | Possible recall gain | False merges and opaque linkage | Defer; candidate discovery only after lexical resolver benchmark |
| C14 | One universal “top VC” score could simplify qualification | Encode a composite of named investors’ public heuristics | Simpler ranking | Marketing bias, stage/thesis mismatch, uncalibrated weights | Reject |

## Amendment test applied before implementation

For every accepted change, answer all eight questions:

1. What observed failure and local evidence justify it?
2. Is the proposed mechanism within the product’s lead-research scope?
3. Which frozen eval measures the intended effect?
4. Can a smaller deterministic fix solve the problem?
5. What new failure, cost, or attack surface does it introduce?
6. Which existing safety invariant must remain unchanged?
7. What is deployment-specific and must be marked for customization?
8. What result would cause rollback or redesign?

A change that cannot answer these questions is not implemented. Research prose
alone is not an improvement; an amendment must alter a contract, executable
mechanism, fixture, validator, or explicit customization decision and then pass
its mapped evaluation.

