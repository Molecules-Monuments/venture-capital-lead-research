---
name: lead-memory-lookup
description: Resolve a typed company identity and retrieve bounded authoritative Postgres history before creation, research, scoring, connector use, or memo generation.
---

# Lead Memory Lookup

## Inputs

- Typed identity keys: company/lead ID, canonical domain, legal/name alias,
  artifact hash, external provider/account/ID, or channel event/message/permalink.
- Purpose, requester ID, confidentiality ceiling, result limit, and the
  deterministic Postgres resolver packet supplied by the chief.

## Contract

Postgres—not model memory—is business authority. Version 3 disables generic
conversational Markdown memory. It separately persists a deliberately small,
peer-scoped preference schema for the verified channel principal; those
preferences affect presentation and research depth only and are never evidence,
identity, approval, or investment judgment. Match exact IDs, domains, artifact hashes, external
IDs, and channel IDs first; then normalized aliases; then return bounded fuzzy
candidates for human review. Similarity never authorizes an automatic merge.
Prior evaluation, memo, and workflow metadata supply decision history; memo
bodies are not returned and memo pointers are never evidence.

## Evidence and failures

Record normalization, match method, confidence, confidentiality ceiling,
supporting IDs, current-state dates, source provenance, and an explicit
external-research decision/reason. Database unavailability, an invalid domain,
conflicting exact identifiers, hidden exact matches, or any fuzzy/name-domain
collision blocks canonical creation and paid/external research.

## Output

Consume the supplied `entity-resolve` packet: `identity`, `decision`, `company`,
`current_facts`, `operational_history`, `external_research`, and policy/authority
metadata. Creation uses only the fixed workflow-only
`company-resolve-create`, which atomically records and consumes the resolution
decision against a claimed workflow request. `memory-lookup` is deprecated and
must not be used by new callers. Direct mutation, external write, and channel
send are forbidden.
