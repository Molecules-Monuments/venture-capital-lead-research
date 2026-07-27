# Document Intake Analyst — Research Dossier

Status: pre-implementation research  
Baseline: `Version_2/complete_update`  
Research date: 2026-07-20

## Current contract and invoked-skill assessment

The agent contract says the model describes deterministic extraction results supplied in an assignment; the deterministic pipeline—not model file inspection—establishes path safety, hash, MIME, quarantine, parser limits, and extracted content. Its tools reinforce that boundary: only read, provisional memory, and session status; web, execution, writes, and arbitrary paths are denied. This is a strong least-privilege design.

The invoked `document-extraction` skill is less clear. It tells the role to operate in quarantine, verify magic/MIME, hash, stream within resource limits, and reject unsafe content—as if the agent performs extraction. The actual agent cannot execute those operations. Version 3.0 should explicitly split the deterministic extractor contract from the model’s extraction-review contract or name the fixed workflow that executes it. Otherwise documentation can claim controls the callable role cannot perform.

There are further mismatches. The skill supports PDF/XLS/XLSX/CSV in its description, while the executable Version 2 fixtures reject legacy `.xls`; the agent scope names XLS. The skill output includes `document_facts`, `limits_applied`, and `persistence_request`; the agent requires `extracted_claims` and `locations` but omits applied limits and persistence request. These differences affect both safety claims and downstream evidence coverage.

## Quantitative capabilities and gaps

- Four read-only tools and zero parser/execution/side-effect tools.
- Four nominal formats, although the tested path rejects legacy XLS; archives, macros, external links, encryption, path escapes, and resource-limit violations are rejected.
- Current G4 fixtures list 3 accepted examples and 13 rejected examples, with formula warnings and fixed byte/page/sheet/row/column/cell/text limits. This is meaningful deterministic coverage.
- Missing behavioral metrics include claim-recovery recall, page/cell locator accuracy, table/OCR completeness, hidden-row/chart handling, model prompt-injection compliance, and downstream interpretation of truncation.
- `parse_status` and a single `truncated` flag cannot express partial coverage by page, sheet, table, image/OCR layer, formula, chart, or unsupported object.

The current deterministic suite is substantially stronger than those of the other four roles, but it tests the extractor and database boundary more than the model’s review output.

## Human and practitioner analogues

The closest human is a forensic data-room intake analyst reviewing a machine-generated extraction manifest. It is not a financial analyst validating the business, and it should never “open the file to see” after the deterministic gate refuses it.

