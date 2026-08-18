# SPDX-License-Identifier: 0BSD
"""Config-driven third-party connector (MCP) injection — offline, no DB, no model.

Proves that render_channel_config.apply_connectors turns a config/connectors.json
into native mcp.servers + per-agent tool grants, keeps secrets as ${VAR}, and
fails closed on an unsafe grant. The live MCP connection is a deployment check.

`ConnectorGrantProseTests` closes the surrounding class: a grant is a runtime
capability, and the only thing that keeps a granted specialist from spending
against a paid connector on its own initiative is the prose of its own contract.
apply_connectors cannot check that, and it does not even validate the `grant_to`
of a **disabled** entry (it `continue`s first), so every claim the shipped
example and the connector register make about the grantable world was unbound.
Each check there enumerates its world from the file that defines it —
config/connectors.example.json for the grantees and their `${VAR}` secrets,
render_channel_config.CONNECTOR_GRANTABLE_AGENTS for the grantable set — rather
than restating a list this tree already knows.
"""

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))  # render imports check_env as a sibling
SPEC = importlib.util.spec_from_file_location("v3_render_connectors", ROOT / "scripts/render_channel_config.py")
assert SPEC is not None and SPEC.loader is not None, "render_channel_config.py is not loadable"
render: Any = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)

# Resolvable only after the sys.path insert above, and safe to import here
# because exec_module has already set sys.dont_write_bytecode (renderer line 21),
# so this cannot leave a scripts/__pycache__ behind for --pristine to report.
import check_env  # noqa: E402

EXAMPLE_CONNECTORS = ROOT / "config/connectors.example.json"
CONNECTOR_REGISTER = ROOT / "workspaces/vc-chief/vc/third_party_connectors.md"
COMPOSE = ROOT / "docker-compose.yml"
# The two services that run OpenClaw itself; the connector register promises the
# example secrets "pass through to the gateway and CLI containers".
SECRET_CARRIER_SERVICES = ("openclaw-gateway", "openclaw-cli")

# The clause every granted specialist's contract has to carry. Both spellings in
# the tree are accepted ("do not use a paid connector unless …" in the three
# example grantees' TOOLS.md, "no paid connector unless …" in outbound-scout's),
# but the meaning is pinned: a prohibition, lifted only by a valid scoped
# approval carried by the assignment. Prose that merely mentions connectors, or
# that conditions them on anything weaker, does not match.
PAID_CONNECTOR_CLAUSE = re.compile(
    r"(?:do not use|may not use|never use|no)\s+(?:a\s+)?paid connectors?\s+"
    r"unless the assignment (?:carries|contains) a valid scoped approval",
    re.IGNORECASE,
)
# Files that bind a specialist's behaviour. USER.md is operator preference and
# SOUL.md is character, so neither is a contract the runtime can be held to.
CONTRACT_FILES = ("TOOLS.md", "AGENTS.md")


def flatten(text: str) -> str:
    """Collapse whitespace so a clause wrapped across lines still matches."""
    return re.sub(r"\s+", " ", text)


def example_servers() -> dict[str, Any]:
    return json.loads(EXAMPLE_CONNECTORS.read_text(encoding="utf-8"))["mcp_servers"]


def example_grantees() -> set[str]:
    """Every agent the shipped example hands a connector to.

    Derived from the file, including its **disabled** entries: they ship
    disabled precisely so the operator enables one by flipping a flag, and the
    grant they name is what that flip activates.
    """
    return {
        agent
        for entry in example_servers().values()
        for agent in entry.get("grant_to", [])
    }


