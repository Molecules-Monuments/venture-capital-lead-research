# Wave G7 recovery lifecycle gate

Run from the package root:

```sh
python3 -B -m unittest discover -s tests/g7 -p 'test_*.py' -v
```

The gate is a hard pass only when every test succeeds. It checks the offline
release contract for fixed Compose targeting, quiesced and atomically published
recovery points, state exclusions, inbox/quarantine and database-artifact hash
coverage, staged fail-closed restore, atomic migration registration, matching
prior-lock/prior-version update metadata, pinned upstream RepoDigests, and
Docker-live image-ID mismatch handling through a mocked Docker boundary.

This gate proves the package's recovery and lifecycle algorithms. It does not
claim a destructive target-host restore, provider/model connectivity, or
channel delivery; those are deployment-commissioning exercises outside the
Version 3.0 package-readiness scope.
