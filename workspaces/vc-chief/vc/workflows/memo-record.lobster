name: vc-memo-record-v3

# Persist the memo prose produced from the frozen, human-approved snapshot.
# The memo-citation provenance trigger confines every citation to the
# compiled-truth snapshot; the memo lands as draft and its approval remains a
# human decision.
args:
  idempotency_key:
    default: ""
  lead_id:
    default: ""
  evaluation_id:
    default: ""
  compiled_truth_id:
    default: ""
  memo_title:
    default: ""
  memo_markdown:
    default: ""
  citations_json:
    default: ""
  evidence_hash:
    default: ""

steps:
  - id: preflight
    run: /workspaces/vc-chief/vc/bin/vcops-workflow preflight
    timeout_ms: 10000

  - id: workflow_start
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow workflow-start
      --workflow memo-record
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

  - id: memo_persist
    env:
      VCOPS_WORKFLOW_ROW_ID: "$workflow_start.json.workflow_run.id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow memo-save
      --lead-id "$LOBSTER_ARG_LEAD_ID"
      --evaluation-id "$LOBSTER_ARG_EVALUATION_ID"
      --compiled-truth-id "$LOBSTER_ARG_COMPILED_TRUTH_ID"
      --workflow-run-id "$VCOPS_WORKFLOW_ROW_ID"
      --status draft
      --title "$LOBSTER_ARG_MEMO_TITLE"
      --content "$LOBSTER_ARG_MEMO_MARKDOWN"
      --citations "$LOBSTER_ARG_CITATIONS_JSON"
      --evidence-hash "$LOBSTER_ARG_EVIDENCE_HASH"
      --generated-by vcops
    timeout_ms: 30000

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
