---
name: memo-writing
description: Produce a two-sided internal investment memo from a current cited snapshot with an auditable claim-evidence map.
---

# Memo Writing

## Inputs

- Lead/company identifiers, compiled-truth snapshot ID/time/hash, qualification result, contradiction and trajectory results, evidence index, supplied memo policy, and predeclared evaluation criteria.

## Contract

Reconcile identifiers, hashes, versions, recommendation, and evidence references before drafting. Write a strong investment case and strong counter-case, then identify the decision cruxes that could change the recommendation. Every crux must have a current view, evidence and counterevidence references, and a falsifier.

Map every material claim to evidence or an explicit inference basis. Preserve submitted claim, verified fact, inference, contradiction, stale, and unknown states. Unsupported claims may not hide in prose. Keep the recommendation identical to the supplied qualification result; an inconsistency is a failure, not permission to revise it.

Rank next diligence by decision value and describe the evidence needed. An owner field is planning metadata only and does not authorize outreach, research, persistence, publication, or delivery. Use plain Obsidian-friendly Markdown without hidden links or active content.

## Evidence and failures

A stale or hash-mismatched snapshot, broken evidence reference, recommendation mismatch, unsupported material claim, missing counter-case, or missing evaluation is a blocker. Weak coverage, unresolved contradictions, falsifiers, and missing data must remain visible.

## Output boundary

Validate the complete response against `/workspaces/schemas/memo-writer.output.schema.json`. The canonical schema, not this prose, controls fields, types, enums, and failure states.

Never browse, calculate, persist, publish, email, upload, write externally, delegate, or send a channel message.

## Persisting the memo (`memo-record` citations contract)

Persistence happens after the approved `evaluate-lead` run, by the chief
routing `vcrun run memo-record` through `data-steward`. Its `citations_json`
is a JSON array with at least one element, and each element must be an object
with EXACTLY the keys `{fact_id, source_id, citation, locator}`:

- `fact_id`/`source_id`: the persisted fact and source ids (integers from the
  compiled-truth snapshot's provenance — not packet-local `evidence_refs`).
- `citation`: a short marker label (≤100 chars) that must appear LITERALLY in
  the memo markdown (e.g. `[C1]`); a label absent from the memo text is
  refused (`citation_marker_missing`).
- `locator`: where in the source the claim lives (≤1000 chars).

Duplicate `(fact_id, source_id, citation)` triples are refused, and every
citation must lie inside the approved snapshot's `current` provenance (a
database trigger enforces this). When drafting, embed the citation markers in
the memo body so the chief can assemble `citations_json` from the
`claim_evidence_map` without editing the prose.
