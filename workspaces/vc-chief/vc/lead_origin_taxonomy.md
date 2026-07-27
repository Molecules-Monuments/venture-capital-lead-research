# Lead Origin Taxonomy

Policy version: `3.0`; taxonomy retained from the 2026-06-10 ground source. Origin controls provenance/routing and never changes score weights.

## Origin groups

Use exactly one:

- `outbound`
- `inbound`
- `unspecified`

## Outbound subtypes

- `source_based`: curated source list, website, RSS, company blog, competitor VC portfolio, upstream investor page, research report.
- `signal_based`: hiring, GitHub activity, product launch, funding, customer story, technical blog, public usage proxy.
- `event_based`: demo day, accelerator batch, conference, hackathon, grant, award, webinar.

## Inbound subtypes

- `direct_contact`: founder or company contacted the firm directly.
- `network_referral`: angel, VC, operator, founder, LP, advisor, or trusted network referred the lead.
- `event_followup`: contact initiated at or after an event the firm attended.
- `unknown`: inbound with a source that cannot yet be classified (the `inbound-text-intake` enforcement set accepts it so an unclassifiable inbound is still recordable).

## Unspecified subtypes

- `crossover`: ad hoc meeting or informal interaction later became a lead.
- `ambiguous`: source exists but cannot be mapped cleanly.
- `unknown`: source is missing.

## Enforcement and intake-mechanism subtypes (Version 3.0)

`origin_group` is the enforced enum (`create-lead` rejects any other value).
`origin_subtype` is a descriptive provenance field, not a closed enum in the
database. Two sources set it:

- **Model classification** — the research/routing lane assigns one of the
  outbound/inbound/unspecified subtypes above from the observed origin.
- **Deterministic intake lane** — the fixed workflows assign an
  intake-mechanism subtype for the exact lane that created the lead:
  `active_sourcing` (`outbound-scout`), `document_upload` (host `inbound-intake`),
  `channel_document_upload` (`document-lead-intake`), and the caller-supplied
  inbound value for `inbound-text-intake` (`direct_contact`, `network_referral`,
  `event_followup`, or `unknown`).

Both are valid; the subtype records *how* the lead entered, and it never
changes score weights.

## Required capture fields

- `origin_group`
- `origin_subtype`
- `origin_confidence`
- `origin_note`
- `intake_channel`
- `source_url` or `source_label`
- `referrer_name` and `referrer_org`, if applicable
