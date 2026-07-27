# Wave G5 adversarial workflow gate

Run from the package root:

```sh
python3 -B -m unittest discover -s tests/g5 -p 'test_*.py' -v
```

This suite tests the release validator and the fixed runner without a database,
gateway, network, or workflow execution. It is also run as the `g5` suite of
`scripts/verify_offline.py`, which is the single deterministic entry point.

The hard gate validates every packaged `.lobster` file with safe YAML,
`vcops.build_parser()`, and the exact pinned Lobster v2026.6.11 graph and
dry-run parser. It also performs negative runtime probes against `vcrun` and
checks Task Flow/Lobster persistence, recovery, authority, approval, and cron
release documentation.

The gate is a hard pass only when every test succeeds. A nonzero validator exit
is a hard failure; it is never interpreted as a skip.
