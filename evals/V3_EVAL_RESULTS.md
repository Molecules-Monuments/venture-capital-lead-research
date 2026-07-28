# Version 3.0 frozen-eval results

Evaluation date: 2026-07-23 (final-audit session: all gates re-executed after
the security/correctness remediation; supersedes the 2026-07-22 results)
Authority: `01_PRECOMMITTED_EVALS.md` (frozen before implementation)

The frozen contract requires that environment-dependent live gates "may be
reported BLOCKED, never PASS, without retained evidence." A gate is PASS only
where deterministic executed evidence exists, and BLOCKED where the live or
model-behavioral portion was never run.

| Gate | Status | Evidence | Boundary |
|---|---|---|---|
| A release completeness | PASS | Complete inventory, manifest/pristine verification (every declared file verified, 0 errors), pinned upstream provenance, Version 3.0.0 check | External distribution signature remains an operator trust input. The recorded image digest is regenerated at build. |
| B delegation contract | PASS (structural) · live routing BLOCKED | Closed delegation/return schemas, chief contract, orchestration and fixture tests | Live model routing was never run against a model. |
| C specialist output quality | **BLOCKED** | Twelve closed schemas and 19 contract tests validate output *shape* only | Gate C's core requirement — ≥12 semantic cases per specialist and Cohen's κ ≥ 0.80 — is entirely live-provider and was not executed. Not a pass. |
| D retrieval/memory | PASS (with a caveat) | 7 retrieval contracts; disposable-DB G4 (84/84); verified per-principal preferences and forget cutoffs; 100k/1m benchmark re-run 2026-07-23 | Reference p95 remains below 250 ms. The benchmark seeds confusable clusters (each case a target plus four trigram-close distractors, mean 5 candidates) and scores precision@1 = recall = 1.0 — the resolver ranks each target above its look-alikes, so this now establishes ranking discrimination (former CR-013 item closed). Target-host capacity is a commissioning exercise. |
| E evidence/decision | PASS (structural) · memo usefulness BLOCKED | Typed missing/negative scoring, provenance contracts, database-derived readiness, claim-evidence memo contract, the autonomous claim→verified-fact promotion predicate, and the new cross-lead document-provenance and disguised-URI independence guards (all execution-tested in G4) | Whether the model's memo prose is decision-useful and its citations entail their sources was never measured against a model. |
| F deterministic data/workflow | PASS | G4 84/84 across seven suites; G5 37/37; G7 25/25; migrations 001–017 twice; **eighteen** workflows execution-verified end-to-end across three executing G4 suites (`test_workflow_execution.py` + `test_source_surveillance.py` + `test_research_intelligence.py`), where `test_workflow_execution.py` drives a test step-interpreter over the vcops command path (not the real Lobster engine); the real-engine execution subset and the real deployment path are verified by the G8 gate (re-run 2026-07-23 after the renderer and lifecycle-script changes); recovery authenticity and archive attacks; the stage-first restore contract | Live destructive recovery on a target is a commissioning exercise. |
| G customization safety | PASS | Fail-closed sample, exact `.env` binding, artifact hashes, review/change controls; the fact-promotion strictness knob is reviewed configuration; the renderer refuses lifecycle renders from a non-package env | Jurisdiction/fund choices are explicitly excluded deployment data. |
| H research quality | **BLOCKED** | Source method/roster and structural contracts exist | Research editorial quality is model-behavioral and was not run. The structural contracts pass but the quality gate did not run. |
| I performance/cost | PASS (reference scope, re-run 2026-07-23) | Indexed resolver at 100k companies / 1m facts: all frozen thresholds met on the recorded host | Eventual target capacity/cost is a commissioning exercise. |
| J final adversarial | PASS (deterministic) · live robustness BLOCKED | Deterministic attack suites, the reconciled `FINAL_ADVERSARIAL_CHECK.md` (retained in the internal audit archive, `_internal/`, excluded from the published package), and the 2026-07-23 eight-agent final audit (all confirmed findings fixed and execution-re-verified) | Live provider/model semantic robustness was not run. |

### A7 — reinstated with explicit disposition

Finding A7 (from `01_ADVERSARIAL_SYSTEM_AUDIT.md`, also retained in the excluded `_internal/` archive: "evidence claims exceed what
the deterministic baseline establishes"; required remediation: retain explicit
NOT READY status for the specialist/model behavioral gate, the retrieval-scale
gate, and live channel/recovery gates — "do not turn missing environmental
evidence into a passing result") remains **RETAINED.** Gates C and H are
BLOCKED; Gate D's fuzzy benchmark now uses confusable clusters with a
precision@1 metric (former dataset-artifact item closed); the live
portions of B, E, and J are marked BLOCKED. No missing environmental evidence
is presented as a passing result.

## Final deterministic summary (executed 2026-07-23; counts and G4/G6/G8/scale re-executed 2026-07-28 after the audit remediation)

- 208 offline unittest cases pass, 0 fail, 0 skip; 24/24 offline checks pass.
- Disposable PostgreSQL G4 passes **84/84** across seven suites with migrations
  001–017 applied and registered twice, including step-interpreter execution
  of all eighteen real `.lobster` workflows across the three executing G4 suites
  (the real-engine subset runs under the G8 deployment gate), the autonomous research-intelligence
  lane, and the new boundary tests (proposal INSERT-forgery, disguised-URI
  independence, cross-lead document provenance, watchlist boundary protection,
  verified-fact source requirement, trust-downgrade refusal, cancel
  workflow-binding, quarantine containment for malformed OOXML).
- The real deployment gate (G8) passes on 2026-07-23: `bootstrap.sh` completes
  on the pinned images, the negative credential proof is rejected over TCP,
  and fixed workflows run through real `vcrun`/Lobster leaving a non-empty
  knowledge base.
- The exact-image gate (G6) passes 8/8 against the image rebuilt from the
  current tree.
- All 26 packaged skills pass the skill-system validator; the deterministic
  system audit covers 26 skills, 12 agents, and **18 workflows**, 0 findings.
- Python syntax, POSIX shell syntax, Ruff, fixed-workflow validation, manifest
  currency, and pristine release inventory all pass.

Overall result: **The deterministic package and its deployment path are verified;
the model-behavioral gates (C, H, and the live portions of B/E/J) are BLOCKED and
were never run against a model.** The package is fit for install and deterministic
operation; certification of autonomous decision quality requires the BLOCKED gates
to be commissioned. Deployment activation remains fail-closed.
