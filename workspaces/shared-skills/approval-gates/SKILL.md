---
name: approval-gates
description: Validate a scoped, expiring, single-use human approval before an external or high-risk action.
---

# Approval Gates

## Inputs

- Immutable action preview: action type, target, lead/company, data, exact payload, risk, and rollback.
- Approval record: opaque token hash, approver stable ID, allowed channel, scope hash, issued/expiry timestamps, and status.
- Caller identity and current time.

## Contract

Require approval for outreach, third-party writes/uploads, spending, sensitive-personal-data collection, destructive changes, schema migrations, public exposure, and expanded automation. Accept only an authenticated approver in an allowed channel: the operator helper binds `--approver` to `VCOPS_OPERATOR_ID` under a constant-time comparison. (`approvals.stable_approver_ids` in the customization profile is a reviewed record, not a runtime allowlist.) Recompute the preview scope hash; require exact match, `pending` status, and `issued_at <= now < expires_at`. Consumption and the governed action must be one atomic database operation on the operator lane (agent-mode and workflow-mode `vcops` cannot request, decide, or consume approval tokens). A token is valid once and cannot authorize a revised, split, broader, or later action.

## Evidence and failures

Return `approved=false` and a reason for missing identity, scope mismatch, expiry, replay, ambiguous language, or policy conflict. Preserve the denied attempt; never infer approval from “yes”, “go ahead”, or an emoji.

## Output

Return `approval_id`, `approved`, `scope_hash`, `expires_at`, `consumed_at`, `action_preview`, and `reason`. This skill never performs the action, sends a channel message, or writes externally. Approval state requires the non-allowlisted operator helper; agent-mode `vcops` cannot create, decide, or consume approvals.
