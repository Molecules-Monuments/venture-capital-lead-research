name: vc-source-watch-v3
# SPDX-License-Identifier: 0BSD

# Register one watched signal source in the surveillance watchlist, or refresh
# an already-enabled one (the "monitor this website" path). This lane cannot
# re-enable a disabled entry; that is operator-lane only (vcops-operator
# source-watch). Curates configuration only; it starts no research and creates
# no lead.
args:
  idempotency_key:
    default: ""
  source_name:
    default: ""
  source_uri:
    default: ""
  source_class:
    default: ""
  cadence:
    default: ""
  thesis_relevance:
    default: ""
  expected_signal:
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
      --workflow system.source-watch
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

  - id: source_watch
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow source-watch
      --name "$LOBSTER_ARG_SOURCE_NAME"
      --uri "$LOBSTER_ARG_SOURCE_URI"
      --source-class "$LOBSTER_ARG_SOURCE_CLASS"
      --cadence "$LOBSTER_ARG_CADENCE"
      --thesis-relevance "$LOBSTER_ARG_THESIS_RELEVANCE"
      --expected-signal "$LOBSTER_ARG_EXPECTED_SIGNAL"
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