class ConnectorInjectionTests(unittest.TestCase):
    def setUp(self):
        self.saved = render.CONNECTORS_CONFIG
        self.tmp = Path(tempfile.mkstemp(suffix=".json")[1])

    def tearDown(self):
        render.CONNECTORS_CONFIG = self.saved
        self.tmp.unlink(missing_ok=True)

    def base(self):
        return render.load_strict_json(render.BASE_CONFIG)

    def write(self, definition):
        self.tmp.write_text(json.dumps(definition))
        render.CONNECTORS_CONFIG = self.tmp

    def test_absent_file_injects_nothing(self):
        render.CONNECTORS_CONFIG = Path("/nonexistent/connectors.json")
        config = self.base()
        self.assertEqual(render.apply_connectors(config), [])
        self.assertNotIn("mcp", config)

    def test_enabled_connector_injects_server_and_grants_tools(self):
        self.write({"mcp_servers": {"crunchbase": {
            "enabled": True, "grant_to": ["founder-researcher", "market-mapper"],
            "server": {"url": "https://x.invalid/mcp", "transport": "streamable-http",
                       "headers": {"Authorization": "Bearer ${CRUNCHBASE_API_KEY}"}},
        }}})
        config = self.base()
        self.assertEqual(render.apply_connectors(config), ["crunchbase"])
        self.assertIn("crunchbase", config["mcp"]["servers"])
        self.assertEqual(
            config["mcp"]["servers"]["crunchbase"]["headers"]["Authorization"],
            "Bearer ${CRUNCHBASE_API_KEY}",  # secret stays a reference, never inlined
        )
        agents = {a["id"]: a for a in config["agents"]["list"]}
        self.assertIn("crunchbase__*", agents["founder-researcher"]["tools"]["allow"])
        self.assertIn("crunchbase__*", agents["market-mapper"]["tools"]["allow"])
        self.assertNotIn("crunchbase__*", agents["data-steward"]["tools"].get("allow", []))

    def test_disabled_connector_is_skipped(self):
        self.write({"mcp_servers": {"c": {"enabled": False, "grant_to": ["market-mapper"],
                                          "server": {"url": "https://x.invalid"}}}})
        config = self.base()
        self.assertEqual(render.apply_connectors(config), [])
        self.assertNotIn("mcp", config)

    def test_grant_to_non_research_agent_is_refused(self):
        self.write({"mcp_servers": {"c": {"grant_to": ["data-steward"],
                                          "server": {"url": "https://x.invalid"}}}})
        with self.assertRaises(ValueError):
            render.apply_connectors(self.base())

    def test_unsafe_server_name_is_refused(self):
        self.write({"mcp_servers": {"Bad Name": {"grant_to": ["market-mapper"],
                                                 "server": {"url": "https://x.invalid"}}}})
        with self.assertRaises(ValueError):
            render.apply_connectors(self.base())

    def test_example_file_is_valid_and_inert(self):
        # The shipped example must parse and, with all entries disabled, inject nothing.
        render.CONNECTORS_CONFIG = EXAMPLE_CONNECTORS
        config = self.base()
        self.assertEqual(render.apply_connectors(config), [])


