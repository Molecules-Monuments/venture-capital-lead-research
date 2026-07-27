# Market Mapper — Version 3.0 Research Dossier

All web sources were accessed 2026-07-20. Evidence grades use `research/00_SOURCE_METHOD_AND_ROSTER.md`.

## Current contract and invoked skills

Version 2 maps category, customer, buyer, budget owner, value-chain position, competitors, substitutes, timing, defensibility evidence, and risks. It correctly distinguishes direct competitors, adjacent alternatives, internal build, status quo, and non-consumption, and requires counterevidence for `why_now`. Its seven skills are `lead-memory-lookup`, `evidence-research`, `knowledge-modeling`, `contradiction-check`, `trajectory-check`, `research-depth-control`, and `approval-gates`.

The strongest design choice is refusing keyword-generated competitor lists and unsupported moat claims. The largest omission is opportunity magnitude: the role prohibits TAM/SAM/SOM rather than distinguishing evidence, bottom-up assumptions, and scenarios. It also lacks a structured wedge-to-expansion path, value capture, market structure, distribution/GTM feasibility, procurement/adoption friction, incumbent response, and “market could remain small” case. `trajectory-check` and `research-depth-control` broaden a no-delegation research worker, while authoritative memory remains inaccessible.

## Quantitative capabilities and human analogue

This is one of only two specialists labeled `VC_PRIMARY_MODEL`, although primary and fast currently resolve to the same model. There is no competitor-recall benchmark, source budget telemetry, entity-resolution service, or deterministic scenario calculator. The nearest human is a sector-focused VC principal combining desk research, customer/expert calls, market structure, bottom-up sizing, and an investment-return question: can this wedge support a sufficiently large outcome at plausible share and economics? Public sources can map observable vendors and buyers; they cannot establish private win rates, willingness to pay, roadmap, churn, procurement politics, or future category boundaries.

## Practitioner approaches worth testing

