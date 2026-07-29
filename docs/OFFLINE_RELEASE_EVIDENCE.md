# Historical Version 2 Offline Release Evidence

> This file is retained as the immutable baseline that Version 3.0 challenged.
> It does **not** establish Version 3.0 retrieval, agent-contract,
> customization, or live readiness. See `V3_RELEASE_EVIDENCE.md` for the new
> gate results and residual limitations.

Package version: `2.0.0`  
Evidence date: 2026-07-18  
Ground source: `OpenClaw - Runbook Lead Research.md`, revision 2026-06-10 — an
internal specification document that is not distributed with this package  
OpenClaw: `v2026.7.1` / `2d2ddc43d0dcf71f31283d780f9fe9ff4cc04fe4`  
Lobster: `v2026.6.11` / `86b8cc20a867f18c08ae8e3f4fec9ee7d52bf8c9`

## Release decision

Offline gates G0 through G7 pass. This package may be transferred to a
reviewed target for G8 live acceptance. It is not production-accepted, and no
channel, cron job, model call, external provider, target-host Docker behavior,
or recovery drill is represented as live-tested.

## Retained gate summary

| Gate | Result | Evidence |
|---|---|---|
| G0 | PASS | Baseline, upstream target, two adversarial passes, epics, waves, definitions of done, and hard gates |
| G1 | PASS | 123 materialized ground-source files with content provenance |
| G2 | PASS | Infrastructure/config/security validator; zero errors and warnings |
| G3 | PASS | 14/14 agent, skill, routing, scoring, and governance checks |
| G4 | PASS | 9/9 groups; 5 semantic, 10 hostile-document, 7 database-invariant, and 9 helper/CLI tests |
| G5 | PASS | 8/8 workflow/upstream checks; 22 adversarial workflow/runner unit tests |
| G6 | PASS | 9/9 exact-schema/security checks for Slack, Teams, Discord, and Telegram |
| G7 | PASS | 11/11 aggregate inventory, syntax, manifest, security, inert-render, workflow, infrastructure, and recovery checks |
| G8 | NOT RUN | Exact host/runtime, credentials, model/provider, selected live channel, persistence, and clean-target restore |

The source QA JSON is retained outside this deployable directory in the
derivation archive (`_internal/`, excluded from the published package).
`manifest.json` binds the reviewed files in this directory by SHA-256, size,
and executable bit for self-consistency; other permission bits are deliberately
not part of the contract because Git does not carry them. It is not an external
authenticity root; confirm separately that the commit you hold is the one the
project published, as described in `README.md` under the developer quick start.

## Final adversarial closure

The last top-down, bottom-up, exact-upstream, workflow/domain, and
recovery/security passes found and corrected:

- OpenClaw bootstrap writes against immutable workspaces;
- Lobster plain-version output mismatch;
- destructive continuation before durable cancellation reconciliation;
- missing Postgres reconciliation for bounded runner failures;
- intake mutation before whole-request idempotency was committed;
- compiled truth that omitted contradicted/history state from its frozen packet;
- caller-controlled final decision guards;
- recovery source/destination containment defects;
- same-version restore and newer-ledger incompatibility gaps; and
- pristine inventory and manifest-authenticity wording gaps.

No blocker/high finding remains in the final offline package. G8-owned medium
residuals are explicit in `RUNBOOK.md`: real image/plugin behavior, OpenClaw
doctor/deep audit, provider/model calls, effective live tool behavior, the
selected channel's complete matrix, host egress/monitoring, and isolated full
recovery.

## Operator hard stop

Keep `PRIMARY_CHANNEL=none` and cron disabled until every applicable G8 row in
`RUNBOOK.md` and `CHANNELS.md` passes with retained target-host evidence. Any
failed, missing, or unretained live check is a hard failure.
