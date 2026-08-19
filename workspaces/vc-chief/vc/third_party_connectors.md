# Third Party Connectors

> [MUST_CUSTOMIZE] This file is your connector register: record each approved
> processor/provider, data classes, purpose, terms, region, credentials,
> cost/rate limits and revocation test. The software reads only the entries in
> `config/connectors.json`. An available connector is not standing authority to
> use it; ask your counsel about processor terms if in doubt.

Policy version: `3.0`; connector use requires current terms/rate/retention review and Version 3 scoped approval where paid, sensitive, or login-gated.

## Purpose

This file lists paid, proprietary, API, or MCP-accessible sources. API keys must never be stored here.

## Connector classes

- Company databases: Crunchbase, PitchBook, Dealroom.
- Enrichment platforms: Harmonic, Clay, Crustdata.
- Contact or email tools: Hunter-style tools, only when approved.
- News/search APIs: Tavily, Exa, Brave, Perplexity, or similar.
- Internal proprietary lists or uploaded spreadsheets.

## Connector entry template

- Connector name:
- Access mode: API / MCP / exported file / manual upload
- Credential location: environment variable or secret reference only
- Allowed use:
- Disallowed use:
- Rate limit:
- Cost limit:
- Data retention notes:
- Approval required:

## Rule

No connector may perform outreach, enrichment of private personal contact data, or external writes unless the approval policy explicitly permits it and the operator approves the specific action.

## Runtime (Version 3.0)

Connectors are wired natively through OpenClaw **MCP servers** — no code. The
operator copies `config/connectors.example.json` to `config/connectors.json`
(gitignored, not in the release manifest) and lists each connector as an
`mcp_servers.<name>` entry with a `server` block (a hosted `url` — see the
stdio caveat below) and `grant_to` the research specialists that may query it.
`scripts/render_channel_config.py` injects each enabled entry into the runtime
config's `mcp.servers` and adds `<name>__*` to those agents' `tools.allow`.

- **Secrets** stay as `${VAR}` references (e.g. `Bearer ${CRUNCHBASE_API_KEY}`)
  and are never written into `connectors.json` or the config. OpenClaw resolves
  them at load from the **gateway process environment**, so the variable must
  actually reach that process. The three shipped example connectors
  (`CRUNCHBASE_API_KEY`, `PITCHBOOK_API_KEY`, `DEALROOM_API_KEY`) are pre-wired:
  set them in `.env` and they pass through to the gateway and CLI containers. A
  connector that uses a **different** variable name additionally requires a
  one-time commissioning edit — add that variable to `scripts/check_env.py`
  `ALLOWED_KEYS` (so `.env` validation accepts it) and to the `openclaw-gateway`
  and `openclaw-cli` `environment:` blocks in `docker-compose.yml` (so it reaches
  the process) — mirroring how a non-bundled search provider is commissioned.
- **Grantable specialists only:** `founder-researcher`, `traction-analyst`,
  `market-mapper`, `outbound-scout`, `lead-signal-detector`. The steward, chief,
  and analysis-only roles are refused a connector grant.
- **OpenClaw ships no Crunchbase/PitchBook/Dealroom server.** Point at a
  third-party/official MCP server over a hosted `url`, or at a thin MCP shim
  over the vendor REST API that you host yourself. A stdio `command` entry is
  **not** usable on this deployment as shipped: `docker-compose.yml` runs the
  gateway with `read_only: true` and `HOME=/home/node` on the read-only root,
  so `npx` cannot create its cache and a package-installing stdio server
  cannot start. The renderer copies the `server` block verbatim, so such an
  entry still renders `PASS` and the gateway still reports healthy — the
  failure appears only at `openclaw mcp doctor <name> --probe`. Every shipped
  example in `config/connectors.example.json` is a hosted `url`.
- **Live connectivity is a deployment-commissioning check**, not a package
  guarantee, and the bar is not the probe alone: `openclaw mcp doctor <name>
  --probe` proves the server connects, and invoking a connector tool from a
  granting specialist proves that specialist can reach it. Keep both results
  with the commissioning record. `config/connectors.example.json` records why.
  The config surface is what this release provides.
