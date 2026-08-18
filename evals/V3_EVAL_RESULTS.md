# Version 3.0 frozen-eval results

Evaluation date: 2026-07-23 (final-audit session: all gates re-executed after
the security/correctness remediation; supersedes the 2026-07-22 results)
Last full re-execution: **2026-08-18** — counts below are that run's measurement
against this tree rather than figures carried forward, unless the sentence
quoting one names a different source. The retrieval p95 is one such figure: it
is a property of the measuring host, so it is reported against its threshold
rather than as a fixed number.
Authority: `01_PRECOMMITTED_EVALS.md` (frozen before implementation)

The frozen contract requires that environment-dependent live gates "may be
reported BLOCKED, never PASS, without retained evidence." A gate is PASS only
where deterministic executed evidence exists, and BLOCKED where the live or
model-behavioral portion was never run.

Audit passes through 2026-08-04 drove parts of the live path against a real
(sub-1B, local) model and retained the evidence, which is why several rows below
distinguish a *mechanism* half from a *judgement* half. Retained evidence moves
only the mechanism half; no gate here invokes a model, and every judgement half
stays BLOCKED until a production-grade model is commissioned.

| Gate | Status | Evidence | Boundary |
|---|---|---|---|
| A release completeness | PASS | Complete inventory, manifest/pristine verification (every declared file verified, 0 errors), pinned upstream provenance, Version 3.0.0 check | External distribution signature remains an operator trust input. The recorded image digest is regenerated at build. |
| B delegation contract | PASS (structural) · live routing BLOCKED | Closed delegation/return schemas, chief contract, orchestration and fixture tests | An agent turn was driven against a real (sub-1B, local) model, so the turn mechanism a delegation rides on — model resolution, provider reach, and the tool payload, which carries the `sessions_spawn` definition — is proven; an actual chief->specialist spawn was never driven live, and whether routing selects the right specialist is judgement and was never run against a production-grade model. |
| C specialist output quality | **BLOCKED** | Twelve closed schemas and 19 contract tests validate output *shape* only | Gate C's core requirement — ≥12 semantic cases per specialist and Cohen's κ ≥ 0.80 — is entirely live-provider and was not executed. Not a pass. |
| D retrieval/memory | PASS (with a caveat) | 7 retrieval contracts; disposable-DB G4 (97/97); verified per-principal preferences and forget cutoffs; 100k/1m benchmark re-run 2026-08-18 (160/160 cases) | Reference p95 remains below 250 ms. The benchmark seeds confusable clusters (each case a target plus four trigram-close distractors, mean 5 candidates) and scores precision@1 = recall = 1.0 — the resolver ranks each target above its look-alikes, so this now establishes ranking discrimination (former CR-013 item closed). Second caveat: gate D's committed "alias recall on adjudicated fixtures ≥ 95%" threshold is **not computed by any gate** — the scale gate's four numeric thresholds cover overall p95 latency, fuzzy recall, fuzzy precision@1, and mean candidate count, and its 60 exact cases are pass/fail domain-key resolutions (`run_retrieval_scale.py:320-324`), so neither yields an alias-recall rate; G4 proves alias *resolution* on specific adjudicated cases without expressing a rate, so that one number is unmeasured rather than met. Target-host capacity is a commissioning exercise. |
| E evidence/decision | PASS (structural) · memo usefulness BLOCKED | Typed missing/negative scoring, provenance contracts, database-derived readiness, claim-evidence memo contract, the autonomous claim→verified-fact promotion predicate, and the new cross-lead document-provenance and disguised-URI independence guards (all execution-tested in G4) | Whether the model's memo prose is decision-useful and its citations entail their sources was never measured against a production-grade model. |
| F deterministic data/workflow | PASS | G4 97/97 across seven suites; G5 60/60; G7 41/41; migrations 001–018 twice; **eighteen** workflows execution-verified end-to-end across three executing G4 suites (`test_workflow_execution.py` + `test_source_surveillance.py` + `test_research_intelligence.py`), where `test_workflow_execution.py` drives a test step-interpreter over the vcops command path (not the real Lobster engine); the real-engine execution subset and the real deployment path are verified by the G8 gate (re-run 2026-08-18, 5/5 checks); recovery authenticity and archive attacks; the stage-first restore contract | Live destructive recovery on a target is a commissioning exercise. |
| G customization safety | PASS | Fail-closed sample, exact `.env` binding, artifact hashes, review/change controls; the fact-promotion strictness knob is reviewed configuration; the renderer refuses lifecycle renders from a non-package env | Jurisdiction/fund choices are explicitly excluded deployment data. |
| H research quality | **BLOCKED** | Source method/roster and structural contracts exist | Research editorial quality is model-behavioral and was not run. The structural contracts pass but the quality gate did not run. |
| I performance/cost | PASS (structural) · budget adherence BLOCKED | Deterministic: subagent concurrency capped at 3 and the child run timeout at 2700 s in `config/openclaw.json`, asserted by `tests/v3`; the proposed per-task budget (`max_sources`/`max_minutes`) required by `delegation-eval.schema.json`, instance-validated in `tests/v3` (`test_delegation_eval_requires_positive_and_falsification_oracles`); the actual `resource_usage` required by `vc-chief-output.schema.json` and `budget_respected` in `return-assessment.schema.json`, contract-tested in `tests/contracts` | Gate I's frozen per-profile budgets (8/25/60 sources; 15/45/240 minutes), the minimal-route median-specialist regression check, and "no research until source cap" are model-behavioral: `workspaces/shared-skills/research-depth-control/SKILL.md` states that the runtime enforces only child concurrency and run timeout, and no in-package executor measures the rest. The 100k/1m resolver p95 is Gate D's threshold and is reported in that row, not here. Eventual target capacity/cost is a commissioning exercise. |
| J final adversarial | PASS (deterministic) · live robustness BLOCKED | The deterministic attack suites that ship with the package and are re-runnable by any downloader (`tests/g4/`, `tests/g5/`), plus successive internal adversarial audits whose confirmed findings were fixed and execution-re-verified by those same suites | Live provider/model semantic robustness was not run. Untrusted search and document content is fenced at the provider boundary in code, which was verified live; whether a model then *honours* that fencing needs a production-grade model. The audit narratives themselves are internal working documents and are not distributed; the suites are the published evidence. |

