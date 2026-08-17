# SPDX-License-Identifier: 0BSD
"""Which arguments each `*-request-claim` step actually records, pinned both ways.

`docs/DATA_MODEL.md` describes `workflow_requests` as the row that claims the
canonical inbound/outbound outer payload before any business mutation, and
`vcops` fails a replay whose claim payload hashes differently. What that
protects is decided by one thing: which of the workflow's arguments the
`.lobster` claim step forwards to `vcops-workflow *-request-claim`. An argument
the step does not pass is not in the claim payload, so a replay that changes
only that argument gets past the claim.

That subset is invisible in both directions. Add a key to a `vcrun` contract and
nothing makes you extend the claim; drop a `--flag` from a claim step and every
existing test still passes, because the step still runs and still returns a
`workflow_request`. So this suite hardcodes both sides for each claim-bearing
workflow — the arguments `vcrun` accepts, and the subset the claim step
forwards — and fails on any movement in either.

The expectations below were measured from the tree, not designed. One gap is
deliberate and is the reason the DATA_MODEL bullet does not claim completeness:
`inbound-text-intake` accepts `origin_subtype` but does not forward it to the
claim. Two later checks still see it: `create-lead` hashes it into
`leads.request_hash` and refuses a differing replay with
`idempotency_payload_mismatch`, and `workflow-start` records the `input_digest`
`vcrun` computes as the sha256 of the validated, normalized argument payload.
Both run after the claim, not before it. If a future change closes that gap,
update `UNCLAIMED` below along with the workflow's entry.

Discovery is a glob over the whole `.lobster` inventory, so a claim step added
to another workflow, removed, or renamed fails the first test rather than
slipping past the per-workflow checks.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = ROOT / "workspaces/vc-chief/vc/workflows"
VCRUN_PATH = ROOT / "workspaces/vc-chief/vc/bin/vcrun.py"

# The three `vcops-workflow` subcommands that write a `workflow_requests` row
# all end in this; matching the suffix keeps discovery independent of which
# spelling a workflow uses (`workflow-`, `document-`, `document-association-`).
CLAIM_MARKER = "request-claim"


def _load_vcrun() -> ModuleType:
    """Import vcrun.py by path, the way tests/g5/test_vcrun.py does."""
    spec = importlib.util.spec_from_file_location("v3_claim_coverage_vcrun", VCRUN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


vcrun = _load_vcrun()


class ClaimStep(NamedTuple):
    """One workflow's claim step, as measured from the shipped tree."""

    step_id: str
    # Everything `vcrun.WORKFLOWS[<workflow>]` accepts from the caller:
    # `keys` plus `optional_keys`. `input_digest` is not here — the runner
    # injects it after validation and refuses it from a caller.
    accepted_args: frozenset[str]
    # The subset the claim step passes on to `vcops-workflow`, and therefore
    # the subset inside the claim's request payload and its hash.
    claimed_args: frozenset[str]


EXPECTED: dict[str, ClaimStep] = {
    "document-ingest": ClaimStep(
        step_id="document_request",
        accepted_args=frozenset({"document_path", "idempotency_key", "trusted_context"}),
        claimed_args=frozenset({"document_path", "idempotency_key", "trusted_context"}),
    ),
    "document-lead-intake": ClaimStep(
        step_id="workflow_request_claim",
        accepted_args=frozenset({
            "company_domain", "company_name", "extraction_id",
            "idempotency_key", "lead_title", "trusted_context",
        }),
        claimed_args=frozenset({
            "company_domain", "company_name", "extraction_id",
            "idempotency_key", "lead_title", "trusted_context",
        }),
    ),
    "inbound-intake": ClaimStep(
        step_id="workflow_request_claim",
        accepted_args=frozenset({
            "channel_account_id", "channel_event_id", "channel_provider",
            "company_domain", "company_name", "document_path",
            "idempotency_key", "lead_title",
        }),
        claimed_args=frozenset({
            "channel_account_id", "channel_event_id", "channel_provider",
            "company_domain", "company_name", "document_path",
            "idempotency_key", "lead_title",
        }),
    ),
    "inbound-text-intake": ClaimStep(
        step_id="workflow_request_claim",
        accepted_args=frozenset({
            "company_domain", "company_name", "idempotency_key",
            "lead_title", "origin_subtype",
        }),
        claimed_args=frozenset({
            "company_domain", "company_name", "idempotency_key", "lead_title",
        }),
    ),
    "outbound-scout": ClaimStep(
        step_id="workflow_request_claim",
        accepted_args=frozenset({
            "company_domain", "company_name", "idempotency_key", "lead_title",
        }),
        claimed_args=frozenset({
            "company_domain", "company_name", "idempotency_key", "lead_title",
        }),
    ),
}

