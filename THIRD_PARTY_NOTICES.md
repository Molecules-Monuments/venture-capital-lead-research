# Third-party notices

The 0BSD license in `LICENSE` applies to original OpenClaw Lead Research
project material. It does not replace or override the licenses, notices,
trademarks, service terms, or acceptable-use policies of third-party software
and content.

This repository configures, depends on, or derives a runtime image from the
following principal projects:

## OpenClaw

- Project: https://github.com/openclaw/openclaw
- Reviewed release: `2026.7.1`
- Reviewed commit: `2d2ddc43d0dcf71f31283d780f9fe9ff4cc04fe4`
- License: MIT
- Copyright notice in the reviewed upstream license: Copyright (c) 2026
  OpenClaw Foundation
- License text: https://github.com/openclaw/openclaw/blob/v2026.7.1/LICENSE

The derived Docker image uses the pinned official OpenClaw image recorded in
`manifest.json`, `.env.example`, and `Dockerfile.openclaw`. OpenClaw names and
marks belong to their respective owner. This project is independent and is not
presented as an official OpenClaw Foundation product.

The same derived image contains the OpenClaw `2026.7.1` DuckDuckGo search,
Ollama provider, and Telegram channel extensions supplied by that upstream
release, plus the exact `@openclaw/firecrawl-plugin@2026.7.1`,
`@openclaw/tavily-plugin@2026.7.1`, `@openclaw/slack@2026.7.1`,
`@openclaw/msteams@2026.7.1`, and `@openclaw/discord@2026.7.1` packages locked
in `runtime-packages/package-lock.json`. They remain OpenClaw components under
the upstream repository's MIT license. The local `vc-trusted-context` extension is
original project material covered by this repository's 0BSD license.

## Optional external model, search, and channel services

The runtime can be configured to call OpenAI, Ollama, a reviewed custom model
endpoint, Slack, Microsoft Teams, Discord, or Telegram. For search it accepts
DuckDuckGo, Firecrawl and Tavily — the three whose plugins the derived image
already carries — and also Brave, Perplexity, Exa, a self-hosted SearXNG
instance, or Parallel in its key-free `parallel-free` form. Those last five are
native to the harness but **not bundled**: selecting one additionally requires
pinning its plugin package in `runtime-packages/` and rebuilding the image, which
brings that package's own licence into scope alongside the provider's terms.
SearXNG is a self-hosted endpoint the operator supplies rather than a vendor
API, so its terms are whatever that deployment's own are.
`config/connectors.example.json` additionally ships pre-wired
entries for the **Crunchbase**, **PitchBook**, and **Dealroom** research
connectors, each with a credential slot in `.env.example` and a pass-through in
`docker-compose.yml`; they are disabled until an operator enables them. These
three are commercial data vendors whose licences typically restrict
redistribution, derived datasets, and retention of the records they return —
review the contract before enabling one, because the terms bind what this
system may persist in `facts` and `evidence_artifacts`. These integrations are optional and are not sublicensed by this
repository. Their software, hosted APIs, content, names, quotas, privacy terms,
acceptable-use rules, and commercial terms remain governed by the applicable
provider. Operators must review those terms and the treatment of prompts,
documents, identifiers, search queries, and results before activation. Ollama
can keep model inference on operator-controlled infrastructure, but local
deployment does not by itself make the surrounding channel, search, logging,
or operating environment private.

## Lobster

- Project: https://github.com/openclaw/lobster
- Reviewed release: `2026.6.11`
- Reviewed commit: `86b8cc20a867f18c08ae8e3f4fec9ee7d52bf8c9`
- Package: `@clawdbot/lobster@2026.6.11`
- License: MIT
- Copyright notice in the reviewed upstream license: Copyright (c) 2026
  Vignesh
- License text: https://github.com/openclaw/lobster/blob/v2026.6.11/LICENSE

## PostgreSQL

- Project: https://www.postgresql.org/
- Container release: `17.10-bookworm`, pinned by digest
- License: PostgreSQL License
- License text: https://www.postgresql.org/about/licence/

## Python, npm, Debian, and container dependencies

The complete pinned Python graphs are in `requirements.lock` and
`requirements-dev.lock`. The pinned npm graph is in
`runtime-packages/package-lock.json`. `Dockerfile.openclaw` records direct
Debian packages installed into the derived image. Most entries in those graphs
are under permissive licenses — MIT, Apache-2.0, BSD variants, ISC, 0BSD, the
Python Software Foundation License, and the PostgreSQL License. The Python
graph is not permissive-only: `psycopg` and `psycopg-binary` 3.2.13, pinned in
`requirements.lock` and installed into the image's `/opt/vcops-venv` by
`Dockerfile.openclaw`, are LGPL-3.0-only
(https://www.gnu.org/licenses/lgpl-3.0.html). They are the only non-permissive
distributions in either Python lockfile, and redistributing the image or that
venv carries the LGPL's notice and license-text obligations for them.

The derived image also inherits the base the pinned OpenClaw image is built on
— `docker.io/library/node:24-bookworm-slim`, recorded in that image's own
`org.opencontainers.image.base.name`/`.base.digest` labels — plus the Debian
packages `Dockerfile.openclaw` installs. That base contributes **Node.js
24.16.0** with npm, corepack, yarn and pnpm, installed from upstream tarballs
into `/usr/local` rather than from apt, so they appear in neither Python
lockfile, neither npm lockfile, nor `dpkg`; their required notices (Node.js MIT
plus the bundled OpenSSL, ICU, V8, c-ares, llhttp and zlib notices) ship only as
`/usr/local/LICENSE` inside the built image, and a redistributor must preserve
that file. The Debian layer beneath it is **not** permissive-only: it
contains substantial GPL/LGPL material — `poppler-utils` is GPL-2/GPL-3, and
the majority of the shipped Debian packages declare a GPL, LGPL, or MPL
licence. Redistributing the built image therefore carries copyleft source-offer
obligations — from this Debian material, from the LGPL Python distributions
named above, and from weak-copyleft npm material in the runtime layers — that
the permissive licenses above do not cover. Treat these as the classes that
require attention, not as a closed inventory: establish the actual obligation
set from the built image rather than from this list.

Lockfiles identify versions and integrity hashes; they are not a substitute
for preserving required copyright notices or license texts in a distributed
binary/image. Before redistributing a derived image or commercial product,
generate and review a software bill of materials and the license/notices from
the exact built artifact. Preserve every notice required by those components.

## Research sources and linked content

The venture, academic, standards, security, and practitioner sources linked in
`research/00_SOURCE_METHOD_AND_ROSTER.md` remain the property of their authors
and publishers. The repository summarizes and cites ideas; it does not license
third-party articles, reports, trademarks, datasets, or other linked content
for redistribution.

This notice is informational and is not legal advice. Downstream users and
distributors are responsible for reviewing the exact artifact and satisfying
all applicable third-party obligations.
