# Lead Signal Detector — Research Dossier

Status: pre-implementation research  
Baseline: `Version_2/complete_update`  
Research date: 2026-07-20

## Current contract and invoked-skill assessment

The agent is correctly bounded as a passive classifier. It may read one supplied event, use public web search only when the assignment permits, consult provisional memory, and return a proposed action; it cannot persist, score, contact, send, execute, or delegate. Its closest invoked skill is `lead-signal-detection`, preceded in the resolver by `trust-boundary` and a memory lookup. This separation is sound: a message can be evidence that somebody made a claim without proving the claim or granting authority.

There is, however, release-blocking contract drift. `AGENTS.md` permits `ignore`, `capture_lead`, `update_existing`, `ask_clarification`, and `escalate`; the skill permits `ignore`, `capture_candidate`, `update_candidate`, `ask_clarification`, and `escalate`. The agent schema asks for `origin_group_hint`, `memory_match`, and `evidence`, while the skill asks for `source_ids`, `origin_hint`, `memory_summary`, `risks`, and `persistence_request`. A schema-valid worker can therefore violate its skill contract. The skill also says a persistence request is routed to the steward, while the agent contract exposes no such field. Version 3.0 should first select one canonical vocabulary and test it end to end.

## Quantitative capabilities and gaps

- Six allowed tools: `read`, two public-web tools, two memory tools, and `session_status`; zero side-effect or delegation tools.
- Nine named signal families and five proposed actions.
- One-event classification; no authority to maintain a continuous watchlist or compare a channel history unless the chief supplies it.
- No class-specific decision thresholds, review-workload budget, freshness half-life, novelty definition, or calibration method.
- Version 2 has a static vague-approval route case, but no measured precision, recall, calibration, duplicate-update accuracy, or model-level paraphrase robustness. The Version 3.0 precommitment of at least 12 semantic cases is therefore a new baseline, not evidence that current behavior is good.

The largest quantitative omission is an error-cost model. False positives consume chief attention; false negatives can miss rare outliers or material risk. A single generic `confidence` cannot express source independence, freshness, identity confidence, and materiality separately.

## Human analogue and practitioner approaches

The closest human is a junior deal-flow or market-intelligence analyst scanning a bounded feed and escalating observations to a deal lead. It is not a partner, investment scorer, approval recorder, or autonomous monitoring service.

**Approach 1 — thesis-led prepared mind.** USV publishes a narrow, evolving thesis and describes it as the framework used to focus investment activity. That supports maintaining explicit topic profiles and revising them when the opportunity set changes, rather than reacting equally to every announcement ([USV Thesis 3.0](https://www.usv.com/writing/2018/04/usv-thesis-3-0/), accessed 2026-07-20). Evidence grade: **C** for effectiveness, **B** for the firm’s stated method. It is self-authored founder-facing content and cannot establish that the framework caused returns.

**Approach 2 — progress and user behavior over presentation.** YC’s current interview guidance says interviewers inspect what has been built and ask about acquisition, growth, usage, retention, unit economics, user requests, and obstacles; it also treats improvement between application and interview as informative ([YC Interview Guide](https://www.ycombinator.com/interviews), accessed 2026-07-20). That supports classifying a dated change in operating evidence separately from funding or publicity. Evidence grade: **C** for predictive effectiveness, **B** for stated admissions practice. YC is an accelerator with ten-minute interviews, not a conventional fund or passive channel monitor.

These approaches disagree usefully: the first begins from a thesis profile; the second gives high weight to observed company progress. The detector should preserve both `thesis_relevance` and `observed_change` instead of collapsing them into “interesting.”

## Counterevidence, standards, and limits

Automation can narrow the opportunity set. A 2026 *Review of Financial Studies* paper reports that data-driven VCs improved screening among historically similar startups but became less likely to finance rare major successes; voluntarily reported fund-performance data and observational adoption measures limit the result ([Data-Driven Investors](https://academic.oup.com/rfs/article/39/7/1909/8285007), accessed 2026-07-20). Evidence grade: **B** for the documented association, **C** for applying it to this agent. This is a direct warning against training signal thresholds only on familiar prior leads.

NIST’s TREC filtering design is relevant because it treats incoming documents as a time-ordered stream, precommits parameters before test runs, and evaluates utility, precision, and recall rather than raw alert count ([TREC 2002 Filtering Guidelines](https://trec.nist.gov/data/filtering/T11filter_guide.html), accessed 2026-07-20). Evidence grade: **A** for evaluation design, **C** for direct VC transfer: the corpus is old newswire, relevance is easier to label than long-horizon venture value, and its example utility weights must not be imported.

An access-based alternative explanation also matters. Early VC success may improve future deal access rather than persistent ability to select the right segments ([Nanda, Samila & Sorenson](https://www.nber.org/papers/w24887), accessed 2026-07-20). Thus a signal that a famous investor appeared should not be treated as independent proof of company quality.

Transfer is strongest for software and internet businesses with observable public events. It is weaker for biotech, defense, industrial, stealth, and emerging-market companies where milestones are private, regulatory, or locally reported. English-language public feeds overrepresent US venture ecosystems. Freshness rules must be signal-specific: a product launch decays differently from an adjudicated legal event.

## Proposed changes and causal mechanisms

1. **Unify enum and schema.** One vocabulary removes deterministic handoff failures and enables semantic validation.
2. **Decompose the judgment.** Add `materiality`, `novelty`, `source_independence`, `freshness`, and `identity_confidence`, each with reason codes. Separate dimensions should reduce confident action proposals caused by one strong but irrelevant cue.
3. **Require a comparison anchor.** An update must identify the prior dated state or say `prior_state_unavailable`; this should reduce repackaged-news updates.
4. **Make corroboration conditional.** Web research is warranted only when it can change the proposed action within budget. This prevents spending on obvious ignores while retaining a path for high-impact ambiguous claims.
5. **Calibrate to a review budget.** Predeclare precision/recall tradeoffs by signal class and report alerts per 100 observations. This aligns the threshold with chief workload instead of list length.
6. **Add explicit `why_now` and `what_would_change_action`.** These fields make the proposal falsifiable without turning it into a score.

## Rejected imports

- Do not treat funding, a portfolio logo, celebrity-investor attention, follower counts, or press volume as traction.
- Do not import TREC’s numerical utility weights or a generic ML probability threshold.
- Do not allow the detector to approve, merge, persist, or continuously monitor outside a chief-supplied assignment.
- Do not lower the threshold merely because a signal matches the current thesis; that would encode confirmation bias.

## Precommitted eval mapping

Use the global 12-case minimum plus at least three paraphrase/order perturbations. Score: action confusion matrix by signal type; precision and recall at a fixed chief-review budget; duplicate/update accuracy; calibration/Brier score for confidence; source-independence and freshness-field correctness; 100% schema/identifier preservation; 100% fail-closed on vague approval, identity collision, confidentiality, and prompt injection; zero side effects. Include stale recycled news, two articles with one underlying company source, a real correction, a thesis-near but immaterial event, a non-thesis high-value outlier, and famous-investor prestige cues. Accept only if canonical action/schema agreement is 100%, unsupported material claims remain zero, and rare-outlier recall does not regress against Version 2.

