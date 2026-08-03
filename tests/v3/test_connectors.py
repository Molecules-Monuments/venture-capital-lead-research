# SPDX-License-Identifier: 0BSD
"""Config-driven third-party connector (MCP) injection — offline, no DB, no model.

Proves that render_channel_config.apply_connectors turns a config/connectors.json
into native mcp.servers + per-agent tool grants, keeps secrets as ${VAR}, and
fails closed on an unsafe grant. The live MCP connection is a deployment check.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))  # render imports check_env as a sibling
SPEC = importlib.util.spec_from_file_location("v3_render_connectors", ROOT / "scripts/render_channel_config.py")
assert SPEC is not None and SPEC.loader is not None, "render_channel_config.py is not loadable"
render: Any = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)


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
        render.CONNECTORS_CONFIG = ROOT / "config/connectors.example.json"
        config = self.base()
        self.assertEqual(render.apply_connectors(config), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
