<!-- SPDX-License-Identifier: 0BSD -->
# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| 3.0.x | Yes |
| 2.x and earlier | No |

This is a self-hosted package. There is no hosted service and no automatic
update channel: patches are published as a new release that the operator
applies with `scripts/update.sh`.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report privately through GitHub's **Report a vulnerability** button on the
*Security* tab of the GitHub repository you obtained this package from
(GitHub Private Vulnerability Reporting). That
channel is preferred because it keeps the report, the fix, and the advisory in
one place and does not disclose the issue before a patch exists.

If that button is not present on the repository, private reporting has not been
enabled yet. In that case contact the repository owner through their GitHub
profile and ask them to enable it, rather than filing a public issue.

Please include:

- the package version (`VERSION`) and the migration set applied,
- which lane the issue is reachable from — host operator, model/agent, fixed
  workflow, or an inbound channel/document,
- the smallest reproduction you have, and
- what an attacker gains.

What to expect:

- **Acknowledgement within 7 days** that the report was received and is being
  looked at.
- **An assessment within 30 days**: accepted with a planned fix, accepted as a
  documented limitation, or declined with reasoning.
- Credit in the release notes if you want it, and coordination on timing before
  any public disclosure.

This project is maintained on a best-effort basis and offers no warranty (see
`LICENSE`, 0BSD). These timelines are intent, not a contractual SLA.

## Scope

**In scope** — anything that lets a party cross a boundary this package claims
to enforce:

- A model/agent lane reaching an operator-only surface: executing a helper
  outside the `bin/agent/` exec allowlist, approving or deciding its own
  proposals, or consuming an approval it was not granted.
- Reading data above the model confidentiality ceiling (`confidential` or
  `restricted` leads, memos, evaluations, or the watchlist) from a model lane.
- Forging or replaying a trusted-context capability token, or minting one for a
  sender/session/document the channel did not actually supply.
- SQL injection, command injection, or path traversal in `vcops.py`,
  `vcrun.py`, the lifecycle shell scripts, or the `vc-trusted-context`
  extension.
- Writing to an append-only history table (`facts`, `fact_sources`,
  `document_facts`, `compiled_truth_facts`, `evaluation_criteria`,
  `memo_citations`, `contradiction_facts`, `trajectory_points`) or otherwise
  defeating a guard trigger as the runtime role.
- Escaping the document intake lane: quarantine bypass, or reaching the host or
  another lead's data through an uploaded PDF/PPTX/XLSX/CSV.
- Recovering plaintext secrets from a backup archive, an image layer, a log, or
  an error message; or defeating the backup HMAC authentication.
- Privilege escalation from the `openclaw_runtime` database role.

**Out of scope** — real, but not a vulnerability in this package:

- Operator misconfiguration that the documentation explicitly warns against —
  most importantly reusing one generated value across several of the six
  deployment secrets, or exposing the gateway beyond loopback without a
  reviewed TLS reverse proxy. `scripts/check_env.py` now rejects reused secrets,
  but a deployment that bypasses the validator is the operator's risk.
- Anything requiring host root, the Docker socket, or an already-compromised
  operator account — those are above this package's boundary by design.
- Model output quality: a wrong, biased, or hallucinated memo, score, or
  citation. The package validates the *shape* of model output, never its
  semantic correctness, and says so in `docs/PRODUCTION_READINESS.md`. This is
  a correctness limitation, not a security boundary.
- Prompt injection that only causes the model to say something wrong, without
  crossing one of the boundaries listed above. Untrusted web and document
  content is *assumed* to be adversarial; the design point is that a
  prompt-injected model still cannot act outside its lane.
- Vulnerabilities in upstream OpenClaw, PostgreSQL, or a third-party connector
  — report those to the respective project. Tell us too if this package's
  configuration makes the impact materially worse.
- Denial of service from an operator-controlled workload (unbounded document
  volume, an over-permissive cron cadence).

## Hardening the deployment

`docs/RUNBOOK.md` §5 (commissioning checklist) and §9 (incident fail-closed
actions) are the operational security surface. The short version:

- Keep `.env` at mode `0600` and never commit it; `scripts/check_env.sh`
  enforces both the mode and the six-secret distinctness rule.
- Generate each of the six secrets independently with `openssl rand -hex 32`.
- Keep `PRIMARY_CHANNEL=none` until the live acceptance matrix has been run.
- Keep the gateway on loopback and terminate TLS in a reviewed proxy.
- Store `BACKUP_HMAC_KEY` outside the backup path — losing it makes every
  existing recovery point unrestorable.
- Run `python3 -B scripts/verify_release.py --pristine` before deploying a new
  package revision.
