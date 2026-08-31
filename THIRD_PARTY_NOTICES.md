# Third-party notices

The Apache License, Version 2.0 in `LICENSE` applies to the original material of
the Venture Capital Lead Research System, Copyright 2026 Molecules & Monuments
GmbH. `NOTICE`
carries the attribution notice that Apache-2.0 §4(d) obliges a redistributor to
pass on with a derived work; this document is a separate surface and covers
third-party material. Neither file replaces or overrides the licenses, notices,
trademarks, service terms, or acceptable-use policies of third-party software
and content.

This repository configures, depends on, or derives a runtime image from the
following principal projects:

## OpenClaw

- Project: https://github.com/openclaw/openclaw
- Reviewed release: `2026.8.1`
- Reviewed commit: `ea806575e6450e4d1efdfc72c19f04be982a1b9b`
- License: MIT
- Copyright notice in the reviewed upstream license: Copyright (c) 2026
  OpenClaw Foundation
- License text: https://github.com/openclaw/openclaw/blob/v2026.8.1/LICENSE
- Upstream's own third-party notices:
  https://github.com/openclaw/openclaw/blob/v2026.8.1/THIRD_PARTY_NOTICES.md

The reviewed upstream `LICENSE` does not end at the MIT warranty clause. Its
last line — "Third-party notices for incorporated or adapted code are recorded
in THIRD_PARTY_NOTICES.md." — is why GitHub's classifier reports the upstream
repository as `NOASSERTION` rather than MIT, and it carries a notice this
document would otherwise omit: portions of OpenClaw are adapted from **Pi /
pi-mono**, and OpenClaw depends on `@earendil-works/pi-tui` for terminal UI
rendering. Both are MIT, **Copyright (c) 2025 Mario Zechner**
(https://github.com/earendil-works/pi-mono). MIT obliges a redistributor to
carry that notice alongside the OpenClaw Foundation's.

Do not expect to rediscover it from the built artifact. Measured in
`vc-lead-research:3.0.1`: `@earendil-works/pi-tui` 0.84.2 is present under
`/app/node_modules/`, ships no licence file of its own, and carries in its
`package.json` only `"license": "MIT"` and `"author": "Mario Zechner"` — the
holder's name, but not the copyright notice MIT requires be reproduced — while
upstream's `LICENSE` and `THIRD_PARTY_NOTICES.md` are not in the image at all.
A software bill of materials generated from the image therefore yields
`pi-tui`, MIT, and no notice to reproduce, and cannot see the adapted-from-Pi
source portion at all. The upstream file linked above is the only route to
that obligation. Lobster is not affected: its `LICENSE` is plain MIT and that
repository publishes no third-party notices file.

The derived Docker image uses the pinned official OpenClaw image recorded in
`manifest.json`, `.env.example`, and `Dockerfile.openclaw`. OpenClaw names and
marks belong to their respective owner. This project is independent and is not
presented as an official OpenClaw Foundation product.

The same derived image contains the OpenClaw `2026.8.1` Ollama provider and
Telegram channel extensions supplied by that upstream release, plus the exact
`@openclaw/duckduckgo-plugin@2026.8.1`, `@openclaw/firecrawl-plugin@2026.8.1`,
`@openclaw/tavily-plugin@2026.8.1`, `@openclaw/slack@2026.8.1`,
`@openclaw/msteams@2026.8.1`, and `@openclaw/discord@2026.8.1` packages locked
in `runtime-packages/package-lock.json`. DuckDuckGo moved between those two
sentences with this release: `2026.8.1` no longer bundles it as an image
extension, so it is now a pinned npm plugin like Firecrawl and Tavily. The
vendor, endpoint and licence are unchanged. They remain OpenClaw components under
the upstream repository's MIT license. The local `vc-trusted-context` extension is
original project material covered by this repository's Apache-2.0 license.

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
24.16.0** with npm 11.13.0, corepack 0.35.0 and yarn 1.22.22, installed from
upstream tarballs rather than from apt (third bullet). None of them appear in either Python
lockfile, either npm lockfile, or `dpkg`, and their notices are not gathered
into one file. Measured against the pinned `OPENCLAW_IMAGE` base
(`ghcr.io/openclaw/openclaw:2026.8.1`) and confirmed identical in the image
built from it: the derived build installs into `/opt` and through `apt`, and
adds nothing under `/usr/local`, so the counts below are the base's. That
equality was itself measured — on the previous release the base and
`vc-lead-research:3.0.0` both returned the same three numbers:

- Node.js, npm and corepack unpack into `/usr/local`, and their own notices —
  Node.js MIT plus the bundled OpenSSL, ICU, V8, c-ares, llhttp and zlib texts,
  npm's own section including its Artistic-2.0 text, and corepack's — are
  aggregated in `/usr/local/LICENSE`. That aggregate is the only match within
  two levels of `/usr/local` (`find /usr/local -maxdepth 2 -iname
  'LICEN[SC]E*'`), which is not the same claim as its being the only licence
  file under `/usr/local`. Dropping the depth limit,
  `find /usr/local -iname 'LICEN[SC]E*' | wc -l` returns **173**: the
  aggregate, 151 under `/usr/local/lib/node_modules/npm`, 20 under
  `/usr/local/share/corepack`, and corepack's own
  `/usr/local/lib/node_modules/corepack/LICENSE.md`. On the previous
  `2026.7.1` base the same command returned 172, split 148/22 — the totals move
  with every base bump, which is why they are re-measured rather than carried
  forward. npm's and corepack's standalone copies duplicate text the aggregate
  already carries; the other **170** are npm's bundled dependencies and the
  vendored pnpm tree. Do not assume the aggregate stands
  in for them — `grep -ci yallist` and `grep -ci sigstore` against
  `/usr/local/LICENSE` both return `0`.
- **yarn 1.22.22** (BSD-2-Clause) is unpacked into `/opt/yarn-v1.22.22`, 5.2 MB
  outside `/usr/local`, and carries its own `LICENSE` there. This one *is*
  identical in the pinned base. `/usr/local/LICENSE` does not cover it:
  `grep -ci yarn /usr/local/LICENSE` returns `0`.
- **pnpm 12.1.0** (MIT) ships **in the pinned base**, materialised through
  corepack at `/usr/local/share/corepack/v1/pnpm/12.1.0` and reachable as
  `/usr/local/bin/pnpm`, where `pnpm --version` answers `12.1.0` under
  `docker run --network none` — so the bytes are in the image rather than
  fetched on first use. Earlier revisions of this document said pnpm was absent
  from the base and arrived with the build; that was measured against a
  different image and is wrong for the one this package pins, on `2026.7.1` as
  well as `2026.8.1`. It makes no difference to the obligation, only to where
  you look. Its own `LICENSE` and the licence files of its bundled dependencies
  under `dist/node_modules/` are the 20 files that tree contributes.
  `grep -ci pnpm /usr/local/LICENSE` returns `0`.

A redistributor who preserves `/usr/local/LICENSE` alone therefore ships yarn,
pnpm, and npm's bundled dependencies with no notice. Preserve the licence files
under `/opt/yarn-v1.22.22`, `/usr/local/lib/node_modules`, and
`/usr/local/share/corepack` as well, and re-run the commands above —
unbounded, not depth-limited — whenever the base image pin or the build moves:
the layout and the counts are properties of those, not guarantees of this
document.

The Debian material in this image is **not** permissive-only: it
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

This project's own material adds to that set rather than being covered by it.
Apache-2.0 §4 requires a redistributor of this software, or of a work derived
from it, to include a copy of `LICENSE`, retain the copyright, patent,
trademark, and attribution notices in the source they carry, mark every file
they changed as changed, and include a readable copy of the attribution notices
in `NOTICE` in at least one of the three places §4(d) allows — a NOTICE file
shipped with the derived work, its documentation, or the display it uses for
such notices. The derived image
this repository builds carries neither file — `.dockerignore` admits only the
build inputs — so a redistributor of that image must add them to the artifact
they ship.

## Contributor Covenant

- Project: Contributor Covenant, version 2.1
- Text: https://www.contributor-covenant.org/version/2/1/code_of_conduct.html
- License: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)

