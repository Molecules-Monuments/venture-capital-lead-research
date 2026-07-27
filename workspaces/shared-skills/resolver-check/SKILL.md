---
name: resolver-check
description: Verify the configured Version 3 resolver, agent, skill, schema, allowlist, workflow, fixture, customization, and health consistency.
---

# Resolver Check

## Inputs

- Explicit deployment root/config, resolver content, canonical schemas,
  reviewed customization profile, and reports from governance lint, fixtures,
  workflows, and system health.

## Contract

Derive the expected inventory from the reviewed profile and `openclaw.json`;
the shipped package contains 12 roles and 26 discovered skills but those numbers
are not universal fund policy. Require exactly one default/channel-facing chief,
no worker delegation, and exactly one exec-capable steward with the immutable
typed launcher boundary. Match each configured role and resolver target to
config, workspace, canonical output schema, and owning skill allowlist. Verify
referenced policy packets/workflows exist, all four lead-creating workflows
consume an authoritative resolution decision, and route triggers are not
materially ambiguous.

## Evidence and failures

Any difference between reviewed profile/config/discovered inventory, duplicate
ID, dangling file/schema/route, omitted allowlist, missing resolver consumption,
absent workflow, failed dependent report, zero-item inventory, weakened core
invariant, or unresolved trigger collision is blocking.

## Output

Return `ok`, exact `agents`, exact `skills`, `routes_checked`, `blockers`, `warnings`, and `report_request`. Route any persistence request to `data-steward`; direct agent-mode mutation is forbidden. Never modify config/files, write externally, or send channels.

## Reachability (Version 3.0)

The authoritative deterministic check here runs as operator/CI tooling (`scripts/validate_skill_system.py` / `verify_offline.py`), not as a chief runtime action — the chief has no `exec`. As a chief agent-skill this is a review/advisory lens that requests or summarizes the check; the enforcing gate is the release pipeline.
