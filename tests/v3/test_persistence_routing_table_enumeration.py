# SPDX-License-Identifier: 0BSD
"""Every persistence operation a specialist can request must have a named row.

A specialist hands the data-persistence steward a `persistenceRequest` whose
`operation` comes from an `enum` in that specialist's own output schema. The
steward's routing table in `workspaces/shared-skills/data-persistence/SKILL.md`
maps those operations to lanes, and it ends with an `anything else` catch-all
that classifies the request `operator_only` and refuses it.

That catch-all is what makes drift silent: add an operation to a specialist
schema and forget the table, and the steward does not fail — it quietly refuses
a request the package intended to route. This suite enumerates the world from
the schemas: for every `workspaces/schemas/*.output.schema.json` that defines
`$defs.persistenceRequest.properties.operation.enum`, each member other than
`none` must be named, in backticks, somewhere in the routing-table section.

`none` is excluded because it means "no persistence requested" — there is
nothing to route. The backticks are load-bearing: `capture_candidate` is a
prefix of `capture_candidates`, so a bare substring test would let the plural
row satisfy the singular operation.

This checks that each operation is *mentioned* in the table. It does not judge
whether the lane the row assigns is the right one.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "workspaces/schemas"
SKILL = ROOT / "workspaces/shared-skills/data-persistence/SKILL.md"

# The section whose rows are the routing table, and the operation that means
# "nothing to route".
SECTION_HEADING = "## Routing a specialist `persistence_request`"
NO_OPERATION = "none"


def _routing_section() -> str | None:
    """The SKILL.md text from SECTION_HEADING up to the next `## ` heading."""
    body = SKILL.read_text(encoding="utf-8")
    start = body.find(SECTION_HEADING)
    if start < 0:
        return None
    rest = body[start + len(SECTION_HEADING):]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def _requestable_operations() -> dict[str, set[str]]:
    """Operation enum per specialist schema that declares a persistenceRequest."""
    found: dict[str, set[str]] = {}
    for path in sorted(SCHEMA_DIR.glob("*.output.schema.json")):
        document: Any = json.loads(path.read_text(encoding="utf-8"))
        node: Any = document
        for segment in ("$defs", "persistenceRequest", "properties", "operation", "enum"):
            if not isinstance(node, dict) or segment not in node:
                node = None
                break
            node = node[segment]
        if isinstance(node, list):
            found[path.name] = {member for member in node if isinstance(member, str)}
    return found


class PersistenceRoutingTableEnumerationTests(unittest.TestCase):
    def test_the_routing_section_heading_is_still_there(self) -> None:
        self.assertIsNotNone(
            _routing_section(),
            f"{SKILL.relative_to(ROOT)} no longer contains the heading "
            f"{SECTION_HEADING!r}, so this suite cannot locate the routing "
            "table. Update SECTION_HEADING to the new wording.",
        )

    def test_specialist_schemas_still_declare_persistence_operations(self) -> None:
        # Without this, a rename under $defs would empty the enumerated world
        # and make the coverage assertion below pass vacuously.
        schemas = _requestable_operations()
        self.assertNotEqual(
            {}, schemas,
            f"no schema in {SCHEMA_DIR.relative_to(ROOT)} defines "
            "$defs.persistenceRequest.properties.operation.enum any more; the "
            "coverage check below would enumerate nothing",
        )

    def test_every_requestable_operation_is_named_in_the_routing_table(self) -> None:
        section = _routing_section()
        self.assertIsNotNone(section, f"{SKILL.name} lost its routing-table heading")
        assert section is not None  # narrowed by assertIsNotNone above

        sources: dict[str, list[str]] = {}
        for schema_name, operations in _requestable_operations().items():
            for operation in operations:
                if operation != NO_OPERATION:
                    sources.setdefault(operation, []).append(schema_name)

        missing = sorted(
            operation for operation in sources if f"`{operation}`" not in section
        )
        self.assertEqual(
            [], missing,
            "specialist output schemas can request persistence operations that "
            f"the routing table in {SKILL.relative_to(ROOT)} never names, so "
            "the steward would fall through to its `anything else` row and "
            "refuse them as operator_only:\n"
            + "\n".join(
                f"  `{operation}` — requested by {', '.join(sorted(sources[operation]))}"
                for operation in missing
            ),
        )


if __name__ == "__main__":
    unittest.main()
