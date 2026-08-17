# SPDX-License-Identifier: 0BSD
"""The inbound origin subtype vocabulary is written down twice; pin them together.

`inbound-intake-analyst` returns `result.origin.subtype`, whose accepted values
are fixed by an `enum` in `workspaces/schemas/inbound-intake-analyst.output.schema.json`.
The chief then hands that value to `vcrun run inbound-text-intake
--origin_subtype ...`, and the runner re-checks it against a set literal spelled
out inline in `validate_workflow_args`. Neither side reads the other, so the two
lists can drift apart: a value added to the schema but not to the runner is
accepted from the analyst and then refused at the workflow boundary, and a value
added to the runner but not the schema makes the analyst's own output invalid.

`tests/g5/test_vcrun.py` already binds the runner guard to the operator-facing
table in `docs/WORKFLOWS.md` (`DocumentedValueDomainTests.DOMAINS`). This suite binds
the third copy — the analyst output schema — to the same guard. Only the
canonical schema under `workspaces/schemas/` is read here; its byte-identical
mirror at `workspaces/vc-chief/vc/schemas/` is held in step by
`tests/contracts/test_envelope_contracts.py`.

The runner set is extracted from vcrun.py's syntax tree rather than imported,
because it is an inline literal in the guard expression and not a module
constant. Extracting it by parsing means the assertion below tracks the literal
the runner actually evaluates, not a copy of it kept somewhere else.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VCRUN_PATH = ROOT / "workspaces/vc-chief/vc/bin/vcrun.py"
SCHEMA_PATH = ROOT / "workspaces/schemas/inbound-intake-analyst.output.schema.json"

# The JSON pointer, as path segments, that the analyst schema puts the subtype
# vocabulary behind.
SCHEMA_POINTER = (
    "properties", "result", "properties", "origin", "properties", "subtype", "enum",
)

# The runner guard this suite looks for: `parsed["origin_subtype"] not in {...}`.
GUARD_SUBJECT = "parsed"
GUARD_KEY = "origin_subtype"


def _schema_enum() -> list[Any] | None:
    """The list at SCHEMA_POINTER, or None if the schema no longer has one there."""
    node: Any = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for segment in SCHEMA_POINTER:
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    return node if isinstance(node, list) else None


def _guard_comparators() -> list[tuple[int, ast.expr]]:
    """Every `parsed["origin_subtype"] not in <X>` comparison in vcrun.py.

    Returns `(line number, right-hand side)` pairs so a failure can point at
    the source line rather than just report a count.
    """
    tree = ast.parse(VCRUN_PATH.read_text(encoding="utf-8"), filename=str(VCRUN_PATH))
    found: list[tuple[int, ast.expr]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if not isinstance(node.ops[0], ast.NotIn):
            continue
        left = node.left
        if not isinstance(left, ast.Subscript):
            continue
        if not (isinstance(left.value, ast.Name) and left.value.id == GUARD_SUBJECT):
            continue
        if not (isinstance(left.slice, ast.Constant) and left.slice.value == GUARD_KEY):
            continue
        found.append((node.lineno, node.comparators[0]))
    return found


def _string_set_members(node: ast.expr) -> list[str] | None:
    """The members of a set-of-string-literals display, or None if it is not one."""
    if not isinstance(node, ast.Set):
        return None
    members: list[str] = []
    for element in node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        members.append(element.value)
    return members


class InboundSubtypeVocabularyTests(unittest.TestCase):
    def guard_members(self) -> list[str]:
        comparators = _guard_comparators()
        self.assertEqual(
            1, len(comparators),
            f"expected exactly one `{GUARD_SUBJECT}[{GUARD_KEY!r}] not in ...` "
            f"comparison in {VCRUN_PATH.name}, found {len(comparators)} at "
            f"line(s) {[line for line, _ in comparators]}. The runner-side "
            "inbound subtype vocabulary is no longer a single expression, so "
            "this suite cannot tell which one the schema must match.",
        )
        line, comparator = comparators[0]
        members = _string_set_members(comparator)
        self.assertIsNotNone(
            members,
            f"{VCRUN_PATH.name}:{line} no longer compares "
            f"{GUARD_SUBJECT}[{GUARD_KEY!r}] against a set of string literals "
            f"(it is a {type(comparator).__name__}). Either restore the literal "
            "set or teach this suite how to read the new form.",
        )
        assert members is not None  # narrowed by assertIsNotNone above
        self.assertEqual(
            sorted(set(members)), sorted(members),
            f"{VCRUN_PATH.name}:{line} lists a duplicate inbound subtype: {members}",
        )
        return members

    def test_the_runner_guard_is_a_readable_literal_set(self) -> None:
        # Stated as its own case so a change to the guard's shape fails with
        # that as the reported cause rather than as a vocabulary mismatch.
        self.assertNotEqual(
            [], self.guard_members(),
            f"the inbound subtype guard in {VCRUN_PATH.name} is empty, which "
            "would make the comparison below pass against an empty schema enum "
            "while accepting no value at all",
        )

    def test_the_analyst_schema_still_declares_a_subtype_enum(self) -> None:
        enum = _schema_enum()
        pointer = "$." + ".".join(SCHEMA_POINTER)
        self.assertIsNotNone(
            enum,
            f"{SCHEMA_PATH.name} has no list at {pointer}; the analyst's "
            "origin subtype is no longer a bounded vocabulary, so nothing "
            "constrains what the chief forwards to inbound-text-intake",
        )
        assert enum is not None  # narrowed by assertIsNotNone above
        self.assertNotEqual([], enum, f"{pointer} in {SCHEMA_PATH.name} is empty")
        self.assertEqual(
            sorted(set(enum)), sorted(enum),
            f"{pointer} in {SCHEMA_PATH.name} lists a duplicate: {enum}",
        )

    def test_the_schema_enum_and_the_runner_guard_are_the_same_vocabulary(self) -> None:
        enum = _schema_enum()
        self.assertIsNotNone(
            enum,
            f"{SCHEMA_PATH.name} no longer has a list at "
            f"$.{'.'.join(SCHEMA_POINTER)}",
        )
        assert enum is not None  # narrowed by assertIsNotNone above
        schema_side = set(enum)
        runner_side = set(self.guard_members())
        self.assertEqual(
            schema_side, runner_side,
            "the inbound origin subtype vocabulary has drifted.\n"
            f"  {SCHEMA_PATH.relative_to(ROOT)} "
            f"({'.'.join(SCHEMA_POINTER)}): {sorted(schema_side)}\n"
            f"  {VCRUN_PATH.relative_to(ROOT)} "
            f"({GUARD_SUBJECT}[{GUARD_KEY!r}] guard): {sorted(runner_side)}\n"
            f"  schema-only (analyst may emit, runner rejects): "
            f"{sorted(schema_side - runner_side)}\n"
            f"  runner-only (runner accepts, analyst output invalid): "
            f"{sorted(runner_side - schema_side)}",
        )


if __name__ == "__main__":
    unittest.main()
