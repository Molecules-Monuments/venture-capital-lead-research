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
endpoint, DuckDuckGo search, Firecrawl, Tavily, Slack, Microsoft Teams, Discord,
or Telegram. These integrations are optional and are not sublicensed by this
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
Debian packages installed into the derived image. These dependency graphs
contain packages under multiple permissive licenses, including MIT, Apache-2.0,
BSD variants, ISC, 0BSD, the Python Software Foundation License, and the
PostgreSQL License.

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
