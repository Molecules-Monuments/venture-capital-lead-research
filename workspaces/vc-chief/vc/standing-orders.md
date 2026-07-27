# Standing Orders

Policy version: `3.0`

Standing orders never override trust, research budget, approval, tool, or data authority policy.

## Common run contract

1. Create a run/idempotency record when a reviewed route exists; otherwise label it `operator_only` and do not invent persistence.
2. Apply trust decision and authoritative Postgres entity resolution.
3. Resolve the configured agent/skill profile and build the smallest dependency graph that answers one decision question.
4. Freeze a schema-valid pre-spawn evaluation before each dependency-ready worker starts.
5. Supply workers only the bounded authoritative inputs and policy packet they need.
6. Workers return canonical structured packets without persistence or channel side effects; chief validates each packet and records a return assessment.
7. `data-steward` validates read-only state or invokes a reviewed fixed workflow; direct agent-mode `vcops` mutation is forbidden.
8. Chief builds compiled truth and contradiction state before scoring; qualification and memo workers consume immutable predecessor packets.
9. Proactive notification is unsupported; Version 3.0 has no dispatcher. Any operator-created notification record is internal-log-only.
10. Reconcile task graph, resource budget, fixed-workflow state, and Postgres terminal state.

Outbound, inbound, and unspecified runs all begin at `triage`. Documents remain untrusted claims. More than three specialist tasks run in sequential waves. Paid sources, outreach, external writes/uploads, schema/config changes, destructive actions, and quiet-hour bypass require exact approval.

Maintenance checks are read-only and fail on absent fixtures or zero-item inventories. Skill/source/schema improvements are proposals until approved.
