# Memo Writer — Version 3.0 Research Dossier

All web sources were accessed 2026-07-20. Evidence grades use `research/00_SOURCE_METHOD_AND_ROSTER.md`.

## Current contract and invoked skills

Version 2 turns an immutable compiled-truth snapshot, qualification result, and evidence index into an internal memo. It must distinguish verified facts, submitted claims, inferences, contradictions, stale evidence, and unknowns; reject stale/broken prerequisites; and keep the recommendation advisory. Its eight skills are `lead-memory-lookup`, `compiled-truth`, `contradiction-check`, `trajectory-check`, `memo-writing`, `evidence-scoring`, `knowledge-modeling`, and `approval-gates`.

The boundary is conceptually good but the allowlist is not: a synthesize-only writer should not perform memory lookup, construct truth, score, remodel knowledge, or rerun checks. The contract asks for many mandatory sections while also demanding concision. It returns a flat `evidence_refs` collection rather than a machine-checkable claim-to-evidence map. Existing memo fixtures test headings only, so a fluent, unsupported memo can pass.

## Quantitative capabilities and human analogue

The memo writer uses the primary model, but there is no enforced schema, length/depth profile, citation-entailment test, recommendation-parity test, or token budget. The closest human is the deal champion or associate writing for an investment committee. A useful memo compresses evidence around the actual decision, exposes the strongest counter-case, records unresolved cruxes, and creates an audit artifact. It is neither a pitch deck nor an autonomous decision. A model can structure and compress; it cannot own the investment, resolve source conflicts by prose, or add research absent from the snapshot.

## Practitioner approaches worth testing

**1. Advocate the strongest coherent case.** Sequoia healthcare investor Michael Dixon says he tries to write the memo advocating partnership as an exercise when evaluating a company ([Sequoia interview](https://articles.sequoiacap.com/2018-08-22-michael-dixon)). This can expose whether a coherent thesis exists and is **grade C as a practice exemplar, D as causal evidence**. The failure mode is motivated reasoning: once the author becomes a champion, missing and contrary evidence can be rationalized away. Version 3 should retain a labeled steelman, never let advocacy define the whole memo.

**2. Preserve the contemporaneous record, scenarios, and risks.** Bessemer publishes selected original recommendation memos for LinkedIn, Shopify, Twilio, Yelp, and others ([BVP memo archive](https://www.bvp.com/memos)); its LinkedIn page connects the historical memo with a public-company/acquisition outcome ([BVP LinkedIn](https://www.bvp.com/companies/linkedin)). The memos show concrete market, product, team, economics, scenarios, terms, and risks at decision time. This is **grade B/C for demonstrating what an actual memo contained and D for proving the format caused success**: the archive is explicitly selected from beneficial decisions and excludes the full denominator.

**3. Memo as decision witness rather than sales copy.** Gompers and Strebulaev’s public account describes memos as concise records of risks, assumptions, unknowns, alternative scenarios, and later retrospectives, not as goalposts or pitches ([TIME essay](https://time.com/6979358/118-hour-decision-essay/)). This is **grade C**: it summarizes a larger research program but includes practitioner storytelling and generalized hours. The operational import is auditable ex-ante claims and updateable cruxes, not “118 hours.”

These approaches should coexist: one section steelmans the investment; a separate independently generated section steelmans the pass/counter-case before synthesis.

## Academic evidence and counterevidence

Nickerson’s broad review documents confirmation bias as selective seeking and interpretation of evidence ([Review of General Psychology](https://doi.org/10.1037/1089-2680.2.2.175)). It is **grade B** for the general mechanism, with no direct VC-memo experiment. It supports separating evidence collection from narrative advocacy and forcing disconfirming evidence into the artifact.

Mellers and colleagues’ forecasting tournaments found that training, aggregation, active open-mindedness, and repeated probabilistic updating improved geopolitical forecasting ([paper](https://pubmed.ncbi.nlm.nih.gov/25987508/)). This is **grade B for structured forecasting and C for VC transfer**: geopolitical questions resolve faster and more cleanly than ten-year, endogenous startup outcomes. Use calibrated, resolvable intermediate forecasts—not fake precision about fund returns.

Gary Klein’s premortem asks a team to assume failure and explain why ([HBR](https://hbr.org/2007/09/performing-a-project-premortem)). It is **grade C/D** here: useful prospective-hindsight technique, but HBR practice evidence rather than a VC outcome trial. A mandatory short premortem may surface omitted failure modes; it should be evaluated, not canonized.

The strongest independent counterevidence is selection and hindsight. Public memos are disproportionately winners; later annotations can make vague claims look prescient. VC fund performance is highly noisy, and memo polish can increase confidence without predictive accuracy. Therefore the memo’s primary measurable job is faithful decision support and institutional learning, not “predict the winner.”

## Stage, sector, and geography limits

Pre-seed memos should be short and hypothesis-heavy; growth memos need cohorts, unit economics, financing, ownership, and scenario sensitivity. Deep tech requires technical milestones, manufacturing/capital/regulatory risks; defense requires mission, procurement, deployment, security, and sovereignty; marketplaces need liquidity; European deals need regulatory, language, labor, financing, and cross-border expansion considerations. One exhaustive software template creates boilerplate and hides the decision crux.

## Proposed Version 3 changes and causal mechanism

1. Restrict the writer to immutable snapshot validation and memo rendering. It consumes—never recomputes—score, contradiction, and trajectory outputs.
2. Add a structured claim ledger: `claim_id`, sentence/section, claim status, evidence IDs, inference basis, confidence, and freshness. This makes grounding machine-testable.
3. Use depth- and ontology-specific templates with a fixed decision core: recommendation, investment case, counter-case, cruxes, falsifiers, evidence coverage, timeline, and what changes the view. This removes boilerplate without losing comparability.
4. Generate steelman-invest and steelman-pass sections independently before synthesis. The causal mechanism is reduced anchoring and visible disagreement.
5. Add resolvable intermediate forecasts with horizon, probability/range, base-rate or analogue, owner, and review date; never one probability of “success.” This creates feedback sooner than an exit.
6. Add a short premortem, prioritized next diligence, and an ex-ante decision log. Later outcome review appends rather than rewrites the original memo.
7. Enforce citation entailment, recommendation parity, snapshot version/hash, and a hard length budget tied to decision depth.

## Rejected imports

- Do not imitate Bessemer or Sequoia prose, section order, or winner-specific weights.
- Do not make the memo an advocacy-only document, a generic 15-section encyclopedia, or a second research agent.
- Do not introduce unsupplied facts, hide weak coverage in narrative, or convert inference into fact.
- Do not use a single “probability of unicorn” or fabricated precision.
- Do not allow later outcomes to overwrite the contemporaneous record.

## Precommitted eval mapping

Maps to C, E, H, I, and J. Freeze at least 12 memo cases across depth and sector, plus stale/broken snapshots and adversarial specialist text. Required: 100% schema and snapshot-hash validity; zero unsupplied material facts; at least 99% material-claim citation recall and 100% citation precision; 100% recommendation parity with the supplied qualification packet; explicit investment case, counter-case, cruxes, falsifiers, coverage, timeline, and change conditions; stale or broken snapshot rejection in every case; and no active content or hidden links. Blind investor review scores decision usefulness, concision, balance, and traceability; Version 3 must average at least 4/5 and improve over Version 2 without exceeding the configured length budget. Paired cases reorder evidence, inject famous names, or add persuasive unsupported prose; the grounded conclusion must remain stable.
