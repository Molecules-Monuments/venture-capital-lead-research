name: vc-proposal-record-v3
# SPDX-License-Identifier: 0BSD

# Persist one governance proposal (schema change, source-policy change, or skill
# candidate) for later operator review. Records a proposal only; it applies
# nothing. Lead-free system operation.
args:
  idempotency_key:
    default: ""
  proposal_kind:
    default: ""
  title:
    default: ""
  summary:
    default: ""
  content_json:
    default: ""

steps:
  - id: preflight
    run: /workspaces/vc-chief/vc/bin/vcops-workflow preflight
    timeout_ms: 10000

  - id: workflow_start
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow workflow-start
      --workflow system.proposal-record
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

  - id: proposal_record
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow proposal-record
      --kind "$LOBSTER_ARG_PROPOSAL_KIND"
      --title "$LOBSTER_ARG_TITLE"
      --summary "$LOBSTER_ARG_SUMMARY"
      --content "$LOBSTER_ARG_CONTENT_JSON"
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
