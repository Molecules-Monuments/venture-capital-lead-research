---
name: governance-lint
description: Validate the supplied Version 3 governance bundle for required contracts, configured inventories, schema consistency, customization, and secret hygiene.
---

# Governance Lint

## Inputs

- Explicit governance bundle root, reviewed customization profile, configured
  agent/skill inventory, canonical schemas, templates, and target version.

## Contract

Validate paths remain inside the bundle root; parse skill frontmatter; enforce unique canonical names/descriptions; check resolver/schema references, score and coverage intervals, approval/notification/state-authority language, required evidence/failure/output sections, customization markers/profile, and absence of likely raw secrets. Compare profile, config, declared, and discovered inventories exactly; do not hard-code the sample counts as universal policy.

## Evidence and failures

Missing files/headings, invalid frontmatter, dangling route, secret pattern, contradictory authority, zero-file scan, or inventory mismatch is a blocker. Report path/line without echoing a secret.

## Output

Return `ok`, `files_checked`, `agent_count`, `skill_count`, `blockers`, `warnings`, and `report_request`. Route report requests to `data-steward`; direct agent-mode mutation is forbidden. Never edit governance, write externally, or send a channel message.

## Reachability (Version 3.0)

The authoritative deterministic check here runs as operator/CI tooling (`scripts/validate_skill_system.py` / `verify_offline.py`), not as a chief runtime action — the chief has no `exec`. As a chief agent-skill this is a review/advisory lens that requests or summarizes the check; the enforcing gate is the release pipeline.
