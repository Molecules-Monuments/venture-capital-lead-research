# SPDX-License-Identifier: Apache-2.0
"""The one shipped approval checkpoint must be one the pinned runtime honours.

`scripts/validate_workflows.py` rejects `approval: false`, but that rule tests
for the Python literal only. The pinned runtime decides whether a step pauses
with a wider predicate (`isApprovalStep`), so `approval: 0`, `approval: null`,
`approval: ""`, `approval: []` and a deleted `approval:` key all mean "no
pause" to the runtime while passing that rule. Widening the detector cannot
close this: the simplest spelling — deleting the key — is invisible to any
rule keyed on the key's value.

So pin the fact that matters instead. The world here is enumerable and small:
across the whole shipped inventory exactly one step declares an `approval:`,
and this suite asserts which one, that its value satisfies the runtime's own
predicate, and that the step declares no execution key. The last part matters
because the runtime evaluates the approval branch *after* it records the
step's result (`dist/src/workflows/file.js:970-976`): a step carrying both an
execution form and an approval runs first and pauses afterwards. (Nothing in
this suite claims the step key list is closed — `EXECUTION_KEYS` below is the
list the pinned runtime counts, quoted with its source lines.)

The runtime predicate is transcribed, not imported — the package vendors no
runtime JavaScript, only the version pin in
`runtime-packages/package.json`. That pin is asserted below, so bumping the
runtime fails this suite and forces someone to re-read `isApprovalStep`
against the new release.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = ROOT / "workspaces/vc-chief/vc/workflows"
RUNTIME_PACKAGES = ROOT / "runtime-packages/package.json"

# The runtime release the predicate and step-shape rules below were read from.
PINNED_LOBSTER = "2026.6.11"

# @clawdbot/lobster 2026.6.11, dist/src/workflows/file.js:224-232 — the forms
# that make a step execute something. A step declaring none of them, and an
# approval the predicate below honours, is a pure checkpoint.
EXECUTION_KEYS = ("run", "command", "pipeline", "workflow", "parallel", "for_each")

# The single approval checkpoint the shipped inventory declares.
APPROVAL_WORKFLOW = "evaluate-lead"
APPROVAL_STEP = "persist_approval"


def is_approval_step(approval: Any) -> bool:
    """Transcription of `isApprovalStep` (dist/src/workflows/file.js:1543-1550).

    JavaScript: `true`, a string whose trim is non-empty, or a truthy object
    that is not an array. YAML `null`/`0`/`""`/`[]`/`false` all fall through to
    `return false`, and so does an absent key (`step.approval` is `undefined`).
    Note that `approval: 1` is *not* honoured either: the first branch is `===`
    against `true`, not a truthiness test. An empty mapping, on the other hand,
    *is* — `Boolean({})` is true in JavaScript — so this returns True for `{}`.
    """
    if approval is True:
        return True
    if isinstance(approval, str):
        return bool(approval.strip())
    return isinstance(approval, dict)


def _expected_workflow_stems() -> set[str]:
    """The release gate's own workflow inventory, so the world cannot shrink.

    `scripts/validate_skill_system.py` compares this constant against the
    directory glob and fails the release on any difference, so deriving the
    enumerated world from it means a workflow cannot disappear from this
    suite's scan without failing the gate first.
    """
    path = ROOT / "scripts/validate_skill_system.py"
    spec = importlib.util.spec_from_file_location("v3_approval_contract_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: the module defines a dataclass, whose machinery
    # resolves the defining module out of sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return set(module.EXPECTED_WORKFLOW_STEPS)


class WorkflowApprovalContractTests(unittest.TestCase):
    documents: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls.documents = {
            path.stem: yaml.safe_load(path.read_text(encoding="utf-8"))
            for path in sorted(WORKFLOW_ROOT.glob("*.lobster"))
        }

    def approval_step(self) -> dict[str, Any]:
        steps = self.documents[APPROVAL_WORKFLOW]["steps"]
        matches = [step for step in steps if isinstance(step, dict) and step.get("id") == APPROVAL_STEP]
        self.assertEqual(
            1, len(matches),
            f"{APPROVAL_WORKFLOW}.lobster no longer has exactly one step with id "
            f"{APPROVAL_STEP!r}; found {len(matches)}",
        )
        return matches[0]

    def test_the_transcribed_runtime_is_the_pinned_one(self) -> None:
        pinned = json.loads(RUNTIME_PACKAGES.read_text(encoding="utf-8"))["dependencies"]["@clawdbot/lobster"]
        self.assertEqual(
            PINNED_LOBSTER, pinned,
            "runtime-packages/package.json now pins @clawdbot/lobster "
            f"{pinned}, but the approval predicate in this suite was read from "
            f"{PINNED_LOBSTER}. Re-read isApprovalStep in the new release, then "
            "update this module's is_approval_step together with the copy in "
            "tests/g4/test_workflow_execution.py — grep `def is_approval_step` "
            "for any further transcription — before moving this constant.",
        )

    def test_the_transcribed_predicate_rejects_the_falsy_spellings(self) -> None:
        # Without this, a transcription that always returned True would satisfy
        # the honoured-approval assertion below while proving nothing.
        # `{}` belongs with the honoured spellings: the runtime's object branch
        # is a JavaScript truthiness test and `Boolean({})` is true.
        for spelling in (True, "Persist this evaluation?", {"prompt": "Persist?"}, {}):
            with self.subTest(honoured=spelling):
                self.assertTrue(
                    is_approval_step(spelling),
                    f"the transcribed isApprovalStep rejects {spelling!r}, which "
                    "the pinned runtime honours — the transcription has drifted",
                )
        for spelling in (False, 0, 1, None, "", "   ", [], ["prompt"]):
            with self.subTest(rejected=spelling):
                self.assertFalse(
                    is_approval_step(spelling),
                    f"the transcribed isApprovalStep honours {spelling!r}, which "
                    "the pinned runtime does not — the transcription has drifted",
                )

    def test_exactly_one_shipped_step_declares_an_approval(self) -> None:
        world = _expected_workflow_stems()
        self.assertEqual(
            world, set(self.documents),
            "the workflow directory and validate_skill_system's inventory "
            "disagree, so this suite is not scanning the whole world",
        )
        declared = sorted(
            (stem, step.get("id"))
            for stem, document in self.documents.items()
            for step in document["steps"]
            if isinstance(step, dict) and "approval" in step
        )
        self.assertEqual(
            [(APPROVAL_WORKFLOW, APPROVAL_STEP)], declared,
            "the set of steps declaring an `approval:` key changed. A new "
            "checkpoint must be added here with its own honoured-value "
            "assertion; a removed one means a reviewed pause is gone.",
        )

    def test_the_shipped_approval_value_is_one_the_runtime_honours(self) -> None:
        step = self.approval_step()
        approval = step.get("approval")
        self.assertTrue(
            is_approval_step(approval),
            f"{APPROVAL_WORKFLOW}.lobster step {APPROVAL_STEP} declares "
            f"approval={approval!r}, which @clawdbot/lobster {PINNED_LOBSTER} "
            "does not treat as an approval step — the run would not pause for "
            "an operator decision. It honours `true`, a non-blank string, or "
            "a mapping.",
        )

    def test_the_shipped_approval_step_declares_no_execution_key(self) -> None:
        step = self.approval_step()
        present = [key for key in EXECUTION_KEYS if key in step]
        self.assertEqual(
            [], present,
            f"{APPROVAL_WORKFLOW}.lobster step {APPROVAL_STEP} declares "
            f"execution key(s) {present}. The pinned runtime records a step's "
            "result before it evaluates the approval branch, so this step "
            "would execute and only then pause.",
        )


if __name__ == "__main__":
    unittest.main()
