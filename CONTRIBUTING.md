# Contributing

Thank you for considering a contribution. This document is the practical route
from a clone to a merged pull request: what the project is, how to propose a
change, which checks have to be green before you ask for review, and what a
maintainer looks for once you do.

## What this project is

The Venture Capital Lead Research System 3.0 is a self-hosted, evidence-first
multi-agent system for venture-capital lead research. It discovers and receives
company leads, resolves company identity, gathers founder, traction, market and
contradiction evidence with its provenance intact, qualifies leads against a
customizable fixed-denominator rubric, and writes internal memos from a frozen
snapshot of what was actually supported. It runs on the operator's own host,
against the operator's own PostgreSQL database, under a set of authority
boundaries that keep a model lane from approving its own work. There is no
hosted service and nothing phones home.

Two documents matter before you change anything:

- [README.md](README.md) is the architecture, scope, setup and risk reference.
  Read at least *Purpose and scope*, *Developer quick start*, and *Testing*.
  The scope section is load-bearing for review: several plausible-sounding
  features are excluded on purpose, and a pull request that adds one will be
  declined on scope rather than on quality.
- [docs/MAINTAINING.md](docs/MAINTAINING.md) holds the engineering rules that
  govern changes to the code — the linters and their exact invocations, what
  else a Python change requires, how documented counts and enumerations are
  mechanized, and how a release is re-pinned. This file is the
  contributor-facing summary of those rules. Where the two disagree,
  [docs/MAINTAINING.md](docs/MAINTAINING.md) is the authority.

## Security problems do not go through a pull request

If you have found a way to cross a boundary this package claims to enforce —
a model lane reaching an operator-only surface, a forged trusted-context token,
a quarantine bypass, a secret recoverable from a backup or an image layer —
stop here and follow [SECURITY.md](SECURITY.md) instead. Do not open a public
issue and do not open a pull request: a public patch discloses the problem
before a fix exists, and the diff is usually a working exploit. Ordinary bugs,
including crashes and wrong results that cross no boundary, are normal pull
requests and belong here.

## Fork, branch, pull request

The flow is plain git plus the GitHub web interface. Nothing beyond that is
required.

1. **Fork** the repository with the *Fork* button on its GitHub page.

2. **Clone your fork and branch off `main`.** Every change starts from `main`;
   there is no develop or release branch.

   ```sh
   git clone https://github.com/<your-account>/<repository>.git
   cd <repository>
   git switch --create <short-topic-name> main
   ```

3. **Make one logical change.** One pull request is one change: a bug fix, or a
   refactor, or a documentation correction — not all three. A branch that
   carries three unrelated changes is three reviews a maintainer has to do at
   once and cannot accept separately, so the whole branch waits on its weakest
   part. If you notice something else while you are in there and it is genuinely
   trivial, fold it in and say so in the description; if it is not trivial, it
   is a second branch.

   For anything large, or anything that changes behaviour an operator depends
   on, open an issue first and agree the direction before writing the code. A
   correct implementation of a change the project does not want is still a
   decline, and that is a waste of your time rather than ours.

4. **Commit** using the convention below, then push the branch to your fork:

   ```sh
   git push --set-upstream origin <short-topic-name>
   ```

5. **Open the pull request** against `main`. GitHub offers a *Compare & pull
   request* button on your fork for a few minutes after the push; the *Pull
   requests* tab of the upstream repository works at any time.

6. **Bring the branch up to date before asking for review.** Rebase or merge —
   either is accepted, so use whichever you are comfortable with. What matters
   is that the reviewer sees your change against current `main` rather than
   against a tree from three weeks ago.

   ```sh
   git remote add upstream https://github.com/<owner>/<repository>.git  # once
   git fetch upstream
   git rebase upstream/main          # or: git merge upstream/main
   git push --force-with-lease       # after a rebase only
   ```

   Use `--force-with-lease` rather than `--force`: it refuses the push if the
   remote branch moved since you last fetched, which is exactly the case where a
   forced push would silently discard someone else's work — including a commit
   you made from another machine.

## Run the checks before you submit

Everything in this section runs on your own machine, offline. No database, no
Docker, no network and no credential is needed. You need Python 3.11 or newer
and a POSIX shell.

### Create the developer virtualenv

The checkers and test dependencies are hash-pinned in `requirements-dev.lock`.
Install them into a disposable virtualenv created *outside* the package, as
README's *Developer quick start* describes. Outside is not a preference: a venv
inside the package puts thousands of undeclared files into the release tree, and
the pristine check below then fails on your tooling instead of on your change.