### A7 — reinstated with explicit disposition

Finding A7, raised by an internal adversarial audit ("evidence claims exceed what
the deterministic baseline establishes"; required remediation: retain explicit
NOT READY status for the specialist/model behavioral gate, the retrieval-scale
gate, and live channel/recovery gates — "do not turn missing environmental
evidence into a passing result") remains **RETAINED.** Gates C and H are
BLOCKED; Gate D's fuzzy benchmark now uses confusable clusters with a
precision@1 metric (former dataset-artifact item closed); the live
portions of B, E, and J and the budget-adherence half of I are marked BLOCKED.
No missing environmental evidence is presented as a passing result.

## Final deterministic summary

Originally executed 2026-07-23; **the complete matrix was last re-executed on
2026-08-18** against this tree, and against the derived image rebuilt from it
with `docker build --no-cache --pull` on 2026-08-18, after that day's edits to the image-baked `workspaces/` files, the trusted-context extension, `Dockerfile.openclaw` itself, and the host-side recovery-lifecycle and workflow-validation scripts — so the image is derived
from exactly this tree. Every count below is that run's measurement, not a
carried-forward one.

- 348 offline unittest cases pass, 0 fail, 0 skip; 30/30 offline checks pass.
- Disposable PostgreSQL G4 passes **97/97** across seven suites with migrations
  001–018 applied and registered twice, including step-interpreter execution
  of all eighteen real `.lobster` workflows across the three executing G4 suites
  (the real-engine subset runs under the G8 deployment gate), the autonomous research-intelligence
  lane, and the new boundary tests (proposal INSERT-forgery, disguised-URI
  independence, cross-lead document provenance, watchlist boundary protection,
  verified-fact source requirement, trust-downgrade refusal, cancel
  workflow-binding, quarantine containment for malformed OOXML).
- The real deployment gate (G8) passes across all five of its
  checks: throwaway runtime files are generated, `bootstrap.sh` completes on
  the pinned images, the negative credential proof is rejected over TCP, fixed
  workflows run through real `vcrun`/Lobster leaving a non-empty knowledge
  base, and teardown removes every container, volume, and runtime file.
- The exact-image gate (G6) passes 8/8 against an image rebuilt
  from this tree with `docker build --no-cache --pull`, and again against the
  image `bootstrap.sh` builds during the deployment gate.
- The reference retrieval-scale gate passes 160/160 cases: fuzzy
  precision@1 = recall = 1.0 over 100 confusable clusters, mean 5 candidates per
  case, and an overall p95 well inside the frozen 250 ms threshold. The p95 is a
  host- and load-dependent latency rather than a property of the tree — repeated
  runs of this same tree span roughly 40–90 ms — so it is reported against the
  threshold rather than as a fixed figure; see
  `docs/V3_RELEASE_EVIDENCE.md`, "Image digests — regenerate at deployment".
- All 26 packaged skills pass the skill-system validator; the deterministic
  system audit covers 26 skills, 12 agents, and **18 workflows**, 0 findings.
- Python syntax, POSIX shell syntax, Ruff, the ty type checker, fixed-workflow
  validation, manifest currency, and pristine release inventory all pass.

Overall result: **The deterministic package and its deployment path are verified;
the model-behavioral gates (C, H, the live portions of B/E/J, and the
budget-adherence half of I) are BLOCKED and
were never run against a production-grade model.** The live-model mechanism those
gates ride on — resolution, provider reach, tool payloads, and the
timeout/context/watchdog bounds — was exercised against a real model by audit
passes outside this package boundary, but that establishes carriage, not
judgement. The package is fit for install and deterministic operation;
certification of autonomous decision quality requires the BLOCKED gates to be
commissioned. Deployment activation remains fail-closed.
