name: vc-inbound-text-intake-v3
# SPDX-License-Identifier: Apache-2.0

# Create a lead from a pure-text inbound submission (founder email, referral,
# warm intro, event follow-up) that carries no document attachment. Mirrors
# outbound-scout's claim -> resolve -> create -> lifecycle, but with an inbound
# origin. Document-bearing inbound goes through inbound-intake / document lanes.
args:
  idempotency_key:
    default: ""
  lead_title:
    default: ""
  company_name:
    default: ""
  company_domain:
    default: ""
  origin_subtype:
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

  - id: workflow_request_claim
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow workflow-request-claim
      --workflow inbound-text-intake
      --idempotency-key "$LOBSTER_ARG_IDEMPOTENCY_KEY"
      --company-name "$LOBSTER_ARG_COMPANY_NAME"
      --company-domain "$LOBSTER_ARG_COMPANY_DOMAIN"
      --lead-title "$LOBSTER_ARG_LEAD_TITLE"
    timeout_ms: 20000

  - id: company_resolve_create
    env:
      VCOPS_WORKFLOW_REQUEST_ID: "$workflow_request_claim.json.workflow_request.id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow company-resolve-create
      --workflow-request-id "$VCOPS_WORKFLOW_REQUEST_ID"
      --workflow inbound-text-intake
      --idempotency-key "$LOBSTER_ARG_IDEMPOTENCY_KEY"
      --name "$LOBSTER_ARG_COMPANY_NAME"
      --domain "$LOBSTER_ARG_COMPANY_DOMAIN"
      --requester-id workflow:inbound-text-intake
      --purpose company_creation
      --max-confidentiality internal
    timeout_ms: 20000

  - id: create_lead
    env:
      VCOPS_COMPANY_ID: "$company_resolve_create.json.company.id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow create-lead
      --company-id "$VCOPS_COMPANY_ID"
      --lead-title "$LOBSTER_ARG_LEAD_TITLE"
      --origin-group inbound
      --origin-subtype "$LOBSTER_ARG_ORIGIN_SUBTYPE"
      --origin-confidence low
      --idempotency-key "$LOBSTER_ARG_IDEMPOTENCY_KEY"
    timeout_ms: 20000

  - id: workflow_start
    env:
      VCOPS_COMPANY_ID: "$company_resolve_create.json.company.id"
      VCOPS_LEAD_ID: "$create_lead.json.lead.id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow workflow-start
      --workflow inbound-text-intake
      --company-id "$VCOPS_COMPANY_ID"
      --lead-id "$VCOPS_LEAD_ID"
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
