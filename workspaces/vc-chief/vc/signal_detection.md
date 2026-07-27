# Signal Detection

Policy version: `3.0`; signals remain low-authority proposals. Agent-mode `vcops` is read-only, so durable signal records require a reviewed fixed workflow or the non-allowlisted operator helper.

This file defines the passive signal detector. It turns low-friction channel/source observations into signal candidates without giving the detector authority to score, persist final facts, or trigger external actions.

## Principle

A signal candidate is a prompt to inspect, not a decision. The detector can notice that something may matter; `vc-chief` decides whether to route, persist, score, or escalate it.

## Signal types

| Signal type | Meaning | Example |
|---|---|---|
| `lead_mention` | A company/person/source is mentioned as a possible lead. | "Can someone look at Plain Vanilla Robotics?" |
| `referral_signal` | A person appears to introduce or recommend a company. | "Jane from Fund X says we should meet them." |
| `correction_signal` | A user corrects an existing record. | "Their ARR is not 1.2m, it is 900k." |
| `approval_intent` | A user appears to approve something but wording may be vague. | "Looks good to me." |
| `rejection_intent` | A user appears to reject or pass. | "Let's pass for now." |
| `status_request` | A user asks for current state. | "Where are we on lead 42?" |
| `traction_signal` | New customer, revenue, usage, hiring, or adoption signal. | "They announced 3 new enterprise customers." |
| `funding_signal` | Financing or investor signal. | "They just raised a seed round." |
| `hiring_signal` | Hiring activity relevant to traction or roadmap. | "They opened 8 robotics engineer roles." |
| `product_signal` | Launch, release, technical demo, product page, or changelog signal. | "They shipped a new autonomous QA module." |
| `risk_signal` | Legal, churn, layoffs, security, regulatory, founder, or reputation concern. | "Customer lawsuit was mentioned in the article." |
| `other` | Signal does not fit the categories above. |  |

## Allowed actions

- Classify message/source as a signal candidate.
- Assign confidence and proposed action.
- Suggest `capture_lead`, `update_existing`, `ask_clarification`, `escalate`, or `ignore`.
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

| Action | Meaning |
|---|---|
| `ignore` | No lead relevance or not enough information. |
| `capture_lead` | Likely new lead; ask `vc-chief` to run lead-routing and memory lookup. |
| `update_existing` | Likely update to known lead/company/fact. |
| `ask_clarification` | Needs one short question before routing. |
| `escalate` | Approval, confidentiality, contradiction, or high-signal issue requires `vc-chief`. |

## Plain vanilla examples

| Input | Signal type | Proposed action | Reason |
|---|---|---|---|
| "Can someone look at Plain Vanilla Robotics?" | `lead_mention` | `capture_lead` | Company mentioned as possible lead. |
| "Looks good, send it" | `approval_intent` | `escalate` | Vague approval; not valid under approval policy. |
| "Their ARR is 900k, not 1.2m" | `correction_signal` | `update_existing` | Potential contradiction against existing fact. |
| "They just raised EUR 4m seed" | `funding_signal` | `update_existing` or `capture_lead` | Financing event may affect priority. |
