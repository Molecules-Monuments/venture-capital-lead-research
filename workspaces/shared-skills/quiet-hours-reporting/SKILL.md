---
name: quiet-hours-reporting
description: Classify a proposed notification without sending it; Version 3 ships internal-log persistence only and no proactive dispatcher.
---

# Quiet-Hours Reporting

## Inputs

- Subject/body summary, severity, related lead/approval IDs, timezone, policy window, idempotency key, and supplied notification policy. Do not accept a provider destination as authority to send.

## Contract

Version 3 can retain an operator-created `internal_log` record only. It ships no
proactive provider dispatcher, digest scheduler, or delivery worker. `batched`,
`normal`, and `urgent` are classifications for a future separately gated
component, not executable delivery states. Same-thread replies to an allowlisted
current requester follow the channel policy and do not use this skill.

## Evidence and failures

Record the classification and policy/time calculation. Invalid timezone,
unapproved bypass, or any request for proactive provider delivery fails closed.
Never report attempted, sent, or delivered because this release has no worker
that can establish those states.

## Output

Return the proposed internal-log payload, classification, policy reason,
`idempotency_key`, and `dispatcher_required: true` for any proactive delivery.
The skill never sends. Agent-mode `vcops` is read-only, so an operator must
create any internal-log record through a non-allowlisted path.
