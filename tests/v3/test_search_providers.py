# SPDX-License-Identifier: Apache-2.0
"""Config-driven web-search provider selection — offline, no DB, no model.

Proves the render wires any native provider (not only the original four): the
plugin is allowlisted, the provider is selected, and a keyed provider gets its
credential as a SecretRef. Activating a non-bundled provider's package is a
separate commissioning step (image rebuild + G6 gate).
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("v3_render_search", ROOT / "scripts/render_channel_config.py")
assert SPEC is not None and SPEC.loader is not None, "render_channel_config.py is not loadable"
render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)

import check_env  # noqa: E402

# All selectable search providers, treated as available so the wiring logic can
# be tested independently of what this particular image happens to bundle. A
# separate test proves that a genuinely non-bundled provider fails closed.
ALL_PROVIDERS = set(render.SEARCH_PACKAGES)


def base_env(search):
    return {
        "VC_MODEL_PROVIDER": "openai", "VC_PRIMARY_MODEL": "openai/gpt-5.6-sol",
        "VC_FAST_MODEL": "openai/gpt-5.6-sol", "VC_MODEL_REASONING": "true", "VC_MODEL_INPUT": "text",
        "VC_MODEL_CONTEXT_WINDOW": "272000", "VC_MODEL_MAX_TOKENS": "16384",
        "VC_MODEL_TIMEOUT_SECONDS": "300", "VC_WEB_SEARCH_PROVIDER": search,
        "VC_WEB_FETCH_PROVIDER": "default",
    }


class SearchProviderRenderTests(unittest.TestCase):
    def render_for(self, search):
        config = render.load_strict_json(render.BASE_CONFIG)
        # Treat every provider as bundled to exercise the wiring logic; bundling
        # is enforced separately (test_non_bundled_provider_fails_closed).
        with patch.object(render, "_bundled_search_providers", return_value=ALL_PROVIDERS):
            render.apply_runtime_selection(config, "none", base_env(search))
        return config

    def test_non_bundled_provider_fails_closed_with_guidance(self):
        # brave is not in runtime-packages/package.json, so selecting it renders a
        # plugins.load path the image does not contain. That must fail closed at
        # render with an actionable message, not silently produce a broken config.
        config = render.load_strict_json(render.BASE_CONFIG)
        with self.assertRaises(ValueError) as ctx:
            render.apply_runtime_selection(config, "none", base_env("brave"))
        self.assertIn("no plugin in this image", str(ctx.exception))
        self.assertIn("runtime-packages", str(ctx.exception))

    def test_bundled_providers_render_without_simulation(self):
        # The three genuinely-bundled providers need no simulation.
        for provider in ("auto", "duckduckgo", "firecrawl", "tavily"):
            with self.subTest(provider=provider):
                config = render.load_strict_json(render.BASE_CONFIG)
                render.apply_runtime_selection(config, "none", base_env(provider))

    def test_brave_is_wired_with_credential_ref(self):
        config = self.render_for("brave")
        self.assertEqual(config["tools"]["web"]["search"]["provider"], "brave")
        self.assertIn("brave", config["plugins"]["allow"])
        self.assertEqual(
            config["plugins"]["entries"]["brave"]["config"]["webSearch"]["apiKey"],
            {"source": "env", "provider": "default", "id": "BRAVE_API_KEY"},
        )

    def test_exa_and_perplexity_are_selectable(self):
        for provider, key in (("exa", "EXA_API_KEY"), ("perplexity", "PERPLEXITY_API_KEY")):
            config = self.render_for(provider)
            self.assertEqual(config["tools"]["web"]["search"]["provider"], provider)
            self.assertIn(provider, config["plugins"]["allow"])
            self.assertEqual(
                config["plugins"]["entries"][provider]["config"]["webSearch"]["apiKey"]["id"], key,
            )

    def test_keyless_provider_needs_no_credential_entry(self):
        # parallel-free is the keyless variant of the parallel plugin: the
        # selectable provider id is "parallel-free" but the plugin package id
        # (plugins.allow / entries key) is "parallel". It renders with no config.
        config = self.render_for("parallel-free")
        self.assertEqual(config["tools"]["web"]["search"]["provider"], "parallel-free")
        self.assertIn("parallel", config["plugins"]["allow"])
        self.assertNotIn("config", config["plugins"]["entries"].get("parallel", {}))

    def test_every_selectable_provider_passes_the_full_render_assertion(self):
        # Regression: assert_effective_config once required the literal env
        # provider id in plugins.allow, which can never hold for parallel-free
        # (plugin id "parallel"), so bootstrap/update/restore hard-failed on a
        # documented option. Run the complete pipeline for every selectable id.
        for search in ("auto", *sorted(render.SEARCH_PACKAGES)):
            with self.subTest(search=search):
                env = base_env(search)
                config = render.load_strict_json(render.BASE_CONFIG)
                with patch.object(render, "_bundled_search_providers", return_value=ALL_PROVIDERS):
                    render.apply_runtime_selection(config, "none", env)
                render.assert_effective_config(config, "none", env)

    def test_searxng_is_wired_with_base_url_ref(self):
        # searxng is keyed by its instance endpoint, not an API key: the render
        # must inject baseUrl as a SecretRef (its plugin schema accepts an object
        # there), otherwise the provider renders with no endpoint and breaks.
        config = self.render_for("searxng")
        self.assertEqual(config["tools"]["web"]["search"]["provider"], "searxng")
        self.assertIn("searxng", config["plugins"]["allow"])
        web = config["plugins"]["entries"]["searxng"]["config"]["webSearch"]
        self.assertEqual(web["baseUrl"], {"source": "env", "provider": "default", "id": "SEARXNG_BASE_URL"})
        self.assertNotIn("apiKey", web)

    def test_env_validator_accepts_new_provider_with_its_key(self):
        # Assert against the shipped validator itself, never a local copy of
        # its logic: a re-implementation stays green when check_env regresses.
        # The assertions target exact search-block error strings, so unrelated
        # validation errors from the padded values cannot flip them.
        base = dict.fromkeys(check_env.REQUIRED, "x")
        base.update({
            "VC_MODEL_PROVIDER": "openai", "OPENAI_API_KEY": "sk-x",
            "VC_WEB_SEARCH_PROVIDER": "brave", "BRAVE_API_KEY": "brv-x",
            "VC_WEB_FETCH_PROVIDER": "default", "VC_CHANNEL_MEDIA_MAX_MB": "25",
            "VC_PRIMARY_MODEL": "openai/gpt-5.6-sol", "VC_FAST_MODEL": "openai/gpt-5.6-sol",
        })
        with_key = check_env.validate_runtime_selection(base)
        self.assertNotIn(
            "VC_WEB_SEARCH_PROVIDER must be one of auto, duckduckgo, firecrawl, tavily, "
            "brave, perplexity, exa, searxng, parallel-free",
            with_key,
        )
        self.assertNotIn(
            "BRAVE_API_KEY must be set exactly when the brave search provider is selected",
            with_key,
        )
        # brave selected without its key must error
        no_key = dict(base)
        no_key["BRAVE_API_KEY"] = ""
        self.assertIn(
            "BRAVE_API_KEY must be set exactly when the brave search provider is selected",
            check_env.validate_runtime_selection(no_key),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
