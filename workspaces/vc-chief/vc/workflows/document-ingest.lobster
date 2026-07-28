name: vc-document-ingest-v3
# SPDX-License-Identifier: 0BSD

# Ingest one document a channel user attached to their message and run the
# deterministic extraction pipeline on it, gated by a short-lived
# trusted-context capability that binds this run to that exact file. The path
# must be a direct file under OpenClaw's private inbound-media root, where the
# channel plugin stores the attachment; this lane cannot read /inbox, which is
# the separate operator-only `inbound-intake` path. Produces a content-addressed
# evidence extraction (hash + stored bytes); it does not create a lead by itself.

args:
  idempotency_key:
    default: ""
  document_path:
    default: ""
  trusted_context:
    default: ""

steps:
  - id: preflight
    run: /workspaces/vc-chief/vc/bin/vcops-workflow preflight
    timeout_ms: 10000
  - id: document_preview
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow document-preview
      --path "$LOBSTER_ARG_DOCUMENT_PATH"
      --trusted-context "$LOBSTER_ARG_TRUSTED_CONTEXT"
    timeout_ms: 120000
  - id: document_request
    env:
      VCOPS_DOCUMENT_SHA256: "$document_preview.json.document.sha256"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow document-request-claim
      --idempotency-key "$LOBSTER_ARG_IDEMPOTENCY_KEY"
      --document-path "$LOBSTER_ARG_DOCUMENT_PATH"
      --document-sha256 "$VCOPS_DOCUMENT_SHA256"
      --trusted-context "$LOBSTER_ARG_TRUSTED_CONTEXT"
    timeout_ms: 20000
  - id: workflow_start
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow workflow-start
      --workflow document-ingest
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
  - id: document_extract
    env:
      VCOPS_RUN_ID: "$workflow_start.json.workflow_run.id"
      VCOPS_WORKFLOW_REQUEST_ID: "$document_request.json.workflow_request.id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow document-extract
      --path "$LOBSTER_ARG_DOCUMENT_PATH"
      --trusted-context "$LOBSTER_ARG_TRUSTED_CONTEXT"
      --workflow-run-id "$VCOPS_RUN_ID"
      --workflow-request-id "$VCOPS_WORKFLOW_REQUEST_ID"
      --idempotency-key "$LOBSTER_ARG_IDEMPOTENCY_KEY"
      --trust-level untrusted_upload
      --confidentiality confidential
      --retention-class standard
    timeout_ms: 120000
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
