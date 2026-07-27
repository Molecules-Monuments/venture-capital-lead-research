# Governance Lint Contract

Policy version: `3.0`

The lint target is the explicit deployment bundle root. A zero-file scan is failure.

## Hard checks

- exact agreement among the reviewed customization profile, configured agent
  IDs, resolver routes, canonical schemas, and discovered shared skills (the
  shipped sample is 12 agents/26 skills, not a universal count);
- each `SKILL.md` has valid `---` frontmatter, canonical `name`, non-empty `description`, and Inputs/Evidence/Output sections;
- resolver agent/skill/policy references exist and match configuration/allowlists;
- scoring weights total 100, bands cover `[0,100]` with no gap/overlap, 82/100 and display 4.1 are high priority, and missing weight is not redistributed;
- approval policy requires stable identity, exact scope hash, expiry, single consumption, and atomic action;
- notification policy distinguishes queue/hold/attempt/delivery and requires provider acknowledgement;
- memory/state policy names Postgres, Task Flow SQLite, OpenClaw memory, and Lobster authority separately;
- document policy includes containment, symlink/MIME/macro/encryption and bounded resource controls;
- no raw secret patterns or unresolved template secret values.

## Result

Missing inventory, invalid frontmatter, dangling route/allowlist, contradictory authority, secret finding, absent dependency, or zero/empty critical section is blocking. Report file/line and rule ID without printing secret values. Lint is read-only; fixes require a separate change.
