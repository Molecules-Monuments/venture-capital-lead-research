# Version 3.0 Research and Implementation Plan

Status: pre-implementation gate  
Baseline: `Version_2/complete_update`  
Date: 2026-07-20

## Objective

Improve the published OpenClaw VC lead-research system without weakening its
evidence, authority, privacy, or side-effect boundaries. Version 3.0 must make
each specialist more decision-useful, make delegation evaluable before work
starts, make customization explicit, and make canonical retrieval behave as
documented.

## Non-negotiable sequence

1. Inventory every agent, skill, tool, policy, workflow, schema object, and test.
2. Freeze the evaluation contract in `01_PRECOMMITTED_EVALS.md`.
3. Adversarially review the research method for survivorship, marketing,
   selection, citation, academic, and outcome-attribution bias.
4. Research every specialist role and write one independent research file per
   agent. Specialists are completed before `vc-chief`.
5. Write the orchestrator research file and delegation/invocation analysis.
6. Record proposed amendments and a benefit/risk/rejection test for each one.
7. Materialize the Version 2 baseline into this directory and implement only
   amendments that pass the precommitted change gate.
8. Run deterministic, database, retrieval, prompt-contract, and adversarial
   evaluations. Record failures as failures; do not redefine the metric.
9. Publish the customization guide, document assessment, change log, residual
   risks, and final red-team report.

## Research method

### Decision-focused question

For each agent, ask: “What observable output must this role produce so that a
human or downstream agent makes a better, faster, more falsifiable VC lead
decision, within the system’s existing authority and privacy boundary?”

### Evidence ladder

Use sources in this order, while looking for disagreement rather than merely
accumulating citations:

1. Auditable outcomes and primary records: realized exits, public holdings,
   fund or company filings, court records, prospectuses, acquisition records,
   and dated portfolio histories.
2. Contemporaneous practitioner artifacts: investment memos, postmortems,
   decision frameworks, board/founder accounts, and operational playbooks.
3. Long-form interviews, books, podcasts, and essays, checked against observed
   behavior and portfolio construction.
4. Independent reporting and case studies with named sources.
5. Academic evidence relevant to forecasting, decision hygiene, teams,
   markets, selection, and measurement. Treat external validity and practitioner
   applicability as claims to test, not defaults.

No fund or person is included solely because they are famous. Inclusion needs
at least one auditable success/outcome signal and one source that reveals a
decision or operating method. Self-marketing may identify a hypothesis but
does not establish that the method caused the result.

### Required source diversity per agent

Each agent research file must include, when relevant:

- at least two distinct successful practitioner approaches;
- at least one counterexample, failure mode, or practitioner disagreement;
- at least one source independent of the person or fund making the claim;
- at least one relevant academic result, with an external-validity critique;
- explicit translation from evidence to agent behavior and a “do not import”
  section for techniques that do not survive the system’s constraints.

Shared sources may be reused, but each role file must explain its own inference.
The research is broad at the source-bank level and narrow at the change level.

## Adversarial review of this approach

### Threats

| Threat | Why it matters | Control |
|---|---|---|
| Survivorship bias | Famous investors and founders are selected after success | Include misses, anti-portfolios, changed theses, base rates, and role-specific counterexamples |
| Fund-return opacity | Logo lists and paper marks can disguise mediocre realized returns | Label realized, marked, attributed, and merely associated outcomes separately |
| Marketing narratives | Public frameworks may be positioning rather than actual process | Compare words with dated investments, memos, governance records, and independent accounts |
| Outcome attribution | A portfolio winner may succeed despite the investor’s method | Treat outcomes as eligibility evidence, not causal proof of every stated practice |
| Halo transfer | Founder operating advice may not transfer to investor selection | Import only mechanisms tied to the agent’s decision and test them in fixtures |
| Citation laundering | Repeated secondary claims can look independently confirmed | Trace material claims to the earliest inspectable source and mark circular sourcing |
| Academic overreach | Clean studies may not resemble sparse private-company data | Record sample, task, effect, limits, and the operational decision the result could change |
| Complexity bias | More fields and agents can lower reliability and increase latency | Every amendment needs an owner, downstream consumer, stop rule, and measurable lift |
| False precision | Rigid scores may hide uncertainty and power-law payoff structure | Keep facts, priors, estimates, ranges, and judgment separate; measure calibration/coverage |
| Evaluation gaming | Prompt/schema compliance can pass while decision quality fails | Use semantic cases, perturbations, counterfactuals, holdouts, and end-to-end lineage tests |

### Concision test

Research is retained only if it changes one of: input requirements, search
strategy, decision decomposition, evidence standard, stop rule, output schema,
handoff, evaluation, or customization guidance. Interesting biography without
an operational consequence is excluded.