`CODE_OF_CONDUCT.md` is an adaptation of that text. The Attribution section of
that file states which changes were made; this entry deliberately does not
restate them, because two copies of the same change list drift apart.

## Developer Certificate of Origin

- Project: Developer Certificate of Origin, version 1.1
- Text: https://developercertificate.org/
- Copyright: (C) 2004, 2006 The Linux Foundation and its contributors
- Terms: verbatim copying and distribution permitted; modification is not

The file `DCO` at the package root is that document reproduced **verbatim**. It
carries no SPDX header and no local edits, because its own terms forbid changing
it — a header would be a modification. `CONTRIBUTING.md` describes how a
contributor certifies it; the certification is the `Signed-off-by:` line on each
contributed commit, not a separate signed instrument. The convention was adopted
with this release, so the maintainers' own history predates it and does not
carry the trailer.

## Research sources and linked content

The venture, academic, standards, security, and practitioner sources linked in
`research/00_SOURCE_METHOD_AND_ROSTER.md` remain the property of their authors
and publishers. The repository summarizes and cites ideas; it does not license
third-party articles, reports, trademarks, datasets, or other linked content
for redistribution.

This notice is informational and is not legal advice. Downstream users and
distributors are responsible for reviewing the exact artifact and satisfying
all applicable third-party obligations.
