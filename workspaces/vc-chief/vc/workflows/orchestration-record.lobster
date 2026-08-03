name: vc-orchestration-record-v3
# SPDX-License-Identifier: 0BSD

# Persist one orchestration/delegation audit entry (delegation_eval,
# return_assessment, or chief_output) for a lead's research run, correlated with
# the native Task Flow handles. Append-only; no business state is mutated.
args:
  idempotency_key:
    default: ""
  lead_id:
    default: ""
  record_kind:
    default: ""
  specialist:
    default: ""
  payload_json:
    default: ""
  # Native Task Flow correlation handles (optional; empty => NULL in vcops).
  flow_id:
    default: ""
  flow_revision:
    default: ""
  task_id:
    default: ""
  # Injected by vcrun after argument validation (never caller-supplied):
  # the sha256 of the canonical argument payload, which binds this run row
  # to exactly these arguments so a reused key with changed arguments fails
  # closed instead of silently sharing the earlier run.
  input_digest:
    default: ""

steps:
  - id: preflight
    run: /workspaces/vc-chief/vc/bin/vcops-workflow preflight
    timeout_ms: 10000

  - id: workflow_start
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow workflow-start
      --workflow orchestration-record
      --lead-id "$LOBSTER_ARG_LEAD_ID"
      --idempotency-key "$LOBSTER_ARG_IDEMPOTENCY_KEY"
      --input-digest "$LOBSTER_ARG_INPUT_DIGEST"
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

  - id: orchestration_record
    env:
      VCOPS_WORKFLOW_ROW_ID: "$workflow_start.json.workflow_run.id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow orchestration-record
      --lead-id "$LOBSTER_ARG_LEAD_ID"
      --kind "$LOBSTER_ARG_RECORD_KIND"
      --specialist "$LOBSTER_ARG_SPECIALIST"
      --payload "$LOBSTER_ARG_PAYLOAD_JSON"
      --workflow-run-id "$VCOPS_WORKFLOW_ROW_ID"
      --flow-id "$LOBSTER_ARG_FLOW_ID"
      --flow-revision "$LOBSTER_ARG_FLOW_REVISION"
      --task-id "$LOBSTER_ARG_TASK_ID"
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