# Derived from EXPECTED and restated so the gap is legible rather than implied:
# accepted arguments that no claim step records.
UNCLAIMED: dict[str, frozenset[str]] = {"inbound-text-intake": frozenset({"origin_subtype"})}


def _forwarded(body: str, argument: str) -> bool:
    """Whether a step body reads `$LOBSTER_ARG_<ARGUMENT>`.

    Anchored on the `$` and terminated by a word boundary so that one argument
    name being a prefix of another cannot make the shorter one look forwarded.
    """
    return re.search(rf"\$LOBSTER_ARG_{re.escape(argument.upper())}\b", body) is not None


def _discovered_claim_steps() -> dict[str, list[tuple[str, str]]]:
    """Workflow stem -> [(step id, run body)] for every step that claims a request."""
    found: dict[str, list[tuple[str, str]]] = {}
    for path in sorted(WORKFLOW_ROOT.glob("*.lobster")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for step in document["steps"]:
            if not isinstance(step, dict):
                continue
            body = step.get("run")
            if isinstance(body, str) and CLAIM_MARKER in body:
                found.setdefault(path.stem, []).append((str(step.get("id")), body))
    return found


class WorkflowClaimStepCoverageTests(unittest.TestCase):
    def test_the_claim_bearing_steps_are_the_expected_ones(self) -> None:
        discovered = sorted(
            (stem, step_id)
            for stem, steps in _discovered_claim_steps().items()
            for step_id, _ in steps
        )
        expected = sorted((stem, entry.step_id) for stem, entry in EXPECTED.items())
        self.assertEqual(
            expected, discovered,
            "the set of .lobster steps that run a *-request-claim command has "
            "changed. A new one needs its own entry below (with the arguments "
            "it forwards); a removed one means a workflow now mutates business "
            "tables without claiming an outer request first.",
        )

    def test_each_runner_contract_accepts_the_expected_arguments(self) -> None:
        for workflow, entry in sorted(EXPECTED.items()):
            with self.subTest(workflow=workflow):
                self.assertIn(
                    workflow, vcrun.WORKFLOWS,
                    f"vcrun no longer defines a contract for {workflow}",
                )
                contract = vcrun.WORKFLOWS[workflow]
                accepted = set(contract["keys"]) | set(contract.get("optional_keys", set()))
                self.assertEqual(
                    set(entry.accepted_args), accepted,
                    f"vcrun's {workflow} contract now accepts a different "
                    "argument set. Decide whether the new argument belongs in "
                    f"the {entry.step_id} claim payload before updating this "
                    f"expectation.\n  expected: {sorted(entry.accepted_args)}"
                    f"\n  vcrun:    {sorted(accepted)}",
                )

    def test_each_claim_step_forwards_the_expected_arguments(self) -> None:
        discovered = _discovered_claim_steps()
        for workflow, entry in sorted(EXPECTED.items()):
            with self.subTest(workflow=workflow):
                steps = discovered.get(workflow, [])
                self.assertEqual(
                    1, len(steps),
                    f"{workflow}.lobster has {len(steps)} steps running a "
                    f"{CLAIM_MARKER} command; this suite expects exactly one "
                    f"({entry.step_id})",
                )
                step_id, body = steps[0]
                self.assertEqual(entry.step_id, step_id, f"{workflow}.lobster renamed its claim step")
                forwarded = {
                    argument for argument in entry.accepted_args if _forwarded(body, argument)
                }
                self.assertEqual(
                    set(entry.claimed_args), forwarded,
                    f"{workflow}.lobster step {step_id} forwards a different "
                    "set of the workflow's arguments to the claim, which "
                    "changes what a replay is checked against.\n"
                    f"  expected: {sorted(entry.claimed_args)}\n"
                    f"  step:     {sorted(forwarded)}\n"
                    f"  dropped:  {sorted(set(entry.claimed_args) - forwarded)}\n"
                    f"  added:    {sorted(forwarded - set(entry.claimed_args))}",
                )

    def test_the_recorded_gap_matches_the_expectations(self) -> None:
        # Keeps UNCLAIMED honest against EXPECTED, so the docstring's statement
        # about origin_subtype cannot outlive the data it describes.
        gaps = {
            workflow: frozenset(entry.accepted_args) - frozenset(entry.claimed_args)
            for workflow, entry in EXPECTED.items()
        }
        self.assertEqual(
            UNCLAIMED, {workflow: gap for workflow, gap in gaps.items() if gap},
            "the arguments accepted but not recorded in a claim no longer "
            "match UNCLAIMED; update it and the docstring together",
        )


if __name__ == "__main__":
    unittest.main()