class ConnectorGrantProseTests(unittest.TestCase):
    """The grantable world, enumerated from the files that define it."""

    def test_every_example_grantee_carries_the_scoped_approval_clause(self):
        """A granted specialist's own contract must condition paid use on approval.

        `tools.allow` decides what the specialist *can* call; nothing in the
        runtime decides what it *may* spend. That restraint lives only in the
        agent's contract, so an agent named in a `grant_to` without the clause
        would be handed a paid connector and told nothing about approval.
        """
        grantees = example_grantees()
        self.assertTrue(
            grantees,
            "config/connectors.example.json names no grant_to agent at all, so "
            "this check would enumerate an empty world",
        )
        for agent in sorted(grantees):
            with self.subTest(agent=agent):
                carriers = []
                for name in CONTRACT_FILES:
                    path = ROOT / "workspaces" / agent / name
                    self.assertTrue(
                        path.is_file(),
                        f"{agent}: workspaces/{agent}/{name} is missing, so the "
                        "connector prose of an agent the example grants to "
                        "cannot be checked",
                    )
                    if PAID_CONNECTOR_CLAUSE.search(flatten(path.read_text(encoding="utf-8"))):
                        carriers.append(name)
                self.assertTrue(
                    carriers,
                    f"{agent}: config/connectors.example.json grants it a "
                    f"connector, but neither workspaces/{agent}/TOOLS.md nor "
                    f"workspaces/{agent}/AGENTS.md forbids paid connector use "
                    "unless the assignment carries a valid scoped approval",
                )

    def test_example_grants_only_to_grantable_known_agents(self):
        """apply_connectors never validates the shipped example's grant_to.

        Every entry ships `enabled: false`, and the renderer `continue`s on that
        before it reaches the grantable/known-agent checks — so the example
        could name a steward, or a typo, and every existing test would still
        pass. Validate the file itself against both worlds.
        """
        grantees = example_grantees()
        ungrantable = sorted(grantees - render.CONNECTOR_GRANTABLE_AGENTS)
        self.assertEqual(
            ungrantable, [],
            "config/connectors.example.json grants a connector to an agent "
            "render_channel_config.CONNECTOR_GRANTABLE_AGENTS refuses, so "
            f"enabling that entry would fail the render: {ungrantable}",
        )
        base_agents = {
            agent["id"]
            for agent in render.load_strict_json(render.BASE_CONFIG)["agents"]["list"]
        }
        unknown = sorted(grantees - base_agents)
        self.assertEqual(
            unknown, [],
            "config/connectors.example.json grants a connector to an agent that "
            f"config/openclaw.json does not define: {unknown}",
        )

    def test_register_documents_exactly_the_grantable_agent_set(self):
        """third_party_connectors.md's "Grantable specialists only" is a closed set.

        It restates render_channel_config.CONNECTOR_GRANTABLE_AGENTS in prose.
        Nothing bound the two, so widening the constant would leave the operator
        reading a shorter list than the renderer accepts — and narrowing it
        would leave a documented specialist whose grant now fails to render.
        """
        tail = flatten(CONNECTOR_REGISTER.read_text(encoding="utf-8")).partition(
            "Grantable specialists"
        )[2]
        self.assertTrue(
            tail,
            "workspaces/vc-chief/vc/third_party_connectors.md no longer carries "
            "a 'Grantable specialists' list, so its prose and "
            "render_channel_config.CONNECTOR_GRANTABLE_AGENTS are unbound",
        )
        documented = set(re.findall(r"`([a-z][a-z0-9-]+)`", tail.partition(".")[0]))
        self.assertEqual(
            documented, render.CONNECTOR_GRANTABLE_AGENTS,
            "workspaces/vc-chief/vc/third_party_connectors.md and "
            "render_channel_config.CONNECTOR_GRANTABLE_AGENTS disagree about "
            "which specialists may hold a connector grant; only the document "
            f"names {sorted(documented - render.CONNECTOR_GRANTABLE_AGENTS)}, "
            f"only the code {sorted(render.CONNECTOR_GRANTABLE_AGENTS - documented)}",
        )

    def test_every_example_server_is_a_hosted_url(self):
        """The register states every shipped example is a hosted `url`.

        A stdio `command` entry cannot start in this deployment (read-only root,
        no npx cache) and the renderer copies the `server` block verbatim, so it
        renders PASS and fails only at `openclaw mcp doctor --probe`.
        """
        offenders = sorted(
            name
            for name, entry in example_servers().items()
            if "url" not in entry["server"] or "command" in entry["server"]
        )
        self.assertEqual(
            offenders, [],
            "workspaces/vc-chief/vc/third_party_connectors.md states every "
            "shipped example is a hosted `url`, but these entries are not — a "
            "stdio `command` server cannot start in the read-only gateway "
            f"container: {offenders}",
        )

    def test_every_example_secret_reaches_the_gateway_and_cli(self):
        """The example's `${VAR}` secrets must be accepted and passed through.

        The register calls them "pre-wired: set them in `.env` and they pass
        through to the gateway and CLI containers". That promise spans three
        files, and a fourth example connector with a new variable name would
        break it silently: check_env would reject the `.env` line, or compose
        would never hand the variable to the process that resolves it.
        """
        # Read the server blocks, not the file text: the `_comment` header
        # explains the convention with a literal `${VAR}` placeholder, which is
        # documentation rather than a variable anything has to pass through.
        secrets = set(
            re.findall(
                r"\$\{([A-Z][A-Z0-9_]*)\}",
                json.dumps([entry["server"] for entry in example_servers().values()]),
            )
        )
        self.assertTrue(
            secrets,
            "config/connectors.example.json references no ${VAR} secret, so "
            "this check would enumerate an empty world",
        )
        unaccepted = sorted(secrets - check_env.ALLOWED_KEYS)
        self.assertEqual(
            unaccepted, [],
            "check_env.ALLOWED_KEYS rejects these connector variables, so "
            f".env validation would fail on the shipped example: {unaccepted}",
        )
        services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
        for service in SECRET_CARRIER_SERVICES:
            environment = services[service]["environment"]
            missing = sorted(secrets - set(environment))
            self.assertEqual(
                missing, [],
                f"docker-compose.yml service {service} does not pass these "
                "connector variables through, so OpenClaw cannot resolve the "
                f"${{VAR}} reference at load: {missing}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