**Approach 1 — reproducible raw-data diligence.** An a16z biotech data-room guide says raw data for key experiments can enable plot replication and treats investment memos and prior Q&A as diligence materials, while warning that different investors focus on different questions ([a16z Virtual Data Rooms](https://a16z.com/virtual-data-rooms-the-unsung-hero-of-biotech-financing/), accessed 2026-07-20). Grade **B** for stated diligence practice, **C** for effectiveness. It is fund-authored founder advice and biotech-specific, but it supports preserving source coordinates and extraction artifacts rather than relying on a smooth summary.

**Approach 2 — document claims corroborated through people and numbers.** First Round reports that its seed diligence often includes 5–15 conversations with customers, prospects, and former colleagues and expects founders to know the numbers reviewed in materials ([First Round partner-meeting diligence](https://review.firstround.com/heres-what-you-can-really-expect-when-pitching-your-seed-stage-startup-at-a-vc-partner-meeting/), accessed 2026-07-20). Grade **B** for stated process, **C** for causal effectiveness. The import is that a parsed deck remains submitted evidence requiring later corroboration, not that this intake agent should make calls.

**Approach 3 — default-deny active content.** Microsoft blocks macros from internet-origin Office files by default because macros are commonly used to deploy malware and ransomware ([Microsoft Office macro policy](https://learn.microsoft.com/en-us/microsoft-365-apps/security/internet-macros-blocked), accessed 2026-07-20). Grade **A** for Microsoft product behavior and threat rationale, **B** for general architecture. This directly supports never executing macros or trusting an allowlisted sender’s attachment content.

## Independent counterevidence, standards, and limits

OWASP’s file-upload guidance recommends defense in depth—extension, content type, signature, filename, storage, size, authorization, and malware/content controls—rather than relying on any one check ([OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html), accessed 2026-07-20). Grade **B**: practitioner consensus guidance, not a controlled study. It is counterevidence to any claim that MIME or a hash alone makes content safe.

Indirect prompt injection can be embedded in documents, emails, hidden text, metadata, and images; OWASP recommends separating instructions from data and least privilege ([OWASP Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html), accessed 2026-07-20). NIST’s 2025 adversarial-ML taxonomy also covers third-party indirect prompt injection ([NIST AI 100-2e2025](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-2e2025.pdf), accessed 2026-07-20). Grades **B** and **A/B** respectively for threat taxonomy, but neither proves a prompt-only defense is sufficient; deterministic least privilege remains primary.

W3C PROV provides a useful vocabulary for entity, activity, agent, derivation, primary source, quotation, and revision ([W3C PROV-O](https://www.w3.org/TR/prov-o/), accessed 2026-07-20). Grade **A** for provenance modeling, **C** for choosing the system’s exact schema.

Extraction completeness varies sharply. Born-digital SaaS decks and simple CSVs are easier than scans, handwriting, merged cells, charts, hidden sheets, formulas with stale cached values, and scientific images. Biotech and financial models need domain-specific later review; defense documents may be export-controlled or highly confidential. Locale affects decimal/date parsing, and PDF page coordinates do not transfer directly to spreadsheet cells.

## Proposed changes and causal mechanisms

1. **Clarify the executor boundary.** Define a deterministic `artifact-extractor` operation and a separate model `document-intake-review` skill. This prevents the system from claiming the model verified hash/MIME or quarantine.
2. **Unify format support with tests.** Either add a safe deterministic XLS path and fixtures or remove XLS from all contracts. Documentation must match executable capability.
3. **Return an extraction coverage manifest.** Per page/sheet/object, report extracted, skipped, truncated, OCR-used, formula-present, hidden, chart/image-only, and limit hit. This should prevent partial extraction from looking complete.
4. **Preserve dual spreadsheet representations.** Store formula text and cached/displayed value separately with cell coordinates; never calculate. This retains evidentiary content without code execution.
5. **Use typed claim locators.** Every claim maps to artifact hash, parser/version, page plus bounding context or sheet/cell range, and extraction activity ID. This improves reproducibility and later correction.
6. **Add semantic review fields.** For each extracted metric, preserve original text, value/unit/period as written, claim status, and ambiguity; do not normalize silently.
7. **Require explicit quarantine/error reason codes.** Unsupported, unsafe, encrypted, corrupt, limit-exceeded, and confidentiality-review cases should not collapse into generic failure.

## Rejected imports

- No direct model inspection of arbitrary files, links, images, formulas, macros, embedded objects, or refused paths.
- Do not enable signed or sender-trusted macros in this system; signature trust is outside the agent’s authority.
- Do not treat OCR, readable text, cached formula values, or raw-data availability as independent verification.
- Do not summarize away skipped regions, hidden content, parser warnings, or conflicting metrics.
- Do not copy biotech data-room completeness expectations into every sector.

## Precommitted eval mapping

Retain every Version 2 deterministic path/MIME/macro/formula/encryption/resource-limit fixture. Add at least 12 model-review cases covering prompt injection in extracted text, hidden rows/sheets, formula plus cached value, OCR errors, chart-only metrics, truncation by page and text limits, conflicting deck metrics, locale numbers/dates, encrypted/oversized artifacts, identical hashes across leads, and broken locators. Require 100% safety/refusal behavior, hash/parser/limit preservation, and schema validity; 100% locator accuracy for extracted high-impact metrics; at least 95% claim-status separation; zero executed content, fabricated provenance, or claims of complete extraction after a limit/error. Measure claim-recovery recall only against the deterministically visible ground truth—never against content the pipeline intentionally quarantined.

