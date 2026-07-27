# Founder Researcher — Version 3.0 Research Dossier

All web sources were accessed 2026-07-20. Evidence grades use the project rubric in `research/00_SOURCE_METHOD_AND_ROSTER.md`.

## Current contract and invoked skills

The Version 2 role is a public-professional-evidence researcher, not a character investigator. It must resolve identity, examine role-relevant operating, technical, research, domain, and startup history, and distinguish fact, inference, risk, and unknown. Its six skills are `lead-memory-lookup`, `evidence-research`, `knowledge-modeling`, `contradiction-check`, `research-depth-control`, and `approval-gates` (`Version_2/complete_update/workspaces/founder-researcher/AGENTS.md`; `config/openclaw.json`). The privacy boundary, same-name caution, primary-source preference, and refusal to infer misconduct or protected traits are excellent and should remain.

The configuration nevertheless overstates the worker’s authority. It cannot perform the authoritative Postgres lookup required by `lead-memory-lookup`; it can only query non-authoritative workspace memory. `research-depth-control` describes child-agent budgets although this agent cannot delegate. `knowledge-modeling` and `approval-gates` invite work beyond a bounded founder assessment. The result schema evaluates founders separately and has no explicit founding-team complementarity, interaction evidence, key-person dependency, falsifier, or unanswered reference question.

## Quantitative capabilities and gaps

The agent uses `VC_FAST_MODEL` (currently the same default model as `VC_PRIMARY_MODEL`) with no response-schema enforcement, token/source counter, confidence calibration, or identity benchmark. It receives a research budget but does not return budget used. Its confidence is an unanchored model label, not an empirically calibrated probability. Public-profile abundance will mechanically favor visible, networked, English-language, or prestige-employer founders. Absence of a profile is therefore evidence of low observability, not weak ability.

The closest human analogue is a VC associate or principal conducting team diligence before partner review. That person combines public records with interviews, supplied references, founder interactions, cofounder dynamics, and judgment about the next company-building challenges. A web-only model can support identity and history reconstruction; it cannot reliably observe truthfulness, learning velocity, recruiting pull, response to challenge, or cofounder conflict. It should generate hypotheses and diligence questions, not a personality verdict.

## Practitioner approaches worth testing

