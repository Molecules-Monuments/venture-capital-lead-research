# Investment Thesis

> [MUST_CUSTOMIZE] This AI-infrastructure/Europe thesis is an example, not
> a default recommendation. Replace it with your firm's mandate, stage,
> sector, geography, check/ownership and outlier policy. The routing and
> scoring cases under `tests/g3` are pinned examples; re-pin them with
> `scripts/init_customization.py --update-hashes` after editing.

Policy version: `3.0`; substantive thesis content is retained from the 2026-06-10 ground source. The customized Version 3 scoring rubric and typed evidence states govern operational decisions.

## Purpose

This is the canonical Ideal Company Profile for inbound, outbound, and unspecified leads.

It governs:

- Database fields.
- Agent routing complexity.
- JSON schemas for structured input and output.
- Pre-qualification gates.
- Memo breadth and depth.
- Scoring weights.
- Missing-data expectations.

The agent system cannot write a reliable memo about fields it was not asked to research. If this thesis is vague, the database and workflow will become vague too.

## Plain vanilla thesis

We look for early-stage software or infrastructure companies with credible founder-market fit, evidence of a painful customer problem, and early signs that the product can become a scalable venture-backed company.

Default sector focus for this template:

- AI infrastructure.
- AI developer tooling.
- Data infrastructure for AI.
- AI security and governance.
- Vertical AI infrastructure for regulated or operationally complex industries.

This sector focus is a starter example. Replace it for each client.

## Target company characteristics

- Stage: pre-seed, seed, or early Series A.
- Geography: Europe, UK, Switzerland, and Israel when relevant to European enterprise markets.
- Company type: product-led software or infrastructure company.
- Preferred category: AI infrastructure, AI developer tooling, data infrastructure for AI, AI security, enterprise AI governance, or vertical AI infrastructure.
- Business model: scalable software, infrastructure, usage-based platform, or enterprise SaaS.
- Avoid: services agencies, pure consulting, thin wrappers, low-defensibility marketplaces, and businesses outside legal/ethical investment scope.

## Stage definition

| Stage | Plain vanilla definition | Evidence examples |
|---|---|---|
| Pre-seed | Team and early product direction; limited market proof | Founder background, prototype, design partners, early technical artifact |
| Seed | Product in market with early user/customer proof | Pilots, customers, usage, open-source adoption, seed financing |
| Early Series A | Repeatable early sales motion or strong adoption curve | Revenue/customer evidence, expansion, retention signal, hiring |

Default deprioritization:

- Growth-stage companies.
- Public companies.
- Pure services agencies.
- Companies too early to identify product, team, or market.

## Geography

Primary:

- Europe.
- United Kingdom.
- Switzerland.

Secondary:

- Israel when clearly relevant to European enterprise markets.
- United States only when the company is unusually strong and directly relevant to the thesis.

Customize:

- Excluded jurisdictions:
- Strategic geographies:
- Local language requirements:
- Regulatory restrictions:

## Founder profile

Strong positive signals:

- Founder-market fit from prior operating, research, engineering, or domain work.
- Technical founder or deeply technical founding team for infrastructure categories.
- Prior startup experience, open-source credibility, enterprise buyer experience, or category-specific expertise.
- Clear evidence that the founder understands the customer workflow.

Weak or negative signals:

- No identifiable founder.
- No public professional context.
- Founder background unrelated to claimed market.
- Heavy reliance on hype language without product evidence.

Founder fields to capture:

- Founder names and roles.
- Relevant operating background.
- Relevant technical/domain background.
- Prior founding experience.
- Prior exits or failures, if public and relevant.
- Academic/research signal, if relevant.
- Open-source or community signal, if relevant.
- Network/referrer signal.
- Founder-market fit rationale.
- Founder risks and missing data.

## Product and technical differentiation

Strong positive signals:

- Solves a hard, frequent, expensive customer problem.
- Product has workflow depth rather than a thin wrapper.
- Technical architecture is meaningfully differentiated.
- Data, distribution, integration, or workflow advantage can compound.
- Product can become a system of record, system of action, or critical infrastructure layer.

Weak or negative signals:

- Generic AI language without a concrete workflow.
- No product evidence.
- Feature easily copied by incumbents or foundation model providers.
- Product depends on fragile platform arbitrage.

Fields to capture:

- Product category.
- Target user.
- Buyer and budget owner.
- Core workflow.
- Technical moat hypothesis.
- Integration depth.
- Defensibility evidence.
- Product maturity.

