# Qualification Analyst — Version 3.0 Research Dossier

All web sources were accessed 2026-07-20. Evidence grades use `research/00_SOURCE_METHOD_AND_ROSTER.md`.

## Current contract and invoked skills

The Version 2 analyst applies exclusions, prequalification, missing-data, contradiction, trajectory, and scoring-readiness rules to a compiled-truth packet. It is advisory, requires provenance for every non-zero criterion, preserves missing dimensions, and blocks `high_priority` without contradiction and trajectory checks. Its nine skills are `lead-memory-lookup`, `compiled-truth`, `contradiction-check`, `trajectory-check`, `lead-routing`, `evidence-scoring`, `knowledge-modeling`, `research-depth-control`, and `approval-gates`.

Several skills exceed its stated job: it should consume routing, memory, compiled truth, and check outputs, not rebuild them. The central quantitative flaw is epistemic: the rubric assigns zero both to materially negative evidence and to no admissible evidence. Although weights are not redistributed, observability becomes performance. Richly documented inbound companies can outrank sparse outbound companies even when underlying quality is equal. One fixed early-stage rubric also compresses pre-seed, seed, Series A, SaaS, marketplace, and deep-tech evidence into the same denominator.

## Quantitative capabilities and human analogue

The role uses the nominal fast model and has no direct deterministic scoring tool. The fixed workflow can later calculate a score, but the model still supplies criterion judgments that drive it. Confidence has no calibration dataset; score bands have no demonstrated chronological relationship to this fund’s decisions or outcomes. The closest human is a VC principal preparing a screening or investment-committee gate: apply mandate and fatal exclusions, assess evidence quality, identify decision cruxes, and recommend the smallest next diligence step. That human does not merely total facts; they distinguish “bad,” “unknown,” “not applicable,” and “too early to know,” and they make fund-specific portfolio judgments the agent is not authorized to make.

## Practitioner approaches worth testing