**1. YC’s adaptive-founder pattern.** Paul Graham publicly emphasizes determination combined with flexibility, imagination, constructive rule-bending, and strong cofounder relationships ([“What We Look for in Founders”](https://www.paulgraham.com/founders.html)). This is meaningfully different from résumé scoring: the proposed mechanism is adaptive action under uncertainty. YC reports a large set of public and high-valued alumni, but that is association-level evidence, not proof that these traits caused returns. The essay is a **practice exemplar, grade C for the construct and D for causality**: selected anecdotes, no rejected-founder denominator, and strong recruiting incentives.

**2. Sequoia’s pivotal-decision lens.** Roelof Botha describes “crucible moments”: founders recognizing an inflection, choosing under uncertainty, and accepting painful capability changes ([Sequoia essay](https://sequoiacap.com/article/crucible-moments-essay/)). Sequoia’s YouTube and Airbnb associations have independently visible outcomes, but the essay is retrospective and winner-selected. It is **grade C as a testable interview frame, D as performance evidence**. The useful import is not “boldness”; it is a chronological record of a consequential decision, alternatives considered, evidence then available, and subsequent update.

**3. Founder–market fit through specific knowledge.** a16z’s account of Chris Dixon’s approach asks whether founders understand the tools, problem, market, and distribution unusually well ([a16z](https://a16z.com/12-things-i-learned-from-chris-dixon-about-startups/)). This is **grade C**: operationally useful but self-published and not linked to a complete outcome denominator. It should become claim-specific evidence—what the founder knows and how that knowledge changed a product or go-to-market decision—not a pedigree proxy.

## Counterevidence and failure modes

Founder-first doctrine has credible counterevidence. Kaplan, Sensoy, and Strömberg follow 50 VC-backed companies from early plans toward public-company stages: business lines were comparatively stable while management turnover was common, leading them to argue that the business may deserve more marginal weight than the original team ([paper](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=657721)). This is **grade B/C**: longitudinal and independent, but a small, old, success-selected IPO-oriented sample. It rejects the import “a great founder can always find a new market.”

Conversely, a randomized AngelList field experiment found that exposing investors to founding-team information increased investor interest, while traction information did not ([Bernstein, Korteweg & Laws](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12470)). This is **grade B** for attention effects, not startup success: investor response is not a realized return and the platform population may not match European institutional seed VC.

Founder assessment is also bias-prone. A pitch experiment found gender and attractiveness effects while holding pitch content more nearly constant ([PNAS](https://doi.org/doi%3A10.1073/pnas.1321202111)); a later field experiment examines race and gender effects among real investors ([Management Science](https://doi.org/10.1287%2Fmnsc.2024.4990)). These are **grade B** warnings with format and population transfer limits. Famous employers, schools, accents, and warm-network access are similarly plausible halo channels even when protected traits are omitted.

## Stage, sector, and geography limits

At pre-seed, interaction evidence and adaptability may dominate sparse metrics; by Series A, team claims should be tested against hiring, execution, and customer evidence. Deep-tech and defense require technical credibility, certification/procurement stamina, and capital planning that consumer-founder heuristics miss. Enterprise infrastructure needs buyer and developer workflow knowledge; consumer companies may require product taste and distribution. European identity, education, and employment records are fragmented across languages and privacy regimes. US network prominence is not a neutral prior for Europe, Israel, or founders with nontraditional careers.

## Proposed Version 3 changes and causal mechanism

1. Make an authoritative identity/alias packet a deterministic predecessor. This reduces same-name error and prestige-driven web search drift.
2. Replace individual résumé summaries with a **team capability map**: product/technical, domain, distribution, recruiting, company-building, and uncovered next-stage needs. This tests complementarity rather than summing biographies.
3. Add chronological `decision_examples` with situation, options, evidence-at-the-time, action, outcome, and later update. This operationalizes adaptability without personality speculation.
4. Add `publicly_observable`, `interaction_evidence_supplied`, `reference_questions`, `key_person_dependency`, `counterevidence`, and `what_would_change_view`. This prevents absence from silently becoming a negative score.
5. Remove worker-owned depth/approval/modeling skills; consume chief-supplied boundaries and return only evidence and proposals.
6. Prohibit a unitary “founder quality” score. Confidence attaches to identity, claims, and bounded inferences separately.

## Rejected imports

- Do not import Graham’s “naughtiness” as a score; it is culturally loaded and can excuse governance risk.
- Do not infer grit from hardship narratives, long hours, social media, or staying with a bad idea.
- Do not use school, employer, investor, or founder fame as a positive prior.
- Do not copy Sequoia winner stories into trait weights or treat pivots as inherently good.
- Do not automate backchannel contact or sensitive personal-data collection.

## Precommitted eval mapping

This dossier maps to evaluation contract C, D, E, H, I, and J. Before prompt changes, freeze at least 12 cases plus paired counterfactuals. Required role-specific gates: identity precision at least 98%; 100% preservation of supplied IDs; zero unsupported credentials or protected-trait inference; 100% material-claim citation; explicit `not_publicly_observable` rather than negative scoring; exact team-gap coverage on adjudicated fixtures; and identical conclusions after swapping prestige school/employer, gender-coded name, or famous-investor cue while keeping evidence fixed. Cases must include same-name founders, quiet technical founders, solo versus complementary teams, prior failure, an impressive résumé with weak relevance, a nontraditional career with strong decision evidence, and contradictory role histories. Human reviewers score usefulness and fairness blind to version; Version 3 must improve decision-question coverage without increasing unsupported founder judgments.
