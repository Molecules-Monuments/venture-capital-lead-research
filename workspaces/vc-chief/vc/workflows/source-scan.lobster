name: vc-source-scan-v3
# SPDX-License-Identifier: 0BSD

# Claim the enabled watchlist sources due this cycle and return the worklist.
# This is the deterministic trigger of automated source surveillance: it records
# the scan attempt and hands the chief the exact due sources to research. The
# research itself (web_search/web_fetch by a read-only specialist) and any
# resulting persistence run through the existing outbound-scout / evidence-record
# workflows, so no browsing or mutation happens inside this lane.
args:
  idempotency_key:
    default: ""
  limit:
    default: "50"
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
      --workflow system.source-scan
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

  - id: source_scan
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow source-scan
      --limit "$LOBSTER_ARG_LIMIT"
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