### Change-benefit gate

Before implementation, every amendment must state:

- observed baseline failure or missed opportunity;
- causal mechanism by which the amendment could improve an outcome;
- affected agent and downstream consumer;
- added latency, cost, false-negative, privacy, or coordination risk;
- precommitted acceptance test and rollback condition;
- whether a prompt change is sufficient or deterministic/schema support is
  required.

An amendment is rejected if it only lengthens the prompt, duplicates another
owner, requires unavailable authority/data, cannot be evaluated, or converts a
useful uncertainty into false certainty.

## Per-agent work plan

### 1. Lead Signal Detector

- Baseline questions: Does it distinguish weak observations from material
  state changes? Are novelty, source independence, time decay, and update
  materiality explicit? Does corroborating every signal waste budget?
- Research: deal-flow signal triage, weak-signal detection, event sourcing,
  alert precision/recall, and how practitioners separate curiosity from action.
- Candidate improvement gate: add materiality/novelty/independence dimensions
  only if they improve signal-action precision without suppressing rare leads.
- Evals: noisy channel injection, vague approval, stale/circular news,
  correction, same-company update, novel high-value signal, confidentiality.

### 2. Lead Router

- Baseline questions: Is the smallest-specialist rule sufficient, or does it
  miss expected value of information? Can it express a staged research path?
- Research: triage, queue prioritization, staged diligence, cost of delay,
  experiment selection, and organizational handoffs.
- Candidate improvement gate: route based on the next decision and information
  value, with explicit stop/continue conditions and no hidden score.
- Evals: minimal route, ambiguous origin, hard-exclusion-first, parallelizable
  independent tasks, dependent tasks, budget exhaustion, identity collision.

### 3. Outbound Scout

- Baseline questions: Does source quality dominate list length? Are sourcing
  channels evaluated for marginal non-duplicate yield? Are negative searches
  and emerging-category vocabulary handled?
- Research: proprietary versus public sourcing, prepared-mind theses, network
  and event sourcing, open-source/product signals, scout incentives, and source
  yield measurement.
- Candidate improvement gate: improve novel qualified yield per source-minute
  without broad scraping, paid access, or thesis-confirmation bias.
- Evals: duplicate-heavy list, new category terminology, source circularity,
  adverse evidence, thesis-near miss, result padding, stop-budget compliance.

### 4. Inbound Intake Analyst

- Baseline questions: Does normalization preserve the referrer and submission
  context useful for later evaluation without converting prestige into fact?
- Research: inbound funnel design, referral provenance, structured application
  data, selection bias, confidentiality, missingness, and founder-submitted data.
- Candidate improvement gate: preserve decision-relevant context and missingness
  semantics while minimizing personal/confidential data.
- Evals: named referral, cold inbound, conflicting fields, attachment risk,
  missing consent/retention, prestige cue, duplicate submission, prompt injection.

### 5. Document Intake Analyst

- Baseline questions: Is extraction provenance complete? Can downstream agents
  distinguish extraction completeness, document claim, and independent proof?
- Research: financial/diligence document controls, parser reliability, spreadsheet
  provenance, adversarial files, and human review thresholds.
- Candidate improvement gate: increase reproducible claim recovery and limit
  visibility without allowing model inspection to replace deterministic safety.
- Evals: MIME mismatch, formula/macro, hidden rows, OCR/truncation, conflicting
  deck metrics, page/cell citations, encrypted/oversized files, identical hash.

### 6. Founder Researcher

- Baseline questions: Does “founder-market fit” invite halo, pedigree, or
  retrospective mythology? Are evidence and role-specific hypotheses separated?
- Research: founder assessment approaches across team/market/product schools,
  founder references, earned secrets, rate of learning, integrity evidence,
  identity resolution, bias and predictive-validity literature.
- Candidate improvement gate: replace generic biography with falsifiable
  capability hypotheses, role coverage, evidence quality, and disconfirmers.
- Evals: famous employer halo, unconventional background, same-name collision,
  complementary team, solo-founder gap, adverse allegation, sparse evidence.

### 7. Traction Analyst

- Baseline questions: Are metrics definitionally comparable and decision-relevant
  by business model/stage? Does the role distinguish quality, durability, and
  accounting from headline growth?
- Research: cohorts, retention, revenue quality, sales efficiency, usage,
  developer adoption, marketplace/liquidity metrics, customer references,
  counter-metrics, and metric manipulation.
- Candidate improvement gate: add stage/business-model metric ontology and
  triangulation without backsolving private financials.
- Evals: ARR versus bookings, net/gross, cohort mismatch, logo claims, OSS stars,
  pilot versus paid, concentration, stale metrics, conflicting periods.

### 8. Market Mapper