## Traction signals

Strong:

- Paying customers or signed pilots.
- Public customer stories.
- Design partners with credible names.
- Open-source usage, GitHub stars, package downloads, community activity, or developer engagement where relevant.
- Hiring after product launch.
- Repeated independent mentions by users or buyers.

Medium:

- Waitlist, demo requests, credible advisors, early investor involvement, or press tied to a product launch.

Weak:

- Generic launch post, social hype, unverified claims, or single-source vanity metric.

Traction fields to capture:

- Customer names, if public or submitted.
- Customer count, if evidenced.
- Revenue/ARR, if disclosed.
- Pilot/design-partner status.
- Usage metrics.
- GitHub stars, forks, contributors, release cadence, or package downloads when relevant.
- Hiring signal.
- Community signal.
- Funding signal.
- Source and confidence per signal.

## Market signals

- Clear buyer and budget owner.
- Painful, recurring workflow problem.
- Tailwind from AI adoption, regulation, security pressure, or platform shift.
- Defensible value chain position.
- Competition exists but incumbents do not fully solve the problem.

Market fields to capture:

- Category.
- Buyer.
- Budget owner.
- User persona.
- Competitors.
- Substitutes.
- Market timing.
- Why now.
- Adoption blockers.
- Regulatory or compliance drivers.
- Value chain position.

## Financial and commercial fields

Use only evidenced data:

- Revenue: amount, period, and source.
- Customers: count, names, stage, and source.
- Pricing: model and source.
- Gross margin or infrastructure cost: only if disclosed or source-backed.
- Funding: amount, round, date, and source.

Do not estimate financial fields unless the user explicitly asks for a scenario model. Scenario models must be labeled as assumptions, not facts.

Inbound adjustment:

- Inbound materials may include revenue, pipeline, customer, pricing, or cap table details.
- Treat these as submitted claims unless independently verified or clearly marked as company-submitted.
- Store the page, sheet, or cell reference for each extracted claim.

Outbound adjustment:

- Outbound discovery usually has less financial evidence.
- Missing financials should not be filled with guesses.
- If financial data is absent, record it as missing data in the vocabulary of
  the lane you are writing (`missing_data_handling.md` maps the two): intake
  lanes use `status: not_disclosed` when the company plainly knows the figure
  but has not published it, and `status: absent` otherwise; research lanes use
  `state: missing` and name the non-disclosure in `reason`.

## Exclusion themes

Default hard exclusions:

- Illegal, deceptive, or prohibited business.
- Use of private personal data without a lawful and approved basis.
- Services-only model without scalable product IP.
- Generic wrapper without workflow depth.
- No identifiable product and no identifiable team.

Default soft exclusions:

- Unclear buyer.
- Weak founder-market fit.
- Crowded market with no differentiation.
- No evidence beyond press or hype.
- Too far outside target geography or stage.

## Recommendation ladder

| Recommendation | Meaning |
|---|---|
| `pass` | Outside thesis, hard exclusion, or insufficient quality. |
| `watch` | Some signal, but not enough for deeper work now. |
| `research_deeper` | Enough signal to justify specialist research. |
| `high_priority` | Strong evidence and fit; needs human review. |
| `needs_human_review` | Approval, confidentiality, conflict, or risk issue. |
| `insufficient_evidence` | Captured but too incomplete to score. |

## Client customization questions

- Which sectors are explicitly in scope?
- Which sectors are explicitly out of scope?
- Which stage boundaries matter?
- Which geographies matter?
- What founder traits matter most?
- What traction signals matter most?
- What minimum evidence is required before a human spends time?
- Which red flags are non-negotiable?
- How should inbound referrals be weighted?
- What external systems, if any, may receive approved writes?

## Output standard

Every evaluated lead must include:

- Origin group and subtype.
- Company name and canonical domain.
- One-line description.
- Founder signal.
- Traction signal.
- Market signal.
- Technical differentiation.
- Financial/commercial evidence.
- Missing fields.
- Exclusion check.
- Recommendation.
- Evidence links or document references.

## Database field implications

At minimum, the database must be able to store:

- Lead origin and subtype.
- Company identity.
- Founder evidence.
- Traction evidence.
- Market evidence.
- Technical differentiation evidence.
- Financial/commercial evidence.
- Missing fields.
- Confidence by claim and criterion.
- Recommendation.
- Approval state.
