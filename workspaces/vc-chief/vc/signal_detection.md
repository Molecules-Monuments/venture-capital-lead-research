# Signal Detection

Policy version: `3.0`; signals remain low-authority proposals. Agent-mode `vcops` is read-only, so durable signal records require a reviewed fixed workflow or the non-allowlisted operator helper.

This file defines the passive signal detector. It turns low-friction channel/source observations into signal candidates without giving the detector authority to score, persist final facts, or trigger external actions.

## Principle

A signal candidate is a prompt to inspect, not a decision. The detector can notice that something may matter; `vc-chief` decides whether to route, persist, score, or escalate it.

## Signal types

These are the exact values of `result.signal_type` in the canonical
`lead-signal-detector.output.schema.json`, which
`workspaces/lead-signal-detector/AGENTS.md` names as the sole authority for
enums. The packet is schema-validated, so a value outside this list is a
contract failure, not a stylistic choice.

| Signal type | Meaning | Example |
|---|---|---|
| `possible_lead` | A company/person/source is mentioned, introduced, or recommended as a possible lead. | "Can someone look at Plain Vanilla Robotics?" / "Jane from Fund X says we should meet them." |
| `correction` | A user corrects an existing record. | "Their ARR is not 1.2m, it is 900k." |
| `approval_intent` | A user appears to approve something but wording may be vague. | "Looks good to me." |
| `rejection_intent` | A user appears to reject or pass. | "Let's pass for now." |
| `status_request` | A user asks for current state. | "Where are we on lead 42?" |
| `traction` | New customer, revenue, usage, or adoption signal. | "They announced 3 new enterprise customers." |
| `funding` | Financing or investor signal. | "They just raised a seed round." |
| `hiring` | Hiring activity relevant to traction or roadmap. | "They opened 8 robotics engineer roles." |
| `product` | Launch, release, technical demo, product page, or changelog signal. | "They shipped a new autonomous QA module." |
| `risk` | Legal, churn, layoffs, security, regulatory, founder, or reputation concern. | "Customer lawsuit was mentioned in the article." |
| `other` | Signal does not fit the categories above. |  |

A referral carries information the plain mention does not — who vouched, and how
close they are. Keep that in the packet's evidence and reason fields; it does not
get its own signal type.

## Allowed actions

- Classify message/source as a signal candidate.
- Assign confidence and proposed action.
- Suggest `capture_candidate`, `update_candidate`, `ask_clarification`,
  `escalate`, or `ignore`.
- Link to memory lookup results when available.
- Return a structured signal packet to `vc-chief`.

## Not allowed

- Create final facts.
- Score the company.
- Contact founders or referrers.
- Treat vague approval intent as valid approval.
- Trigger external writes, CRM updates, paid connector calls, or outreach.
- Run broad research without `vc-chief` routing.

## Proposed actions

These are the exact values of `result.proposed_action` in the same canonical
schema. The packet's `persistence_request.operation` uses a narrower
vocabulary — `none`, `capture_candidate`, or `update_candidate` — so only the
two capture/update actions carry over. `ignore`, `ask_clarification`, and
`escalate` are never valid operations; the schema keys the choice to
`persistence_request.requested` instead (`false` forces `operation: "none"`,
`true` requires a capture/update operation plus a non-empty reason).

| Action | Meaning |
|---|---|
| `ignore` | No lead relevance or not enough information. |
| `capture_candidate` | Likely new lead; ask `vc-chief` to run lead-routing and memory lookup. |
| `update_candidate` | Likely update to known lead/company/fact. |
| `ask_clarification` | Needs one short question before routing. |
| `escalate` | Approval, confidentiality, contradiction, or high-signal issue requires `vc-chief`. |

## Plain vanilla examples

| Input | Signal type | Proposed action | Reason |
|---|---|---|---|
| "Can someone look at Plain Vanilla Robotics?" | `possible_lead` | `capture_candidate` | Company mentioned as possible lead. |
| "Looks good, send it" | `approval_intent` | `escalate` | Vague approval; not valid under approval policy. |
| "Their ARR is 900k, not 1.2m" | `correction` | `update_candidate` | Potential contradiction against existing fact. |
| "They just raised EUR 4m seed" | `funding` | `update_candidate` or `capture_candidate` | Financing event may affect priority. |
