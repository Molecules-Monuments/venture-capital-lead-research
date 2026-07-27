# G5 adversarial workflow gate

This suite tests the release validator and fixed runner without a database,
gateway, network, or workflow execution.

Run from the `Version_2` directory:

```bash
python3 -m unittest discover -s complete_update/tests/g5 -p 'test_*.py' -v
python3 intermediate/validate_g5.py --output qa/g5-workflows.json
```

The hard gate validates every packaged `.lobster` file with safe YAML,
`vcops.build_parser()`, and the exact pinned Lobster v2026.6.11 graph and
dry-run parser. It also performs negative runtime probes against `vcrun` and
checks Task Flow/Lobster persistence, recovery, authority, approval, and cron
release documentation.

`qa/g5-current.json` is retained as the pre-migration red result. A nonzero
validator exit is a hard failure; it is never interpreted as a skip.

