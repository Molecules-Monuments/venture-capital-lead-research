# Traction Analyst — Version 3.0 Research Dossier

All web sources were accessed 2026-07-20. Evidence grades use `research/00_SOURCE_METHOD_AND_ROSTER.md`.

## Current contract and invoked skills

The Version 2 analyst examines supplied and public customer, user, developer, product, hiring, funding, and commercial signals. It preserves metric definition, value, unit, period, cohort, date, source, and claim status; distinguishes direct, indirect, and weak evidence; and refuses to infer ARR, customers, adoption, or funding from proxies. Its seven skills are `lead-memory-lookup`, `evidence-research`, `knowledge-modeling`, `contradiction-check`, `trajectory-check`, `research-depth-control`, and `approval-gates`.

The epistemic posture is strong. The implementation is not. The agent cannot perform the authoritative memory lookup, has no deterministic calculator, and cannot enforce source/runtime budgets. `trajectory-check` requires exact parsing of suffixes, units, periods, cohorts, and percentage change, yet this remains model arithmetic. The output’s signal object omits `cohort`, `fact_status`, and direct source binding even though the work contract requires them. A single generic signal taxonomy also mixes SaaS revenue, open-source adoption, marketplaces, consumer engagement, hardware backlog, defense contracts, and pre-revenue design partners.

## Quantitative capabilities and human analogue

The agent uses the nominal fast model, with no numeric test suite, confidence calibration, stage/sector metric ontology, or deterministic comparison service. It can recognize a definition mismatch in prose but is not a safe ledger. The closest human is an investor or finance/product analyst reconstructing the operating truth behind a pitch: reconcile bookings versus recognized revenue, inspect cohorts, call customers where authorized, distinguish pilots from deployments, and ask whether usage is repeatable and economically valuable. Public research alone cannot verify private revenue, retention, contract terms, concentration, churn, or usage instrumentation. The agent must label company-supplied data rather than pretend to audit it.

## Practitioner approaches worth testing

