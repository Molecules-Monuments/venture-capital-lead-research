<!--
Thank you for contributing to the Venture Capital Lead Research System.

Keep every section below. An empty section is an answer too: write "none" or
"not applicable" rather than deleting the heading, so a reviewer can tell an
omission from a deliberate no.
-->

## What changed, and why

<!--
The change in a few sentences, and the reason for it. If it closes an issue,
link it. If it changes behaviour an operator could be relying on, say so here
in plain words — that sentence is what a release note is written from.
-->

## Gates

Run from the package root. These commands call the developer virtualenv **by
path**, the form `CONTRIBUTING.md` uses, so they work whether or not you have
activated it — README's *Developer quick start* shows the activated form if you
prefer that. The order matters:
`build_release_manifest.py` re-pins the inventory that `--pristine` then
verifies, and `--pristine` must see a tree with no caches in it, which is why
Python runs with `-B` and Ruff with `--no-cache`.

```sh
VENV="../openclaw-v3-dev-venv"

"$VENV/bin/ruff" check . --exclude _internal --no-cache
"$VENV/bin/ty"   check . --python "$VENV" --python-version 3.11 --extra-search-path scripts
python3 -B scripts/build_release_manifest.py
python3 -B scripts/verify_release.py --pristine
"$VENV/bin/python" -B scripts/verify_offline.py
```

Both linters are also gate steps inside `verify_offline.py`, so the last
command is the backstop; running them directly is the fast feedback loop while
you work. Tick what you ran, and say what it reported:

- [ ] `"$VENV/bin/ruff" check . --exclude _internal --no-cache` — exit `0`
- [ ] `"$VENV/bin/ty" check . --python "$VENV" --python-version 3.11 --extra-search-path scripts` — exit `0`
- [ ] `python3 -B scripts/build_release_manifest.py` — re-pinned, I read the
      printed delta, and `manifest.json` is staged in this pull request
- [ ] `python3 -B scripts/verify_release.py --pristine` — `PASS`
- [ ] `"$VENV/bin/python" -B scripts/verify_offline.py` — `PASS` (paste the
      totals it printed)
- [ ] Database (G4), image (G6), deployment (G8), and retrieval-scale gates —
      result, or **not run — needs PostgreSQL 17 / Docker**

That last line is a real answer, not an excuse. Those gates need a PostgreSQL
17 installation, a Docker daemon, and in the G8 case a host willing to have a
throwaway deployment built on it, so they are deliberately absent from
continuous integration and are run by a maintainer before a release. Say which
of them you could not run and why, and a maintainer will run them.

## Evidence for a behaviour change

<!--
For anything that changes behaviour — a bug fix, a new refusal, a changed
default — name the test that fails without the change and passes with it, and
say which suite it lives in. A fix with no check behind it is a defect that has
been postponed rather than closed, because nothing stops the next change from
reintroducing it.

Documentation-only changes need this too when the document states a count, an
enumeration, or a command: those are bound to the tree by tests, and the
binding is the point.
-->

## Developer Certificate of Origin

- [ ] Every commit in this pull request carries a `Signed-off-by:` line
      matching its author (`git commit -s`), certifying the
      [Developer Certificate of Origin 1.1](https://github.com/Molecules-Monuments/venture-capital-lead-research/blob/main/DCO) as described in
      `CONTRIBUTING.md`.
