name: vc-document-lead-intake-v3
# SPDX-License-Identifier: 0BSD

# Create a candidate lead from an already-ingested document extraction: resolve
# the company identity (from the supplied name/domain), open the lead, and bind
# the extraction to it as founding evidence. This is the document-originated
# entry into the research pipeline (paired with document-ingest above).

args:
  idempotency_key:
    default: ""
  trusted_context:
    default: ""
  extraction_id:
    default: ""
  lead_title:
    default: ""
  company_name:
    default: ""
  company_domain:
    default: ""

steps:
  - id: preflight
    run: /workspaces/vc-chief/vc/bin/vcops-workflow preflight
    timeout_ms: 10000
  - id: workflow_request_claim
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow document-association-request-claim
      --idempotency-key "$LOBSTER_ARG_IDEMPOTENCY_KEY"
      --extraction-id "$LOBSTER_ARG_EXTRACTION_ID"
      --lead-title "$LOBSTER_ARG_LEAD_TITLE"
      --company-name "$LOBSTER_ARG_COMPANY_NAME"
      --company-domain "$LOBSTER_ARG_COMPANY_DOMAIN"
      --trusted-context "$LOBSTER_ARG_TRUSTED_CONTEXT"
    timeout_ms: 20000
  - id: company_resolve_create
    env:
      VCOPS_WORKFLOW_REQUEST_ID: "$workflow_request_claim.json.workflow_request.id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow company-resolve-create
      --workflow-request-id "$VCOPS_WORKFLOW_REQUEST_ID"
      --workflow document-lead-intake
      --idempotency-key "$LOBSTER_ARG_IDEMPOTENCY_KEY"
      --name "$LOBSTER_ARG_COMPANY_NAME"
      --domain "$LOBSTER_ARG_COMPANY_DOMAIN"
      --requester-id workflow:document-lead-intake
      --purpose company_creation
      --max-confidentiality internal
    timeout_ms: 20000
  - id: create_lead
    env:
      VCOPS_COMPANY_ID: "$company_resolve_create.json.company.id"
      VCOPS_PROVIDER: "$workflow_request_claim.json.verified_context.provider"
      VCOPS_ACCOUNT_ID: "$workflow_request_claim.json.verified_context.account_id"
      VCOPS_EVENT_ID: "$workflow_request_claim.json.verified_context.event_id"
      VCOPS_SENDER_ID: "$workflow_request_claim.json.verified_context.sender_id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow create-lead
      --company-id "$VCOPS_COMPANY_ID"
      --lead-title "$LOBSTER_ARG_LEAD_TITLE"
      --origin-group inbound
      --origin-subtype channel_document_upload
      --origin-confidence low
      --channel-provider "$VCOPS_PROVIDER"
      --channel-account-id "$VCOPS_ACCOUNT_ID"
      --channel-event-id "$VCOPS_EVENT_ID"
      --channel-message-id "$VCOPS_EVENT_ID"
      --channel-sender-id "$VCOPS_SENDER_ID"
      --idempotency-key "$LOBSTER_ARG_IDEMPOTENCY_KEY"
    timeout_ms: 20000
  - id: workflow_start
    env:
      VCOPS_LEAD_ID: "$create_lead.json.lead.id"
      VCOPS_COMPANY_ID: "$company_resolve_create.json.company.id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow workflow-start
      --workflow document-lead-intake
      --lead-id "$VCOPS_LEAD_ID"
      --company-id "$VCOPS_COMPANY_ID"
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
  - id: document_associate
    env:
      VCOPS_WORKFLOW_REQUEST_ID: "$workflow_request_claim.json.workflow_request.id"
      VCOPS_LEAD_ID: "$create_lead.json.lead.id"
    run: >-
      /workspaces/vc-chief/vc/bin/vcops-workflow document-associate-lead
      --workflow-request-id "$VCOPS_WORKFLOW_REQUEST_ID"
      --extraction-id "$LOBSTER_ARG_EXTRACTION_ID"
      --lead-id "$VCOPS_LEAD_ID"
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
