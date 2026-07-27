# Outbound Scout — Research Dossier

Status: pre-implementation research  
Baseline: `Version_2/complete_update`  
Research date: 2026-07-20

## Current contract and invoked-skill assessment

The outbound scout discovers public candidates within a chief-supplied thesis, source allowlist, jurisdiction, period, and budget. It correctly distinguishes discovery evidence from investment quality, consults memory only for provisional duplicates, and cannot contact, authenticate, persist, score, or delegate. Its main skill is `outbound-sourcing`; `source-improvement` is a separate weekly maintenance route, and `lead-memory-lookup` is a required predecessor.

The main contract gap is that the skill requires `candidates`, `duplicates`, `sources_used`, `budget_used`, `blocked_sources`, and `persistence_request`, while the agent schema only guarantees `result.candidates`, evidence, missing data, warnings, and error. The agent therefore cannot demonstrate compliance with the very budget and source constraints that define its task. The skill also requires exact-domain deduplication before fuzzy proposals; the agent says to run a provisional lookup per candidate but provides no batch plan, normalization trace, or deterministic duplicate collection.

## Quantitative capabilities and gaps

- Six tools: read, public search/fetch, provisional memory search/get, and session status; zero side-effect or delegation tools.
- Search is bounded by source class, jurisdiction, period, result limit, and assignment budget, but consumption is not a required output.
- No authentication, paid service, account creation, downloads, or executable content.
- One candidate array with no minimum or maximum imposed by the agent contract; the “do not pad” rule is qualitative.
- No current metric for precision@k, novel qualified yield, duplicates per source, evidence quality, source-minute cost, vocabulary coverage, or false-negative outliers.

Version 2’s static route fixture proves that a public portfolio page routes to the scout; it does not prove that the scout identifies novel companies, follows budgets, resists circular sourcing, or stops when marginal yield collapses.

## Practitioner approaches

The closest human is a thesis-aware sourcing analyst or scout producing a reviewable candidate packet. It is not a lead creator, diligence owner, or outreach function.

**Approach 1 — concentrated thesis and prepared mind.** Sequoia states that its model is to invest in a small number of companies so it can concentrate support ([Sequoia on the Latin American opportunity](https://sequoiacap.com/article/the-latin-american-startup-opportunity/), accessed 2026-07-20). Its pitch framework asks for problem, solution, why now, customer/market, direct and indirect alternatives, model, team, and vision ([Writing a Business Plan](https://sequoiacap.com/article/writing-a-business-plan/), accessed 2026-07-20). Grade **B** for its stated approach, **D/C** for causal effectiveness: both are self-marketing, and a pitch template is not a sourcing denominator. The transferable mechanism is a compact candidate thesis, not Sequoia’s concentration level.

**Approach 2 — broad open aperture around explicit problem areas.** YC publishes Requests for Startups but warns that these are only a fraction of what it funds and that founders do not need to follow them ([YC Requests for Startups](https://www.ycombinator.com/rfs), accessed 2026-07-20). Grade **B** for stated sourcing interest, **C** for effectiveness. This supports query expansion around hypotheses without making the current thesis an exclusion rule.

**Approach 3 — institutionalized false-negative review.** Bessemer’s anti-portfolio records prominent opportunities it declined ([Bessemer Anti-Portfolio](https://www.bvp.com/anti-portfolio), accessed 2026-07-20). Grade **B** as evidence of a public learning practice, **D** as a complete false-negative denominator: it is selected, humorous, and retrospective. Its useful import is the discipline of reviewing misses, not the anecdotes themselves.

## Counterevidence, academic evidence, and transfer limits

Historical-pattern automation can suppress novelty. The 2026 data-driven-investor study associates automation with better screening of backward-similar companies but fewer rare major successes and fewer subsequent patents/citations ([Data-Driven Investors](https://academic.oup.com/rfs/article/39/7/1909/8285007), accessed 2026-07-20). Grade **B** for the association, **C** for direct system transfer because adoption is observational and private-fund return reporting is selective.

The one-fund study of more than 8,000 sourced deals shows real but noisy selection and emphasizes that market/product evidence explains larger outcomes better than team scoring in that setting ([Jang & Kaplan](https://www.nber.org/papers/w33483), accessed 2026-07-20). Grade **B/C**. Its unusually complete funnel is useful, but one early-stage fund and financing outcomes do not validate universal sourcing criteria.

The counterfactual failure is two-sided: high precision can become a familiar-company filter; high recall can become undifferentiated list padding. Public English sources favor US software, visible launches, open-source projects, and venture-connected founders. Biotech, defense, industrial, emerging-market, and stealth companies require different milestones and sources. Portfolio pages are especially circular: they reveal another investor’s selection, not independent customer or product evidence.

## Proposed changes and causal mechanisms

1. **Make budget accounting mandatory.** Return queries, results inspected, sources fetched, elapsed/source units, blocked sources, and stop reason. This should prevent hidden overrun and “research until cap.”
2. **Separate discovery from corroboration.** Store `discovery_source` and at least one `independent_primary_source` when available. Circular investor/press repetition then cannot masquerade as corroboration.
3. **Add source-yield feedback.** Log deduplicated candidates, accepted-for-review outcomes, evidence grade, cost, and false-positive burden by source window; use `source-improvement` only after minimum sample and human review. This can shift effort toward marginal yield without automatic source deletion.
4. **Use a query frontier.** For each thesis concept, record customer language, adjacent category terms, substitutes, regulation/technical milestones, and explicit negative terms. This should improve recall when companies use emerging vocabulary.
5. **Preserve thesis-near misses.** Add `fit_inference`, `thesis_gap`, and `outlier_reason`; do not discard merely for failing a historical archetype. This is the direct safeguard against backward-similarity bias.
6. **Batch exact normalization before fuzzy memory review.** Canonicalize domains/URLs once, exact-deduplicate, then surface reviewable alias candidates with method and confidence.

## Rejected imports

- No portfolio logo, funding announcement, accelerator membership, web traffic, GitHub star count, or celebrity endorsement proves investment quality.
- Do not import YC’s current requests as hard thesis or Sequoia’s concentration as a candidate cap.
- Do not bulk scrape, authenticate, bypass terms, buy access, or contact founders.
- Do not automatically remove a source after a short low-yield window or assign learned numeric source weights without local, outcome-linked data.

## Precommitted eval mapping

Evaluate at least 12 semantic cases across duplicate-heavy lists, new-category language, circular sources, stale pages, adverse evidence, thesis-near misses, non-US names/domains, result padding, and budget exhaustion. Primary metrics: qualified precision@k, adjudicated novel-candidate recall, exact duplicate precision/recall, independent-primary-source coverage, accepted candidates per source-minute, and outlier recall. Guardrails: 100% URL/date/claim-status fields, 100% budget compliance and stop-reason reporting, zero invented traction/funding/founder facts, zero side effects, and fuzzy matches never auto-merge. Compare source mix and marginal yield with Version 2; do not accept a precision gain that materially reduces the held-out unconventional-outlier suite.

