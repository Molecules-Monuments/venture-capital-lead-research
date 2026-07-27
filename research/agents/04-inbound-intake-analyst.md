# Inbound Intake Analyst — Research Dossier

Status: pre-implementation research  
Baseline: `Version_2/complete_update`  
Research date: 2026-07-20

## Current contract and invoked-skill assessment

The inbound analyst is correctly positioned as a normalization and provenance role. It reads supplied submission context, preserves submitter statements as claims, assigns chief-supplied trust/confidentiality/storage/retention labels, and recommends the next specialist. It cannot browse, parse arbitrary attachments, reply, persist, or delegate. The `inbound-intake` skill is preceded by trust and memory decisions; documents route through the document analyst.

The skill and agent differ materially. The skill requires consent/lawful-basis flags and distinguishes `absent`, `not_disclosed`, `not_applicable`, and `extraction_failure`; the agent exposes only general `missing_data` and `approval_risks`. The skill asks for `origin`, `duplicate_candidates`, and `persistence_request`, while the agent schema uses channel/source fields and lacks those canonical handoff fields. Conversely, the agent includes storage and retention explicitly. These should be combined rather than left as competing contracts.

## Quantitative capabilities and gaps

- Four read-only tools: assignment reading, provisional memory search/get, and session status; no web or side effects.
- One supplied submission packet; attachments can only be referenced, not opened.
- Structured capture covers channel, time, sender/referrer label, company, documents, claims, public facts supplied by the chief, confidentiality, storage, retention, and next agent.
- No maximum personal-data field set, no missingness enum, no referral-authority separation, no consent/lawful-basis field, and no completeness metric.
- Version 2 has one static inbound-referral route fixture. There is no behavioral measurement of claim/fact separation, prestige resistance, conflicting-field handling, privacy minimization, or duplicate-submission accuracy.

The agent is intentionally unable to verify claims. That is a strength, but `verified_public_facts` is a misleading field name unless every supplied fact carries its independent evidence identifier and verification status; otherwise chief prose can be laundered into “verified.”

## Human analogue and practitioner approaches

The closest human is a deal-flow operations analyst who creates a clean, traceable record from a founder or referrer submission. It is not the person who validates the deck, judges the referrer, or decides whether to invest.

**Approach 1 — standardized open intake at scale.** YC describes tens of thousands of applications, human reading, and custom software for parsing applications, messaging founders, and choosing interviews; it denies having a secret model that finds winners ([Inside YC Admissions](https://www.ycombinator.com/blog/inside-yc-the-admissions-team), accessed 2026-07-20). Its application guidance emphasizes concise, specific founder evidence rather than generic adjectives ([How to Apply to YC](https://www.ycombinator.com/howtoapply), accessed 2026-07-20). Grade **B** for stated operations, **C/D** for predictive effectiveness. It supports structured fields plus preserved raw wording, but YC’s format and founder-selection philosophy are marketing- and accelerator-specific.

**Approach 2 — high-touch staged intake.** First Round says it reviews shared materials for fit and conflicts, lets founders do most of the talking in the first meeting, and deepens work through follow-ups and references before a partner meeting ([First Round investment process](https://www.firstround.com/who-we-back), accessed 2026-07-20). Grade **B** for stated process, **C** for effectiveness. This approach preserves narrative context and uncertainty rather than forcing every submission into a fully populated form.

The system should combine their mechanisms: a stable minimum schema for comparability, raw-source preservation for nuance, and explicit missingness rather than compelled answers.

## Counterevidence, standards, and transfer limits

Warm or prestigious access is not neutral. Research on initial VC success finds that early success can improve access to later-stage deals and larger syndicates even where persistent ability to select the right segments is not found ([Nanda, Samila & Sorenson](https://www.nber.org/papers/w24887), accessed 2026-07-20). Grade **B** for the documented pattern, **C** for an individual referral. A referrer may be valuable provenance, but reputation must not upgrade submitted claims or create a scoring bonus.

The broad VC survey documents variation across stage, industry, geography, and success, but it is self-reported and the authors disclose GP/LP consulting relationships ([Gompers et al.](https://www.nber.org/papers/w22587), accessed 2026-07-20). Grade **B** descriptively, **C** for intake design. It does not justify collecting every field practitioners say they use.

Privacy and provenance standards are more directly transferable. GDPR Article 5 establishes purpose limitation, data minimization, accuracy, and storage limitation ([EUR-Lex GDPR](https://eur-lex.europa.eu/legal-content/EN/TXT/?toc=OJ%3AL%3A2016%3A119%3AFULL&uri=uriserv%3AOJ.L_.2016.119.01.0001.01.ENG), accessed 2026-07-20). W3C PROV distinguishes entities, activities, agents, derivation, primary sources, quotation, and revision ([W3C PROV-O](https://www.w3.org/TR/prov-o/), accessed 2026-07-20). Both grade **A** for their normative/data-model domains, but neither decides the fund’s lawful basis, retention period, or investment relevance; those remain deployment-specific and require counsel/operator configuration.

Transfer is strongest for direct founder/referrer submissions in configured jurisdictions and channels. Consent, lawful basis, retention, and sensitive-data rules vary by jurisdiction. Standard forms can disadvantage founders using a second language or companies whose key evidence is regulatory/technical rather than SaaS metrics. The raw message should remain referenced, not silently rewritten into a US seed template.

## Proposed changes and causal mechanisms

1. **Unify the skill/agent schema.** Add canonical origin, duplicate candidates, persistence request, consent/lawful-basis status, and explicit storage/retention fields. Deterministic handoffs should then stop depending on prose.
2. **Use typed missingness.** Every expected field receives `present`, `not_disclosed`, `not_applicable`, `extraction_failed`, or `not_requested`, with source reference. This prevents absence from being misread as zero or adverse evidence.
3. **Separate referrer provenance from authority.** Capture stable referrer/source ID, relationship as submitted, and introduction path, but add `claim_authority: none` unless the trust policy supplies authority. This blocks prestige laundering while preserving funnel analytics.
4. **Require evidence IDs for supplied public facts.** Otherwise keep them as submitted claims. This prevents chief-generated summaries from silently gaining fact status.
5. **Add data-minimization reasons.** Each personal-data field must have purpose, retention class, and downstream consumer; reject or redact fields with no configured purpose.
6. **Preserve raw-to-normalized lineage.** Link every normalized value to message/artifact locator using a small PROV-like derivation record. This improves correction and auditability.

## Rejected imports

- No referrer reputation score, famous-founder bonus, school/employer prestige weight, or warm-introduction truth upgrade.
- Do not copy YC’s application questions wholesale or require every field before a lead can exist.
- Do not browse to “complete” the packet, parse attachments, infer consent, or collect private contact/family/protected data.
- Do not treat incomplete disclosure as deception or score missing values as zero.

## Precommitted eval mapping

Use at least 12 cases: named referral, cold inbound, conflicting name/domain, duplicate submission, second-language free text, missing consent/retention, attachment risk, extraction failure, prestige cues, prompt injection, unsupported “verified fact,” and an entirely sparse but valid lead. Measure provenance-field completeness, typed-missingness accuracy, claim/fact separation, duplicate-candidate accuracy, and privacy-field minimization. Require 100% stable identifier preservation; at least 95% claim-status correctness; zero unsupported material facts, inferred authority, or excess PII; and 100% fail-closed behavior for unclear confidentiality, consent/lawful basis, unsafe documents, and identity collisions. Run paired prestige-blind fixtures: changing only the referrer/founder fame must not alter claim status or recommended diligence route without an explicit policy reason.