- Baseline questions: Does the map help underwrite market evolution rather than
  merely list competitors? Are wedge, value chain, budgets, substitutes,
  distribution, market expansion, and non-consumption connected?
- Research: market creation versus share capture, bottoms-up sizing, category
  design, value networks, power laws, competitive response, and timing.
- Candidate improvement gate: produce falsifiable market structure and scenario
  ranges while avoiding invented TAM and generic “why now”.
- Evals: category boundary ambiguity, internal build/status quo, entrant response,
  buyer/user/budget-owner split, new-market expansion, adverse scenario.

### 9. Qualification Analyst

- Baseline questions: Does a fixed weighted score create false precision? Does it
  distinguish kill criteria, uncertainty, expected value, option value, and next
  information need?
- Research: VC selection funnels, decision journals, base rates, calibration,
  structured versus holistic judgment, anti-portfolio analysis, and power-law
  portfolio logic.
- Candidate improvement gate: retain reproducibility while making score limits,
  uncertainty, vetoes, and evidence coverage decision-relevant.
- Evals: same score/different uncertainty, missing high-value dimension,
  hard exclusion, outlier upside, contradiction, origin neutrality, boundary.

### 10. Memo Writer

- Baseline questions: Does the memo reveal the investment case, counter-case,
  cruxes, and what would change the decision, or mainly summarize evidence?
- Research: published investment memos, IC formats, pre-mortems, decision
  journals, dissent, calibration, and post-investment learning.
- Candidate improvement gate: improve claim-to-citation coverage and decision
  clarity without introducing facts or persuasive smoothing.
- Evals: unsupported sentence, stale snapshot, counter-case omission, crux and
  falsifier coverage, recommendation inconsistency, concise executive usability.

### 11. Data Steward

- Baseline questions: Is the write boundary deterministic and complete? Are
  identity, lineage, retrieval, idempotency, rollback, and temporal evidence
  adequate for all promised operations?
- Research: data stewardship, entity resolution, provenance, bitemporal models,
  retrieval design, event sourcing, data quality, and least privilege.
- Candidate improvement gate: make authoritative retrieval and lineage match the
  documented contract without adding free-form SQL or agent authority.
- Evals: exact/fuzzy/alias collisions, domain changes, artifacts/messages, stale
  facts, duplicate review, idempotent replay, revision conflict, permission deny.

### 12. VC Chief (after all specialists)

- Baseline questions: Does it precommit success criteria before delegation? Are
  assignments decision-specific, independently verifiable, and economical? Does
  synthesis preserve dissent and dependency order? Can the chief detect a
  specialist that followed schema but answered the wrong question?
- Research: partner/IC workflows, devil’s advocacy, diligence planning, portfolio
  construction, expected value of information, forecasting, delegation, and
  multi-agent orchestration reliability.
- Candidate improvement gate: require a delegation evaluation packet written
  before spawn; validate work against it; retry only with diagnosed delta;
  preserve dissent and stop when the decision is sufficiently informed.
- Evals: pre-spawn eval presence, task/policy/schema completeness, dependency
  DAG, contradictory agents, partial failure, budget overrun, stale packet,
  evidence reconciliation, no unnecessary delegation.

## Planned artifacts

- `01_PRECOMMITTED_EVALS.md`: frozen quality and completeness measures.
- `research/00_SOURCE_METHOD_AND_ROSTER.md`: practitioner/fund/founder roster,
  outcome labels, evidence grading, and source bank.
- `research/agents/<agent>.md`: twelve separate role research files.
- `audits/BASELINE_DOCUMENT_ASSESSMENT.md`: current-document findings.
- `audits/CHANGE_JUSTIFICATION_REGISTER.md`: benefit/risk/eval for every edit.
- `CUSTOMIZATION.md`: explicit file-by-file customization sequence and tests.
- `audits/FINAL_ADVERSARIAL_REVIEW.md`: final challenge and residual risks.
- Version 3.0 deployment package, migrations, fixtures, and validation evidence.

*(Delivered-as note: the three planned `audits/` assessment files landed as
`02_BASELINE_ASSESSMENT_AND_CHANGE_GATE.md`, `03_CURRENT_DOCUMENT_ASSESSMENT.md`,
and the adversarial-check narrative retained in the project's internal audit
archive (`_internal/`, excluded from the published package); this frozen plan
keeps the original names for provenance.)*

## Completion rule

Version 3.0 is complete only when all 12 agent research files exist, all
specialists have been assessed before the chief, every accepted change maps to
a precommitted eval, retrieval tests exercise actual database behavior, the
customization guide names every fund-specific file, and the final red-team
report contains no unresolved critical finding. A known failure is never
relabelled “out of scope” after implementation merely to obtain a pass.
