# Governance Lint Contract

Policy version: `3.0`

The lint target is the explicit deployment bundle root. A zero-file scan is failure.

## Hard checks

- exact agreement among the configured agent IDs, resolver routes, canonical
  schemas, and discovered shared skills (the shipped sample is 12 agents/26
  skills, not a universal count). Note that `scripts/validate_skill_system.py`
  checks those against the configuration and its own expected inventory; it does
  **not** open the customization profile, so `agent_profile.roster` and
  `investment_policy.rubric_id` in the profile are reviewed by a human, not by a
  gate;
- each `SKILL.md` has valid `---` frontmatter, canonical `name`, non-empty `description`, and Inputs/Evidence/Output sections;
- resolver agent/skill/policy references exist and match configuration/allowlists;
- scoring weights total 100, bands cover `[0,100]` with no gap/overlap, and missing weight is not redistributed. The specific boundary is **not** fixed here: check the band edges against the deployment's own reviewed `scoring-rubric.v3.json` and the CHECK in `migrations/007_scoring_readiness_gate.sql`, which must agree with each other. (`82/100` is the *shipped sample's* high-priority edge, not a requirement, and it is an edge on the unrounded `final_100` only — `display_5` rounds to a two-point window, so its `4.1` straddles this edge rather than marking it and no band edge can be read off a display value.);
- approval policy requires stable identity, exact scope hash, expiry, single consumption, and atomic action;
- notification policy distinguishes queue/hold/attempt/delivery and requires provider acknowledgement;
- memory/state policy names Postgres, Task Flow SQLite, OpenClaw memory, and Lobster authority separately;
- document policy includes containment, symlink/MIME/macro/encryption and bounded resource controls;
- no raw secret patterns or unresolved template secret values.

## Result

Missing inventory, invalid frontmatter, dangling route/allowlist, contradictory authority, secret finding, absent dependency, or zero/empty critical section is blocking. Report file/line and rule ID without printing secret values. Lint is read-only; fixes require a separate change.