```sh
cd <path-to-the-package-root>
python3 -m venv ../openclaw-v3-dev-venv
../openclaw-v3-dev-venv/bin/python -m pip install \
  --disable-pip-version-check --require-hashes -r requirements-dev.lock
```

Keep `--require-hashes`. It is what makes the dependency graph reproducible, and
dropping it changes what the checkers below are actually running.

### The five commands

Run all five from the package root. Each must exit `0`.

```sh
VENV="../openclaw-v3-dev-venv"

"$VENV/bin/ruff" check . --exclude _internal --no-cache
"$VENV/bin/ty"   check . --python "$VENV" --python-version 3.11 --extra-search-path scripts
python3 -B scripts/build_release_manifest.py
python3 -B scripts/verify_release.py --pristine
"$VENV/bin/python" -B scripts/verify_offline.py
```

Check the exit status of each one. Neither `ruff` nor `ty` prints a non-zero
status in a form a pipeline preserves, so do not pipe them through `head` or
`tail` when the result is what you care about.

`build_release_manifest.py` re-pins the release inventory and prints the delta it
absorbed. **Read that delta.** Every path in it should be a file you changed on
purpose. A path you do not recognise is an integrity finding rather than a
re-pin — find out where it came from before you commit it.

`verify_offline.py` is the broad one: the offline test suites plus Python and
shell syntax, `ruff`, `ty`, skill/agent/router validation, fixed-workflow
validation, manifest currency, and the pristine release inventory. It resolves
both checkers from its own virtualenv before falling back to `PATH`, so the
pinned versions decide the result. Run it under the venv interpreter as shown;
the host `python3` has neither the checkers nor the locked test dependencies and
will report `FAIL` on a perfectly good package.

### Why `--no-cache` and `-B`

`verify_release.py --pristine` compares the tree against `manifest.json` and
treats *any* undeclared file inside the package as a tampering signal. That is
its job — it is the operator-facing check that the copy about to be deployed is
the copy that was released. A `.ruff_cache/` directory left behind by `ruff`, or
a `__pycache__/` left behind by an ordinary `python3` invocation, is precisely
such a file. So `--no-cache` stops `ruff` writing its cache, and `-B` stops
CPython writing bytecode; without them the gate fails on your tooling's litter
and tells you nothing about your change. `ty` writes no cache and needs no
equivalent flag.

If a checker reports something you believe is wrong, fix the code first. Do not
widen `ruff.toml` and do not add a blanket ignore — the rule selection was
measured against this tree, and removing a rule to make one finding go away
removes it everywhere. A genuine false positive is suppressed on the single
line that provokes it, with a comment saying why the checker is wrong.
[docs/MAINTAINING.md](docs/MAINTAINING.md) gives the full rules, including the
exact directive syntax and what else a Python change requires beyond green
checkers.

### The gates you are not expected to run

Three further gates need infrastructure:

- **G4**, the database gate (`scripts/run_g4.py`, reached with
  `verify_offline.py --with-g4-database`), creates a disposable local
  PostgreSQL 17 cluster and proves the SQL-level boundaries against it.
- **G6**, the image gate (`verify_offline.py --with-g6-image
  vc-lead-research:3.0.0`), probes a built Docker image with the network
  disabled and verifies exact pinned versions.
- **G8**, the deployment gate (`scripts/run_g8_deployment.py`), exercises a
  live, commissioned deployment.

They need PostgreSQL 17 tools, Docker, and a real deployment respectively, and
no outside contributor is expected to have all three. Run whichever ones you
have if your change touches `migrations/`, `Dockerfile.openclaw`,
`docker-compose.yml`, or the lifecycle scripts — and either way, say in the pull
request which gates you ran and which you could not. Continuous integration runs
the offline gates on every pull request, and a maintainer runs the
infrastructure gates before merging anything that depends on them.

## Commit messages

The existing history is the convention. `git log --format='%s' -40` in a clone
shows it directly. Match what you see there:

- A **summary line in the present tense**, imperative or declarative, saying
  what the change does — "Make the release gate runnable on the platform it
  ships to", "Stop the band-edge gate refusing the customization it exists to
  protect". Keep it under about 72 characters, capitalize the first word, and
  leave off the trailing full stop. This project uses no type prefixes, no
  ticket numbers, and no emoji in the summary.
- A **blank line**.
- A **body that explains why the change is right**, not what the diff already
  shows. State the behaviour that was wrong, what proves it wrong — a file and
  line, a script's actual output, a test that fails — and what evidence supports
  the new behaviour. Where a gate result is that evidence, give the measured
  numbers rather than "tests pass". Wrap the body at roughly 72 to 79 columns.

