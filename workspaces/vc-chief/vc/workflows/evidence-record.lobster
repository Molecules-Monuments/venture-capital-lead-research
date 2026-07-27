name: vc-evidence-record-v3
# SPDX-License-Identifier: 0BSD

# Persist one research claim with its provenance as a submitted_claim, then
# attempt the deterministic corroboration-gated promotion. Nothing on this
# path can mint a verified fact by assertion.
args:
  idempotency_key:
    default: ""
  lead_id:
    default: ""
  evidence_json:
    default: ""

steps:
  - id: preflight
    run: /workspaces/vc-chief/vc/bin/vcops-workflow preflight
    timeout_ms: 10000

  - id: workflow_start
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow workflow-start
      --workflow evidence-record
      --lead-id "$LOBSTER_ARG_LEAD_ID"
      --idempotency-key "$LOBSTER_ARG_IDEMPOTENCY_KEY"
    timeout_ms: 20000

  - id: workflow_running
    env:
      VCOPS_RUN_ID: "$workflow_start.json.workflow_run.run_id"
      VCOPS_EXPECTED_REVISION: "$workflow_start.json.workflow_run.record_version"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow workflow-transition
      --run-id "$VCOPS_RUN_ID"
      --status running
      --expected-revision "$VCOPS_EXPECTED_REVISION"
    timeout_ms: 20000

  - id: evidence_persist
    env:
      VCOPS_WORKFLOW_ROW_ID: "$workflow_start.json.workflow_run.id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow evidence-record
      --lead-id "$LOBSTER_ARG_LEAD_ID"
      --evidence "$LOBSTER_ARG_EVIDENCE_JSON"
      --workflow-run-id "$VCOPS_WORKFLOW_ROW_ID"
    timeout_ms: 20000

  - id: fact_promote
    env:
      VCOPS_FACT_ID: "$evidence_persist.json.fact.id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow fact-promote
      --fact-id "$VCOPS_FACT_ID"
    timeout_ms: 20000

  - id: workflow_succeeded
    env:
      VCOPS_RUN_ID: "$workflow_running.json.workflow_run.run_id"
      VCOPS_EXPECTED_REVISION: "$workflow_running.json.workflow_run.record_version"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow workflow-transition
      --run-id "$VCOPS_RUN_ID"
      --status succeeded
      --expected-revision "$VCOPS_EXPECTED_REVISION"
    timeout_ms: 20000
