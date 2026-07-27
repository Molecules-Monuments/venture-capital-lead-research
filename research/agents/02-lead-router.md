# Lead Router — Research Dossier

Status: pre-implementation research  
Baseline: `Version_2/complete_update`  
Research date: 2026-07-20

## Current contract and invoked-skill assessment

The router is appropriately narrow: classify origin, distinguish a new lead from a possible update, and select the minimum next specialist work. It cannot browse, research, score, persist, or decide investment quality. It receives the trust decision, memory result, and policy packet rather than reconstructing authority itself. Its invoked path is `lead-memory-lookup` followed by `lead-routing` from the exact 12-agent/26-skill resolver inventory.

The principal weakness is contract/skill divergence. The `lead-routing` skill requires `required_skills` and `blockers`; the agent output requires neither, but adds `candidate_action`, `duplicate_risk`, and `next_step`. The skill says dangling targets or an absent allowlist produce a blocked route, yet there is no canonical blocker code in the agent schema. This weakens deterministic validation and forces the chief to infer the skill chain from prose. The router also cannot verify its memory hint against Postgres directly; that is safe only if the assignment contains the deterministic lookup result the skill requires.

## Quantitative capabilities and gaps

- Four read-only tools: `read`, two memory operations, and current-session status; no web or side effects.
- Three origin groups and a finite 12-role/26-skill route inventory.
- One bounded assignment at a time; no delegation.
- The Version 2 G3 suite contains one example per major route and denials, but it validates static route contracts rather than the model’s semantic behavior under paraphrase, conflicting policies, dependency order, or specialist minimality.
- There is no expected-value-of-information model, dependency graph, specialist cost estimate, or explicit stop/continue condition.

The “smallest specialist set” principle controls cost, but minimum cardinality is not always minimum expected work. Two independent tasks may be efficient in parallel, whereas a market task dependent on resolved identity should wait. The router currently has no field to express that distinction.

## Human analogue and practitioner approaches

The closest human is the associate or deal-flow manager who performs an initial screen and plans the next diligence step. It is not the researcher who answers that step and not the partner who decides.

**Approach 1 — staged, relationship-heavy routing.** First Round describes an initial materials/basic-fit/conflict review, a first meeting, follow-up with the point partner and sometimes a domain expert, reference calls, and then a partnership meeting. Most passes occur after the initial meeting ([First Round investment process](https://www.firstround.com/who-we-back), accessed 2026-07-20). Evidence grade: **B** for stated process, **C** for effectiveness. It supports cheap prerequisites before expensive specialists and domain escalation only after an initial gate. It is self-published and seed-specific.

**Approach 2 — standardized high-throughput routing supported by software.** YC says its admissions team handles tens of thousands of applications through human reading plus custom software for parsing, messaging, and interview selection; it explicitly says there is no secret model that finds great companies ([Inside YC Admissions](https://www.ycombinator.com/blog/inside-yc-the-admissions-team), accessed 2026-07-20). Evidence grade: **B** for the operating description, **C** for outcome causality. This supports structured packets and deterministic workflow support while preserving human escalation for ambiguous pre-launch teams.

The useful commonality is staged work. The disagreement is whether routing should be personalized early or standardized at volume. The system should express the path and information need, not encode either organization’s pace or brand as universal.

## Counterevidence, academic evidence, and transfer limits

The most relevant full-funnel study examines more than 8,000 sourced deals at one early-stage VC. The firm showed selection ability, but selection remained noisy: only a minority of invested companies reached larger financing thresholds, and team scores explained initial funding better than larger outcomes, for which product and market had more power ([Jang & Kaplan, Venture Capital Start-up Selection](https://www.nber.org/papers/w33483), accessed 2026-07-20). Evidence grade: **B** within that fund, **C** for this router. Funding is an imperfect outcome, one firm is not the market, and routing is upstream of investment selection.

The broader VC survey finds meaningful differences by stage, industry, geography, and prior success ([Gompers et al.](https://www.nber.org/papers/w22587), accessed 2026-07-20). Evidence grade: **B** for reported practice, **C** for causal guidance; it is a self-report survey and several authors disclose GP/LP consulting. This rejects one universal route based solely on “what VCs value.”

NIST’s routing evaluation freezes training/test separation and scores ranked routing with average precision ([TREC Filtering and Routing Guidelines](https://trec.nist.gov/data/filtering/T11filter_guide.html), accessed 2026-07-20). Grade **A** for evaluation hygiene, **C** for direct transfer because VC work is a dependency-constrained workflow, not document ranking.

First Round’s path best fits seed software. Growth, biotech, defense, and regulated companies may require legal, technical, or customer validation earlier. In less network-dense geographies, immediate domain-expert routing may be necessary. Route fixtures therefore need stage, sector, and geography variants rather than a single “canonical diligence order.”

## Proposed changes and causal mechanisms

1. **Synchronize schema and skill.** Include canonical `required_agents`, `required_skills`, `blockers`, and enumerated route reason codes. This makes resolver validation deterministic.
2. **Route one decision question, not a topic.** Add `next_decision`, `information_needed`, and `downstream_consumer`. Specialists then answer a falsifiable question instead of producing generic research.
3. **Express dependencies.** Return ordered waves with `parallelizable`, `prerequisite_ids`, and stop conditions. This should lower latency without launching specialists whose inputs are not ready.
4. **Add an ordinal information-value rationale.** Use `low/medium/high` plus explanation, expected decision change, cost class, and false-negative risk—never a pseudo-precise ROI. This should favor the smallest useful experiment rather than the fewest agents mechanically.
5. **Make identity and hard-exclusion checks first-class blockers.** Unresolved identity or policy must prevent research expansion, while an unsupported suspected exclusion should route the smallest verifying task rather than become a rejection.
6. **Require route minimality self-check.** Name each omitted plausible agent and why it is not yet needed. This exposes over-delegation and missing work to the chief.

## Rejected imports

- Do not copy First Round’s meeting sequence, YC’s interview timing, or a fixed “domain expert always second” rule.
- Do not learn routes from historical investment outcomes until local labels distinguish routing quality from company quality and investor access.
- Do not launch all independent-looking roles in parallel when identity, trust, or document safety is unresolved.
- Do not let memory similarity establish a duplicate, merge, or prior decision.

## Precommitted eval mapping

Use at least 12 semantic cases and three perturbations for judgment-heavy cases. Measure agent-selection accuracy (at least 95%), minimality (at least 90%), required-skill accuracy, dependency-order accuracy, blocker correctness, and cost-class agreement; require 100% schema/identifier preservation and fail-closed behavior. Cases must cover ambiguous origin, identity collision, hard-exclusion-first, document-before-traction dependency, safe parallel founder/market work, budget exhaustion, stale-only memory, missing policy, famous-investor prestige, and a novel outlier poorly matched to history. Compare median specialist count and total planned cost with baseline; any increase requires at least the precommitted ten-percentage-point decision-quality lift. Zero route may fabricate authority or perform a side effect.
