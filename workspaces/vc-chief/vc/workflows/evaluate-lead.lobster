name: vc-evaluate-lead-v3
# SPDX-License-Identifier: Apache-2.0

# Compile the lead's accepted evidence into a frozen truth snapshot, score it
# against the reviewed rubric, and pause at the single human approval checkpoint
# before persisting the evaluation. This is the ONE fixed workflow with an
# approval gate: the investment decision stays human-gated, and the memo is
# persisted (via memo-record) only from this human-approved frozen snapshot.

args:
  idempotency_key:
    default: ""
  lead_id:
    default: ""
  criteria_json:
    default: ""
  decision_context_json:
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

  - id: lead_show
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow lead-show
      --lead-id "$LOBSTER_ARG_LEAD_ID"
    timeout_ms: 20000

  - id: workflow_start
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow workflow-start
      --workflow evaluate-lead
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

  - id: prequalify
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow prequalify
      --criteria "$LOBSTER_ARG_CRITERIA_JSON"
      --decision-context "$LOBSTER_ARG_DECISION_CONTEXT_JSON"
    timeout_ms: 20000

  # This payload is the operator's only view of the pause: it has to carry both
  # what they are approving and the run identity, because rejecting or
  # cancelling requires --run-id and --expected-revision and nothing else
  # surfaces them once the run is paused (docs/WORKFLOWS.md).
  #
  # It is the one place this package composes references inside a larger string
  # rather than using a whole-value reference. No reference surface in the
  # pinned runtime fails closed on a missing field — a known step with a
  # missing path resolves to nothing on every surface — but the composed form
  # is worse still, because the empty value disappears inside otherwise valid
  # JSON rather than arriving as an empty argument the helper can reject. That
  # is why the form is normally forbidden for identifiers. It is safe here and
  # only here: the two run-identity fields come from `workflow_running`, a
  # transition step that cannot succeed without returning them, and
  # `evaluation` comes from `prequalify`, whose helper (`cmd_evaluation_preview`)
  # returns that key unconditionally — so the run never reaches this gate with
  # any of them missing. Each referenced path is also on the validator's
  # reviewed-path allowlist.
  - id: persist_approval
    approval:
      prompt: Persist this evaluation and its new compiled-truth snapshot?
    stdin: >-
      {"workflow_run":{"run_id":"$workflow_running.json.workflow_run.run_id","record_version":$workflow_running.json.workflow_run.record_version},"evaluation":$prequalify.json.evaluation}

  - id: compiled_truth
    env:
      VCOPS_WORKFLOW_ROW_ID: "$workflow_start.json.workflow_run.id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow compiled-truth
      --lead-id "$LOBSTER_ARG_LEAD_ID"
      --workflow-run-id "$VCOPS_WORKFLOW_ROW_ID"
      --min-confidence 0.7
      --policy-version 3.0
      --compiled-by vcops
    condition: "$persist_approval.approved"
    timeout_ms: 30000

  - id: evaluation_save
    env:
      VCOPS_WORKFLOW_ROW_ID: "$workflow_start.json.workflow_run.id"
      VCOPS_COMPILED_TRUTH_ID: "$compiled_truth.json.snapshot.id"
      VCOPS_EVIDENCE_HASH: "$compiled_truth.json.snapshot.evidence_packet_hash"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow evaluation-save
      --lead-id "$LOBSTER_ARG_LEAD_ID"
      --workflow-run-id "$VCOPS_WORKFLOW_ROW_ID"
      --compiled-truth-id "$VCOPS_COMPILED_TRUTH_ID"
      --criteria "$LOBSTER_ARG_CRITERIA_JSON"
      --decision-context "$LOBSTER_ARG_DECISION_CONTEXT_JSON"
      --status final
      --policy-version 3.0
      --evidence-hash "$VCOPS_EVIDENCE_HASH"
      --evaluated-by vcops
    condition: "$persist_approval.approved"
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
    condition: "$persist_approval.approved"
    timeout_ms: 20000
