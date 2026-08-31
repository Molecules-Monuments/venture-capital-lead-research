# SPDX-License-Identifier: Apache-2.0
"""The postures 2026.8.1 decides for us, and the egress it added.

Two classes of drift that every suite in this package was blind to before the
2026.8.1 upgrade, for the same reason: both are about keys we do **not** set.

`PosturePinTests` pins the settings whose upstream default moved toward
autonomy or toward the network. A default flip is invisible to a schema
validator, to `openclaw config validate`, and to the reviewed-artifact hash —
the file simply says nothing, and the meaning of saying nothing changes under
you. 2026.8.1 flipped grounded dreaming on, the operator terminal on, the
foreground concurrency lane from 4 to a floor of 8, the skill-workshop
approval policy to `auto`, archived-transcript retention from "inherit
pruneAfter" to "keep until the disk budget evicts", and added a personal-recall
key defaulting on. Each row below therefore exists to make the file *say* the
posture, so the next flip fails here instead of shipping.

`RetiredKeyTests` is the other half of the same coin. The seven keys 2026.8.1
retired or renamed are not merely ignored: the root schema is
`strictObject(...)` and the gateway exits 78 before doing anything while one is
present. Re-adding `diagnostics.stuckSessionAbortMs` to restore a tuning knob
is a startup-fatal edit, and this is where it gets caught — offline, on a
laptop, rather than on the deployment host. The names that are unique in the
document are scanned for over the whole tree rather than at a fixed path,
because the residual that made 2026.8.1's own repair planner refuse this config
was a *second* `tools.exec.timeoutSec`, nested under one agent.

`EgressEnumerationTests` replaces a universal with a list. Through 2026.7.1 the
package could truthfully say the gateway made one unsolicited outbound call.
2026.8.1 makes three, and one of them cannot be switched off by any config key,
env var, or plugin setting. A sentence that counts is a sentence that rots, so
the count is gone and the world is enumerated: each host is named, and the
retired singular claim is refused wherever it might come back.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_env  # noqa: E402


# Distinguishes "the key is absent" from "the key is present and null/false",
# which is the whole point: an unset key is where a flipped default gets in.
_MISSING = object()


def _load_shipped() -> dict[str, Any]:
    return json.loads((ROOT / "config/openclaw.json").read_text(encoding="utf-8"))


def _resolve(document: Any, path: str) -> Any:
    """Walk a dotted path, returning the _MISSING sentinel rather than raising."""
    current = document
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


# Every row is source-proven against the 2026.8.1 dist. The third column is why
# the pin exists, not what it does — a reader who wants to remove one needs the
# reason it was added.
POSTURE_PINS: tuple[tuple[str, Any, str], ...] = (
    (
        "plugins.entries.memory-core.config.dreaming.enabled",
        False,
        "grounded dreaming flipped false -> true; memory-core's reconciler does "
        "not consult cron.enabled, so an unpinned default writes a 'Memory "
        "Dreaming Promotion' cron row at every gateway start",
    ),
    (
        "gateway.terminal.enabled",
        False,
        "the operator terminal flipped opt-in (=== true) to opt-out (!== false); "
        "unpinned it is a browser-reachable /bin/bash inside the container that "
        "holds every bot token and API key",
    ),
    (
        "agents.defaults.maxConcurrent",
        3,
        "the top-level agent lane left a hardcoded 4 for "
        "min(16, max(8, availableParallelism())), a floor of 8 on any host; "
        "measured at exactly 8 under the shipped cpus: 2.0",
    ),
    (
        "agents.defaults.utilityModel",
        "",
        "new in 2026.8.1 and unset means auto-derive, which routes session "
        "titles, conversation labels and the progress narrator to a model "
        "outside the approved set; the empty string is the documented disable",
    ),
    (
        "agents.defaults.modelSelectionScope",
        "session",
        "unset lets a bare channel /model persist into the config file; the "
        "read-only mount turns that into a swallowed warning, which is "
        "fail-by-accident rather than policy",
    ),
    (
        "update.checkOnStart",
        False,
        "unset is true: a startup GET to telemetry.openclaw.ai carrying "
        "version, platform, arch and node in the User-Agent, which DO_NOT_TRACK "
        "does not stop",
    ),
    (
        "models.catalogRefresh.enabled",
        False,
        "unset is true: a startup and six-hourly GET to catalog.openclaw.ai, "
        "started before the update-check early return, so the update switches "
        "do not reach it. This key is the only switch",
    ),
    (
        "telemetry.enabled",
        False,
        "already the upstream default, pinned explicitly because "
        "`openclaw telemetry on|off` rewrites the config file and cannot run "
        "against this deployment's read-only mount",
    ),
    (
        "session.maintenance.resetArchiveRetention",
        "30d",
        "2026.8.1 changed the unset meaning from 'inherit pruneAfter' to 'keep "
        "until the disk budget evicts', while archiving on every removal path",
    ),
    (
        "skills.workshop.autonomous.mode",
        "off",
        "the renamed key defaults to 'auto', which applies captured proposals "
        "and runs a daily cleanup that can rewrite or drop writable skills; "
        "deleting the old key rather than replacing it opts into that",
    ),
    (
        "skills.workshop.approvalPolicy",
        "pending",
        "the default moved 'pending' -> 'auto'; this is the one pin that "
        "survives the migration verbatim, and it survives precisely because "
        "the default moved out from under it",
    ),
    (
        "memory.search.enabled",
        False,
        "the posture moved from agents.defaults.memorySearch to memory.search; "
        "renaming a disabled control is exactly how a disabled control becomes "
        "an enabled one",
    ),
    (
        "memory.search.rememberAcrossConversations",
        False,
        "new in 2026.8.1 and true unless session.dmScope is set; today this "
        "resolves false only incidentally, via a dmScope pinned for another "
        "reason, so one unrelated edit would enable cross-conversation recall",
    ),
    (
        "cron.enabled",
        False,
        "not a 2026.8.1 change, but it became load-bearing in this release: the "
        "cron lane's own concurrency is now a hardcoded 8, and it is the only "
        "thing preventing the scheduler from running the rows memory-core "
        "writes regardless of it",
    ),
)

# Keys 2026.8.1 retired or renamed. Splitting them by whether the name is unique
# in this document is not fussiness: `enabled` appears throughout, so it can only
# be checked at a fixed path, while the rest can be swept for anywhere — which is
# what catches a residual nested under one agent rather than at the top level.
RETIRED_UNIQUE_KEYS = (
    "stuckSessionWarnMs",
    "stuckSessionAbortMs",
    "useAccessGroups",
    "maxConcurrentRuns",
    "memorySearch",
    "timeoutSec",
)
RETIRED_KEY_AT_PATH = ("skills.workshop.autonomous", "enabled")

# The complete set of hosts a default 2026.8.1 gateway contacts without being
# asked, measured from the pinned dist rather than from release prose:
#   telemetry.openclaw.ai  dist/telemetry-DcLnYR14.js:49
#                          GET /api/latest-version, startup and <=1x/24h
#   catalog.openclaw.ai    dist/model-catalog-YrXw0PBH.js:148
#                          GET /models/v1/catalog.json, startup and every 6h
#   clawhub.ai             dist/official-external-plugin-catalog-CBlJFCmU.js:32
#                          GET /v1/feeds/plugins, unconditional startup prewarm
#
# The first two are switched off by the pins above. The third has no config key,
# no env var and no plugin-config path; it is deniable only by host egress
# policy. That is the whole reason the singular claim had to go rather than be
# re-worded.
UNSOLICITED_EGRESS_HOSTS = (
    "telemetry.openclaw.ai",
    "catalog.openclaw.ai",
    "clawhub.ai",
)
EGRESS_DOCUMENTS = (
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "docs/RUNBOOK.md",
)
# The claim shape, not the word. CODE_OF_CONDUCT.md uses "unsolicited" in an
# unrelated sense, and a future sentence saying there is *no* single such call
# must not read as the claim it is denying — so match only the definite forms
# that actually assert one.
# CHANGELOG entry headings, e.g. "## [3.0.1] - 2026-08-31". The entry for the
# CURRENT VERSION is a live claim and is scanned; every entry below it is closed
# history describing a base this release no longer pins.
CHANGELOG_ENTRY_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)

SINGULAR_EGRESS_CLAIM = re.compile(
    # Catch the possessive form too ("the gateway's only unsolicited outbound
    # call"), which the definite-article-only pattern missed, and tolerate a
    # line break anywhere inside the phrase — the claim is routinely wrapped.
    r"(?:the|[A-Za-z]+['\u2019]s)\s+(?:only|one|sole|single)\s+unsolicited\s+outbound"
    r"|\ba\s+single\s+unsolicited\s+outbound",
    re.IGNORECASE,
)


class PosturePinTests(unittest.TestCase):
    def test_every_flipped_default_is_pinned_explicitly(self) -> None:
        shipped = _load_shipped()
        for path, expected, reason in POSTURE_PINS:
            with self.subTest(path=path):
                actual = _resolve(shipped, path)
                self.assertIsNot(
                    actual,
                    _MISSING,
                    f"{path} is unset, so this deployment inherits whatever "
                    f"OpenClaw decides. Pin it: {reason}",
                )
                self.assertEqual(
                    expected,
                    actual,
                    f"{path} is {actual!r}, not {expected!r}. {reason}",
                )
                # Guard the JSON true/false vs 0/1 conflation: bool is an int in
                # Python, so assertEqual(False, 0) passes and would let a pin
                # meant as a switch be written as a number.
                self.assertIs(type(expected), type(actual))

    def test_model_allowlist_is_non_empty_and_every_entry_resolves(self) -> None:
        # Two fail-opens, both silent. An empty array means allow-any, and so
        # does an array whose every entry fails to resolve — the policy reverts
        # rather than refusing. Env substitution is deep over array items, so a
        # ${...} entry is legitimate; what it must not be is a reference to a
        # variable nothing guarantees.
        shipped = _load_shipped()
        allow = _resolve(shipped, "agents.defaults.modelPolicy.allow")
        self.assertIsNot(
            allow,
            _MISSING,
            "agents.defaults.modelPolicy.allow is absent, so every catalog "
            "model is reachable through /model and the model picker",
        )
        self.assertIsInstance(allow, list)
        self.assertTrue(allow, "an empty modelPolicy.allow silently means allow-any")
        for entry in allow:
            with self.subTest(entry=entry):
                self.assertIsInstance(entry, str)
                self.assertTrue(entry.strip())
                reference = re.fullmatch(r"\$\{([A-Z0-9_]+)\}", entry)
                if reference is None:
                    continue
                self.assertIn(
                    reference.group(1),
                    check_env.REQUIRED,
                    f"{entry} refers to a variable check_env does not require, "
                    "so it can be absent at runtime; if every entry fails to "
                    "resolve the allowlist reverts to allow-any",
                )


class RetiredKeyTests(unittest.TestCase):
    def test_no_retired_key_survives_anywhere_in_the_document(self) -> None:
        shipped = _load_shipped()
        found: dict[str, list[str]] = {name: [] for name in RETIRED_UNIQUE_KEYS}

        def walk(node: Any, trail: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    here = f"{trail}.{key}" if trail else key
                    if key in found:
                        found[key].append(here)
                    walk(value, here)
            elif isinstance(node, list):
                for index, item in enumerate(node):
                    walk(item, f"{trail}[{index}]")

        walk(shipped, "")
        for name, sites in found.items():
            with self.subTest(key=name):
                self.assertEqual(
                    [],
                    sites,
                    f"{name} was retired or renamed in OpenClaw 2026.8.1. The "
                    "schema is strict, so the gateway exits 78 before doing "
                    f"anything while it is present at {sites}",
                )

    def test_the_retired_workshop_autonomy_flag_is_gone_from_its_own_path(self) -> None:
        # Checked at a path rather than swept for: `enabled` is a legitimate key
        # in a dozen places. The replacement is the `mode` pin in POSTURE_PINS,
        # and the pair matters — deleting this key without adding that one opts
        # into the new "auto" default rather than out of it.
        shipped = _load_shipped()
        parent_path, retired = RETIRED_KEY_AT_PATH
        parent = _resolve(shipped, parent_path)
        self.assertIsNot(parent, _MISSING, f"{parent_path} is absent entirely")
        self.assertNotIn(
            retired,
            parent,
            f"{parent_path}.{retired} was renamed to .mode in OpenClaw 2026.8.1 "
            "and is now a startup-fatal unrecognized key",
        )


class EgressEnumerationTests(unittest.TestCase):
    def test_no_document_still_claims_a_single_unsolicited_outbound_call(self) -> None:
        # The world is manifest.json's declared inventory, not a glob of the
        # tree. Two reasons, and the second is the binding one. It is the
        # package's own source of truth for "documents this release ships", so
        # a new document is covered the moment it is declared. And a gate may
        # only assert things about content the package CONTROLS: an rglob would
        # reach `inbox/` and `quarantine/`, where an operator's own payload
        # lives, and a founder's memo that happened to contain this phrase would
        # fail the release gate for a documented operator action. The manifest
        # excludes those roots by construction.
        offenders = []
        for relative in sorted(
            entry["path"]
            for entry in json.loads(
                (ROOT / "manifest.json").read_text(encoding="utf-8")
            )["files"]
            if entry["path"].endswith(".md")
        ):
            document = ROOT / relative
            if not document.is_file():
                continue
            text = document.read_text(encoding="utf-8")
            # CHANGELOG.md is a ledger of past releases. An entry for a shipped
            # release describing what was true of THAT release's pinned base is
            # a historical record, not a live claim, and rewording it would
            # falsify the ledger. Scan only the text above the first released
            # entry heading; everything below it is closed history.
            if relative == "CHANGELOG.md":
                current = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
                superseded = next(
                    (
                        match
                        for match in CHANGELOG_ENTRY_HEADING.finditer(text)
                        if match.group(1) != current
                    ),
                    None,
                )
                if superseded:
                    text = text[: superseded.start()]
            if SINGULAR_EGRESS_CLAIM.search(text):
                offenders.append(relative)
        self.assertEqual(
            [],
            offenders,
            "a default 2026.8.1 gateway makes three unsolicited outbound calls, "
            f"not one: {', '.join(UNSOLICITED_EGRESS_HOSTS)}. Enumerate them "
            "rather than counting them",
        )

    def test_every_unsolicited_host_is_named_where_the_surface_is_described(self) -> None:
        # Naming all three is the whole point: two are switchable and the third
        # is not, so a reader who is told about two of them will build an egress
        # policy that fails open on the one they were not told about.
        for relative in EGRESS_DOCUMENTS:
            body = (ROOT / relative).read_text(encoding="utf-8")
            for host in UNSOLICITED_EGRESS_HOSTS:
                with self.subTest(document=relative, host=host):
                    self.assertIn(
                        host,
                        body,
                        f"{relative} describes this deployment's outbound "
                        f"surface but never names {host}",
                    )


if __name__ == "__main__":
    unittest.main()