Commits must **not** carry a `Co-Authored-By` trailer naming an automated
assistant. If you used a tool to help write the change, that is your business
and needs no trailer: you reviewed it, you are submitting it, and you are the
author of record. A `Co-Authored-By` naming a human who genuinely co-wrote the
change is welcome.

## What a good pull request contains

A description that answers four questions, so the reviewer does not have to
reconstruct them from the diff:

1. **What changed** — a couple of sentences, not a file list.
2. **Why it is right** — the wrong behaviour, and how you know it was wrong.
3. **Which gates you ran and what they returned** — paste the counts and the
   final status. Name any gate you could not run and why.
4. **For a behaviour change, the test that would have failed before.** Name it
   by module and test name.

That fourth point comes from a standing rule of this project: **a fix without an
enforcing check is deferred recurrence.** Fixing the instance closes the
instance; only a test or a gate closes the *class*, and an unenforced fix comes
back the next time someone edits nearby code, usually in a shape nobody
recognises. So a bug fix should arrive together with a test that fails without
it.

Verify that both ways round before you submit: revert or stash the fix, run the
new test, and watch it fail; then restore the fix and watch it pass. A test that
passes against the unfixed code proves nothing at all, and this is the single
most common thing that sends a pull request back.

## Documentation changes

Documentation is held to the same gates as code, and for a concrete reason:
several offline tests bind what the documents *say* to what the tree *is*. Gate
and test counts quoted in the evidence documents are checked against fresh test
discovery. The erasure-gap list is checked against every table in
`docs/SCHEMA.sql`, so a new table fails the gate until it has been consciously
categorized. Documented command invocations are checked against the scripts they
name.

Two consequences for a documentation-only pull request. First, run the same five
commands above; a Markdown-only change really can fail `verify_offline.py`.
Second, when it does, the gate is working: the prose made a claim the tree does
not support. Correct the document to the measured value — never weaken the test
to match the sentence. Some of these numbers are generated state with a script
of their own rather than text to be hand-edited;
[docs/MAINTAINING.md](docs/MAINTAINING.md) names which, and how to move them.

The same standard applies to new prose. If you write a sentence containing
"only", "every", "all", "none" or "complete", it is a claim about a whole world,
and it needs a test that enumerates that world from the source of truth. If you
cannot back it that way, write the weaker sentence that is true.

## Sign off your commits

Contributions are accepted under the project's own licence, Apache-2.0, and are
certified with a **Developer Certificate of Origin** sign-off rather than a
signed agreement. There is nothing to print, nothing to email, and no personal
data collected beyond what git already records.

Add `-s` when you commit:

```sh
git commit -s -m "Your commit message"
```

That appends one line to the commit message:

```
Signed-off-by: Your Name <your.email@example.com>
```

The name and email must be real and must match the commit author. By adding it
you certify the [Developer Certificate of Origin 1.1](DCO) — in short, that you
wrote the change or otherwise have the right to submit it under this project's
licence, and that you understand the contribution and its sign-off are public
and kept indefinitely.

Every commit in a pull request needs the line. If you forget on the last commit,
`git commit --amend -s` fixes it; for a whole branch,
`git rebase --signoff main` does. There is no bot and no automated status check:
a maintainer verifies the sign-offs by reading them, the same way the rest of
the review works.

One thing to know in advance, so it is never a surprise. The maintainers may ask
for a signed contributor agreement before merging a contribution they intend to
relicense — for instance into a commercially licensed edition of this software.
That has not been necessary so far, no such agreement is in force, and the
sign-off above is all that is asked of you today. If it ever becomes relevant to
a change of yours, you will be told before the work is merged, not after.

## Code of conduct

Participation in this project is governed by
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). It applies to issues, pull requests,
commit messages, and any other project space. Report a concern privately to
<mvrecko@moleculesandmonuments.com>.

## What to expect from the maintainers

This project has two maintainers and is maintained on a best-effort basis
alongside other work. There is **no service-level agreement** and no promised
response time. Review may be slow, and it will be slower for a change that needs
an infrastructure gate a maintainer has to schedule. A polite comment on your
own pull request after a stretch of silence is reasonable rather than rude.

In return, a decline comes with its reason. If a change is turned down on scope,
on evidence, or on a boundary it would weaken, you will be told which — so you
can judge whether a different approach would land.

Because the project is small, it is worth stating the other side of that
plainly. The system is released under Apache-2.0 (see [LICENSE](LICENSE);
Copyright 2026 Molecules & Monuments GmbH). That license lets anyone fork this
project and carry it in their own direction, including a direction the
maintainers would not take, and including the case where the maintainers stop
altogether. A fork is an accepted outcome of a small project rather than a
failure of one, and no permission is needed for it. Preserve the license and the
notices in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and the rest is
yours to run with.
