name: vc-preference-observe-v3
# SPDX-License-Identifier: Apache-2.0

# Record one bounded per-principal preference observation (e.g. a requester's
# preferred memo length or citation density), gated by a trusted-context
# capability that binds it to a specific channel identity. Preferences are a
# closed allowlist of keys/values — this never stores free-form memory.

args:
  idempotency_key:
    default: ""
  trusted_context:
    default: ""
  preference_key:
    default: ""
  preference_value:
    default: ""
  observation_kind:
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
      --workflow preference-observe
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
  - id: preference_observe
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow preference-observe
      --trusted-context "$LOBSTER_ARG_TRUSTED_CONTEXT"
      --preference-key "$LOBSTER_ARG_PREFERENCE_KEY"
      --preference-value "$LOBSTER_ARG_PREFERENCE_VALUE"
      --observation-kind "$LOBSTER_ARG_OBSERVATION_KIND"
      --idempotency-key "$LOBSTER_ARG_IDEMPOTENCY_KEY"
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