**1. Evidence-first staged diligence.** First Round’s Looker account describes an investor calling ten customer references and using intense product dependence as a decisive signal ([First Round](https://review.firstround.com/the-inside-story-of-how-this-startup-turned-a-216-word-pitch-email-into-a-2-6-billion-acquisition/)). Its broader guidance describes collecting quantitative and qualitative evidence across team, economic engine, and moat ([First Round evaluation guide](https://review.firstround.com/from-bigco-to-startup-20-tips-for-evaluating-early-stage-companies-and-making-the-leap/)). The Looker acquisition is a visible outcome, but both are selected narratives. Evidence grade is **C**: use the falsifiable evidence mechanism, not the winner’s weights.

**2. Explicit scenario and miss review.** Bessemer publishes selected historical investment memos and an anti-portfolio of major false negatives ([memos](https://www.bvp.com/memos), [anti-portfolio](https://www.bvp.com/anti-portfolio)). The valuable mechanism is institutional memory: retain what was known, why the deal passed or failed, and compare it with later evidence. The sources are **grade C for process, D for causal performance** because winning memos and humorous misses are selected rather than a complete decision ledger.

**3. Multi-stage rather than one-rule screening.** A broad survey of 885 institutional VCs reports that selection is multi-factor and that practices differ across stage, geography, sector, and past success ([Gompers et al.](https://www.nber.org/papers/w22587)). This is **grade B descriptive evidence**, not proof of what produces returns. It supports stage-specific evidence expectations and contradicts copying a universal factor hierarchy.

## Academic evidence and independent counterevidence

Research using internal records at a UK venture fund finds that evaluation criteria change across successive decision stages ([Boocock & Woods](https://publications.aston.ac.uk/id/eprint/38840/)). This is **grade C** because it is one older regional fund, but its mechanism—cheap gate before expensive diligence—is directly relevant.

Mainprize and colleagues report that standardized decisions based on attributes observed in successful ventures beat decisions based on VCs’ espoused criteria across 129 plans ([study record](https://dro.deakin.edu.au/articles/journal_contribution/Caprice_versus_standardization_in_venture_capital_decision_making/21044083)). It is **grade C**: professional-journal evidence with selection, label, and era concerns. It supports consistency audits, not a frozen universal scorecard.

The counterweight is the power-law and false-negative problem. Korteweg and Sørensen find VC performance especially noisy and difficult to separate from luck ([paper](https://finance.darden.virginia.edu/wp-content/uploads/2018/01/paper-Sorensen.pdf) — the `finance.darden.virginia.edu` URL cited at the 2026-07-20 access date **now returns HTTP 404**, re-checked 2026-08-24, so this rests on the archived reading rather than a live link); **grade B/C**, fund-level and not a criterion experiment, and a citation that no longer resolves cannot be re-verified by a reader. Bessemer’s anti-portfolio likewise shows that reasonable filters can reject enormous outcomes, but is not a denominator-complete dataset. A model that predicts past investment choices can merely automate the fund’s biases. A published scorecard/ML case reports 78% accuracy in reproducing one firm’s decisions ([Systems](https://www.mdpi.com/2079-8954/9/3/55)); **grade C/D** because the target is historical choice, not net return, and the sample is one firm.

## Stage, sector, and geography limits

Pre-seed evidence is mostly team, problem, product insight, and learning; missing ARR is expected. Seed and Series A permit stronger adoption, retention, and commercial gates. Deep tech, biotech, defense, and hardware require technical milestones, regulatory/procurement evidence, capital needs, and time horizons that software weights mis-score. European geography changes mandate, follow-on capital, procurement, and regulatory risk. No external study supplies this fund’s weights; they require local policy plus chronological labeled evaluation.

## Proposed Version 3 changes and causal mechanism

1. Separate `quality_score`, `evidence_coverage`, `evidence_reliability`, and `decision_confidence`. This stops unknown from masquerading as bad while keeping missingness visible.
2. Use explicit states per criterion: positive, negative, mixed, unknown, not applicable, and blocked. Deterministic aggregation consumes these typed judgments.
3. Make hard mandate/exclusion, prequalification, diligence readiness, and priority four distinct gates with stage-specific prerequisites. This matches the cost and evidence available at each stage.
4. Require criterion-level evidence IDs, counterevidence, base rate/analogue where available, and `what_would_change_score`. This makes judgment falsifiable.
5. Remove routing, depth, memory execution, compiled-truth construction, and knowledge-modeling skills. The chief supplies immutable prerequisite packets and a pre-spawn eval.
6. Add an exception path that never hides policy: a low score may be sent to human review only with a named power-law hypothesis, capped research budget, and falsifier. This preserves outlier discovery without silently overriding the rubric.

## Rejected imports

- Do not fit weights to selected winning memos, famous funds, or public exits alone.
- Do not optimize for reproducing past partner votes; that can encode pedigree, network, stage, and cycle bias.
- Do not use funding, prestigious co-investors, founder fame, or rich documentation as quality.
- Do not let a composite score override identity, contradiction, legal, confidentiality, or mandate blockers.
- Do not treat the anti-portfolio as a license to waive every filter.

## Precommitted eval mapping

Maps to C, D, E, F, G, H, I, and J. Freeze deterministic boundary fixtures and a chronological historical replay before changing weights. Required: 100% parity with the deterministic calculator; every score boundary and override correct; zero `high_priority` with unreliable identity, hard exclusion, or blocking contradiction; 100% evidence-ID validity; missing and negative paired cases produce different coverage/reliability while any configured ranking penalty is explicit; monotonicity for genuinely stronger otherwise-identical evidence; and no result change from famous founder/investor cues. Report precision, recall, calibration, false-negative opportunity cost, research cost, stage/sector slices, and abstention—not accuracy alone. Any weight or threshold change is `MUST_CUSTOMIZE` and requires chronological holdout improvement without safety regression.
