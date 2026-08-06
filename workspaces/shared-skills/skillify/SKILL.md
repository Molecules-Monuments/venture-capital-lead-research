---
name: skillify
description: Create a complete pending Skill Workshop package for an explicitly requested or recurring reusable workflow, with tests and release integration defined.
user-invocable: false
---

# Skillify

Convert a durable workflow into a production-quality skill candidate. This skill creates or revises a **pending** OpenClaw Skill Workshop artifact; it never activates or deploys that artifact.

## Inputs

- An explicit operator request to create or improve a skill, or at least two distinct auditable examples of the same recurring workflow gap.
- Representative trigger phrases and negative triggers, intended owner, bounded inputs and outputs, deterministic behavior opportunities, evidence requirements, risks, affected routes and files, and the supplied skill policy.
- For a revision, the exact pending proposal ID returned by `skill_workshop` `inspect`; never guess an ID.

Do not place pitch-deck excerpts, confidential deal facts, credentials, trusted-context capabilities, personal data, or full conversation transcripts in a proposal. Generalize evidence to short non-sensitive references.

## Contract

1. Confirm that a reusable skill is the smallest solution. Do not create a skill for a one-off answer, a user preference, or behavior already owned by a non-overlapping skill.
2. Choose a lowercase hyphen-case name of at most 64 characters and a description that states what the skill does and when it should trigger. The description must be at most 160 UTF-8 bytes.
3. Author the entire procedure body for `proposal_content`. It must contain actionable `Inputs`, `Contract`, `Evidence and failures`, and `Output` sections; exact schemas, commands, and bounds where needed; deterministic helpers for mechanical or security-sensitive work; and explicit prohibitions. OpenClaw adds the YAML frontmatter when it renders the pending proposal.
4. Define any support files as UTF-8 text below only `assets/`, `examples/`, `references/`, `scripts/`, or `templates/`. Keep the complete proposal below the configured 40,000-byte limit. Never include dependencies, binaries, secrets, copied third-party works, or executable side effects.
5. Define production integration before proposing: owner agent, resolver trigger and precedence, configuration entry and agent allowlist delta, canonical schema references, positive/negative/adversarial fixtures, official quick validation, deterministic system validation, release-manifest update, deployment gate, rollback, and documentation changes.
6. For a new skill call `skill_workshop` once with `action=create`, `name`, `description`, full `proposal_content`, bounded `goal`, generalized `evidence`, and reviewed support files. For an existing pending proposal, call `action=inspect` and then `action=revise` with its exact ID. Do not call `action=update`: Skill Workshop only writes skills that live inside the calling agent's own workspace, and every skill in this deployment is loaded from a shared extra directory instead, so the call fails. Change an existing skill through the operator release procedure in the runbook, or propose a differently named skill with `action=create`.
7. Inspect the returned proposal and verify its status is `pending`, its scan reports no blocking finding, and its name, content, support-file inventory, target, and hash match the intended package. A tool error or incomplete inspection is a failed result, not a prose fallback.

## Evidence and failures

Block creation when ownership, trigger boundaries, production integration, tests, rollback, licensing/provenance, or security review is missing. Block overlapping or privilege-expanding skills and any skill that would weaken identity, approval, sandbox, database, channel, evidence, or legal boundaries.

`skill_workshop` actions `apply`, `reject`, and `quarantine` are outside agent authority and are blocked by the deployment hook. Do not ask another agent, use another tool, or write files to bypass that control. Autonomous transcript review remains disabled.

The pending artifact is not release-ready merely because Workshop accepted it. An operator must export it into the repository, update all coupled router/configuration/agent/schema/test/documentation files, run `scripts/validate_skill_system.py`, run the official `skill-creator` validator, rebuild the manifest and image, complete the full release gate, and deploy through code review. Until then it is not active and must not be described as installed.

## Output

Return exactly one object containing `status`, `proposal_id`, `proposal_kind`, `skill_name`, `description`, `draft_hash`, `scan_status`, `trigger_examples`, `negative_triggers`, `owner`, `route_delta`, `allowlist_delta`, `schema_delta`, `tests`, `security_review`, `release_steps`, `rollback`, and `operator_action_required`.

Use `status: "pending_operator_release"` only after a successful create or revise plus inspect (`action=update` is not usable in this deployment — see step 6). Otherwise return `status: "blocked"` with the missing or failed gate. Never claim that a pending proposal is active, production-installed, or approved.