**1. YC’s high-frequency growth compass.** Paul Graham recommends weekly growth during the accelerator and prefers revenue, then active users, over absolute counts ([“Startup = Growth”](https://www.paulgraham.com/growth.html)). The mechanism is fast feedback and compounding, not a universal 5–7% threshold. This is **grade C as a pre-seed operating practice and D as causal return evidence**: YC self-report, selected examples, short program horizon, and poor transfer to enterprise, regulated, hardware, or long-cycle sales.

**2. a16z’s metric-definition and cohort discipline.** a16z separates bookings, revenue, recurring and services revenue; warns about cumulative charts, unlabeled axes, small bases, and inconsistent ARR; and recommends cohort retention rather than registrations ([16 Startup Metrics](https://a16z.com/16-startup-metrics/), [16 More Startup Metrics](https://a16z.com/16-more-startup-metrics/)). For B2B it further distinguishes contracted ARR, live ARR, net-new ARR, gross and net retention, and CAC payback ([B2B GTM metrics](https://a16z.com/11-key-gtm-metrics-for-b2b-startups/)). These are **grade B/C for accounting definitions and C for benchmark claims**: reproducible definitions, but fund-selected experience and company/stage dependence.

**3. Customer love as diligence evidence.** First Round describes calling ten Looker customer references and finding unusually strong dependence on the product before its investment ([First Round case](https://review.firstround.com/the-inside-story-of-how-this-startup-turned-a-216-word-pitch-email-into-a-2-6-billion-acquisition/)). The acquisition is a visible portfolio outcome, but the article is one selected winner and firm marketing. It is **grade C** for the mechanism: triangulated customer evidence can be stronger than logo display. The agent should consume authorized, provenance-rich call notes, not initiate contact.

## Independent evidence and counterevidence

A 20-year panel of 142 Israeli incubator technology ventures reports that early sales traction predicted long-run survival and survival at scale ([Gimmon & Levie](https://journals.aom.org/doi/pdf/10.5465/amd.2019.0056)). This is **grade B/C**: longitudinal and outcome-linked, but survival is not VC return, the cohort is small and old, and incubator selection/geography limit transfer.

The countercase is fundamental unpredictability. A study of 6,579 UK new ventures finds that growth becomes harder—not easier—to predict as firms age, even while survival becomes more predictable ([Coad et al.](https://publications.aston.ac.uk/id/eprint/39216/)). This is **grade B** and argues against converting a clean early trend into a long-horizon forecast. The AngelList randomized experiment found that traction disclosure did not increase early investor response on average while team disclosure did ([Bernstein et al.](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12470)); this is attention evidence, not proof that traction lacks outcome value.

Recent AI retention benchmarks rebase cohorts after early “tourist” churn ([a16z AI retention](https://a16z.com/ai-retention-benchmarks/)). That is a useful hypothesis but **grade C/D** for universal benchmarking: private selected-company data, changing definitions, and no disclosed representative denominator. It must never become a hard threshold without local chronological validation.

## Stage, sector, and geography limits

Pre-product ventures need problem intensity, prototype use, design-partner commitment, and learning velocity; zeros in ARR are not negative evidence. Seed SaaS needs cohort retention, revenue quality, concentration, gross margin, sales cycle, and expansion. Consumer, marketplaces, open source, fintech, defense, biotech, and hardware each require different denominators and lag structures. A government contract, grant, backlog, free GitHub star, signed pilot, and paid recurring deployment are not interchangeable. Europe’s procurement, privacy, languages, grants, and slower enterprise cycles make US weekly-growth benchmarks especially hazardous.

## Proposed Version 3 changes and causal mechanism

1. Introduce sector/stage metric ontologies selected by the chief: SaaS, consumer, marketplace, developer/open-source, fintech, regulated enterprise, hardware/deep tech, and government. This prevents category errors.
2. Make metric normalization, comparable-period checks, and arithmetic deterministic. The model interprets returned calculations; it does not calculate them.
3. Emit a complete metric tuple per observation: definition, numerator, denominator, value, unit/currency, period, cohort, as-of/observed/retrieved dates, source, fact status, and comparability key.
4. Separate `reported_scale`, `growth`, `retention`, `engagement_depth`, `revenue_quality`, `customer_concentration`, `sales_efficiency`, and `evidence_reliability`. This shows why a metric matters without collapsing it to “traction.”
5. Add proxy-specific inference ceilings: logos never prove payment, stars never prove production adoption, funding announcements never prove cash received.
6. Permit scenario calculations only when explicitly requested, with assumptions and sensitivity clearly separated from facts. This aligns with the thesis policy while preserving the no-backsolve default.

## Rejected imports

- No universal YC weekly-growth, “40% PMF,” retention, CAC, or ARR threshold.
- No automatic success prediction from Crunchbase, social traffic, investor prestige, or funding amount.
- No comparison of ARR to revenue, contracted to live revenue, gross to net retention, incompatible cohorts, or currencies without a cited basis.
- No hidden estimate presented as a fact, and no private customer contact without scoped approval.

## Precommitted eval mapping

Maps to gates C, D, E, H, I, and J. Freeze fixtures for `1.2m`, `900k`, percentages from small bases, currencies, overlapping periods, cohort shifts, bookings/revenue/ARR, gross/net retention, pilots, logos, GitHub activity, funding announcements, and stale company claims. Required: 100% numeric normalization and deterministic-calculator parity; zero false trend on incompatible observations; 100% required date/unit/period/cohort/fact-status presence; 100% self-report and circular-source labeling; zero proxy-to-fact promotion; correct sector ontology on at least 95% of held-out cases; and 100% budget compliance. Paired cases must hold values constant while changing metric definition or evidence reliability; conclusions must change with an explicit reason. Historical backtests are chronological and report missingness and survivorship, not only classification accuracy.
