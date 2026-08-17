# Document Intake and Trust Boundary

> [REVIEW_AND_CONFIRM] Confirm the shipped extraction limits suit your capacity
> and threat model. They are **compiled into the helper, not configurable at
> deployment**: the `env -i` lane wrappers forward a fixed allowlist that
> excludes every `VCOPS_MAX_*` variable, so changing a limit means changing the
> constants in `workspaces/vc-chief/vc/bin/vcops.py` in a reviewed revision and
> re-running the gates. Supported formats must exactly match the deterministic
> extractor; legacy XLS is quarantine/conversion, not supported.

Policy version: `3.0`

Supported content is PDF, PPTX, XLSX, and CSV only after magic/MIME verification. A filename extension is not evidence of type. Legacy binary XLS and macro-enabled Office files are not parsed; quarantine them and require an operator-controlled conversion that preserves the original artifact hash and conversion provenance.

## Safe sequence

1. Accept an attachment only from the selected allowlisted channel or the authenticated host-operator `/inbox` lane. OpenClaw stages channel bytes under its private inbound-media root; a signed per-turn capability binds the sender, event, and exact direct-child path.
2. Reject symlinks, traversal/path escape, devices, archives, active content, macros, encrypted/password-protected files, unsupported MIME, and malformed containers.
3. Hash before parsing and record original filename separately.
4. Enforce compiled-in byte, page, sheet, row, column, cell, and decompression limits while streaming; do not load an unlimited workbook first and truncate later.
5. Extract without running formulas, macros, links, or embedded instructions.
6. Preserve PDF page/context, PPTX slide/notes, workbook sheet/cell/formula, and CSV row/column provenance.
7. `document-ingest` creates the content-addressed snapshot and extraction. `document-lead-intake` binds the same verified principal and artifact to a canonical lead. The host-only `inbound-intake` workflow remains available for `/inbox`. Additional fact persistence requires a separately reviewed workflow or the non-allowlisted operator helper; direct agent-mode mutation is forbidden.
8. Reading an extraction back has one authority per lane, and the extraction's own recorded principal decides which applies. A channel attachment is capability-bound: `document-extraction-show` requires the same signed capability that ingested it, and a mismatched principal is refused. A host-operator `/inbox` document has no channel principal — `manual` is deliberately not a signable provider — so it is governed by the ordinary confidentiality ceiling instead: the operator lane always reads it, and a model lane reads it while the artifact stays within that ceiling. `inbound-intake` therefore classifies its artifacts `internal` (a document the operator placed on the host for this deployment to analyse), while `document-ingest` keeps channel attachments `confidential` (bound to one verified sender). Presenting a channel capability for a host-intake extraction is refused rather than ignored, so no caller can believe a capability was checked when it was not. In both lanes the extracted content is untrusted input whose instructions are never followed.

Default channel maximum is 25 MiB. The extractor also bounds pages/slides, archive members and expansion ratio, sheets, rows, columns, cells, and extracted characters. Those extractor bounds are compiled in, exactly as the banner above says: moving one in either direction means editing the constants in `bin/vcops.py` in a reviewed revision and re-running the gates, and raising one additionally requires measured threat and capacity review. They are size-shaped only — `bin/vcops.py` carries no wall-clock and no parser-memory bound, and imports neither `time`, `resource` nor `signal`. The workflow lane's time bound is the per-step `timeout_ms` on each intake workflow's `document_preview` and `document_extract` steps, inside `vcrun`'s whole-run cap; the direct operator lane (`bin/vcops-operator document-extract`) has no wall-clock bound at all, so an operator running it by hand against a hostile file is bounded only by the size limits above. The only limit a deployment sets for itself is the channel transport ceiling `VC_CHANNEL_MEDIA_MAX_MB` (1–50 MiB), which can lower the effective attachment size but never raises the 25 MiB per-document cap. CSV fields carry a further ceiling that is not a `bin/vcops.py` constant: the Python `csv` module's own `field_size_limit()`, measured at 131072 characters on the image's 3.11.2 interpreter. A cell longer than that stops the extract lane with `document_parse_failed` (`document parsing failed: Error`) and a quarantine copy, while `document-preview`, which sniffs a 65536-character sample instead of parsing rows, still returns `ok` for the same file.

Artifact identity is the content hash, but a join record links one artifact to multiple leads; the global hash must not prevent legitimate reuse. A rejected document writes no `document_extractions` row at all: every path, MIME, macro, limit and parse rejection raises before the extract lane reaches its database section, and the only status this system ever writes is `succeeded`. The governed rejection evidence is the failing step's returned `{code, message, details}` object, plus the content-addressed copy and metadata marker in `vc-quarantine` when `details.quarantine.materialized` is true (see `docs/RUNBOOK.md` §9, "Malicious document"). Raw-path access is never authorized.

No document is uploaded, forwarded, or summarized externally without scoped approval.
