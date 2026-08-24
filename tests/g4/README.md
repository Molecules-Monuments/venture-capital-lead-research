# G4 adversarial gate

This suite is the executable contract for the Version 3 data and helper boundary. It is
deliberately hostile: a test failure is a release blocker, not a warning.

Run the complete gate from the repository root:

```sh
python3 -B scripts/run_g4.py
```

The runner requires PostgreSQL 17 `initdb`, `pg_ctl`, `psql` and `pg_dump` on
PATH — the server package, since it builds a throwaway cluster — for the major this
package deploys (`POSTGRES_IMAGE`) — and aborts with an actionable message on
any other major, because a gate that validates migrations against a version
the deployment never runs would report PASS while proving nothing.

The runner always starts a disposable local PostgreSQL cluster and refuses an
external database URL. Run it with the release virtual-environment Python so
the hash-pinned dependencies are present. All database mutations are isolated
to the disposable cluster, which is stopped and removed afterward.

The contract covers:

- global artifact identity with many-to-many lead provenance;
- fail-closed document intake, including path and archive attacks;
- numeric/currency normalization, contradiction/trajectory separation, and
  fixed-denominator evidence scoring;
- workflow revisions, transition validation, idempotency, and cancellation;
- pre-mutation outer workflow-request payload claims and globally bound intake
  extraction replay;
- frozen contradiction/history ledgers and database-derived final-evaluation
  identity/blocking guards;
- scoped, expiring, one-use approvals with hashed tokens;
- durable notification deduplication, retries, and attempt history; and
- append-only audit data plus least-privilege runtime grants.

No test may be skipped in a passing G4 result. Missing tools, dependencies,
migrations, helper entry points, or runtime evidence make the gate fail.