**1. Narrow, urgent wedge with a path outward.** Paul Graham argues that strong startup ideas often begin with a small group that wants a product intensely, provided there is a credible path into adjacent users or markets ([How to Get Startup Ideas](https://paulgraham.com/startupideas.html); [Do Things That Don’t Scale](https://www.paulgraham.com/ds.html?viewfullsite=1)). The mechanism is concentrated demand and fast learning, not small TAM. This is **grade C for an early consumer/software heuristic, D for causal performance**: founder/investor essay, selected exemplars, no denominator, weak transfer to procurement-heavy and capital-intensive markets.

**2. Market-structure-specific analysis.** Bill Gurley’s marketplace framework examines experience delta, two-sided pull, fragmentation, payment flow, frequency, take rate, network effects, and the risk that supply aggregation never creates demand ([Benchmark/Above the Crowd](https://abovethecrowd.com/2012/11/13/all-markets-are-not-created-equal-10-factors-to-consider-when-evaluating-digital-marketplaces/)). Benchmark’s eBay and Uber association makes the framework worth studying, but not causally validated. It is **grade B/C as a reproducible marketplace checklist, D as return attribution**. Its key import is ontology-specific market structure, not a universal marketplace bonus.

**3. Buyer-led bottom-up opportunity.** Former Segment operators describe identifying ICP, buyer, use cases, business value, buying process, obtainable share, and average spend, then triangulating with external data ([a16z Segment guide](https://a16z.com/getting-ready-to-move-upmarket/)). a16z separately warns that GTM should be learned from how an early market buys rather than imposed prematurely ([Market Annealing](https://a16z.com/market-annealing-getting-to-10m-arr-in-very-early-markets/)). These are **grade C** practice exemplars: concrete and falsifiable, but self-reported selected operating cases.

These approaches disagree productively. A giant present market is not necessary for a valuable wedge, but a narrow wedge without an expansion mechanism cannot support venture returns. Version 3 should represent both current reachable market and contingent expansion, not choose one slogan.

## Independent evidence and counterevidence

Kaplan, Sensoy, and Strömberg find that business lines remained relatively stable among 50 VC-backed companies progressing toward public-company stages, while managers changed more often ([paper](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=657721)). This is **grade B/C** and supports treating the underlying opportunity as material, but its success-selected, old IPO sample cannot settle early pivots or modern AI categories.

A meta-analysis of 219 estimates from 41 studies finds that market size affects entry differently by niche, high-tech, incumbent, and period context ([European Journal of Marketing](https://www.sciencedirect.com/org/science/article/abs/pii/S0309056617001022)). This is **grade B** for the contingency claim, not startup return prediction. Research on new-product forecasting highlights both epistemic and reality-changing uncertainty and recommends combining scenarios with forecasts rather than pretending to know one future ([Derbyshire & Giovannetti](https://www.sciencedirect.com/science/article/pii/S0040162516302980)); **grade B/C**, with new-product rather than VC-deal external validity.

Academic and practitioner literature also suffer from endogenous categories: successful products can expand or redefine the market being “measured.” Third-party market reports are often vendor-funded, repeat one another, and describe spend categories that do not map to the startup’s reachable buyer. That failure mode is more dangerous than simply missing a TAM number.

## Stage, sector, and geography limits

Pre-seed work should establish urgent user/problem, plausible buyer, status quo, and expansion hypotheses—not a precise ten-year forecast. Series A can use observed pricing, sales cycles, win/loss evidence, and segment-level unit economics. Marketplaces require liquidity and disintermediation; open source requires user-to-buyer conversion; defense requires mission, budget line, procurement, deployment, and sovereignty; deep tech requires technical substitution, manufacturing, regulation, and capital intensity. European markets fragment by language, regulation, procurement, labor, and data residency. US category and price benchmarks cannot silently define European opportunity.

## Proposed Version 3 changes and causal mechanism

1. Add `market_model_type` and ontology-specific questions. This prevents applying SaaS or marketplace heuristics everywhere.
2. Separate `initial_wedge`, `reachable_market_now`, `expansion_paths`, `expansion_dependencies`, and `terminal_market_hypothesis`. This reconciles narrow-wedge learning with venture-scale potential.
3. Add buyer journey, budget source, procurement, adoption blocker, switching cost, distribution channel, value capture, and incumbent-response fields. These connect market attractiveness to executable company strategy.
4. Permit bottom-up scenario ranges only with explicit customer counts, spend/value assumptions, obtainable share, time horizon, sources, and sensitivity; deterministic arithmetic produces numbers. Third-party TAM remains a contextual claim.
5. Require inclusion reasons and exclusion reasons for competitors, plus a dated evidence graph. This improves precision and makes omissions reviewable.
6. Add `counter_case`, `market_could_remain_small_because`, and decisive customer/expert questions. This reduces category hype and confirmation bias.

## Rejected imports

- No generic “large TAM” score, top-down report copied as fact, or arbitrary 1% share calculation.
- No keyword competitor dump, famous-investor/category heat bonus, or “no competitors means opportunity” inference.
- No universal monopoly, network-effect, or market-tipping assumption.
- No adoption forecast without procurement, distribution, willingness-to-pay, and incumbent-response assumptions.
- No scenario value promoted to verified fact or scoring coverage.

## Precommitted eval mapping

Maps to gates C, D, E, H, I, and J. Freeze cases across enterprise SaaS, developer infrastructure, marketplace, consumer, defense, regulated vertical, and deep tech. Required: at least 90% precision and 90% recall for adjudicated competitor/substitute classes; 100% citations for buyer, budget, timing, and competitor inclusion; 100% arithmetic/assumption traceability for scenarios; explicit counter-case and wedge/expansion dependencies in every accepted map; zero unsupported TAM or market-share facts; and 100% budget compliance. Paired fixtures hold the category label constant while changing buyer, budget, procurement, or distribution; the map must change. Another pair presents a huge report TAM with weak reachable demand versus a narrow wedge with evidenced expansion; the agent must not reward the headline number. Geography perturbations test regulation, currency, language, and data-residency transfer.
