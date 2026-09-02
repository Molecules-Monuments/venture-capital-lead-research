# G6 channel gate

The Version 3 offline channel contract covers all four disabled-by-default
templates, positive and negative profile rendering, plugin provenance and
deployment wiring, the governed document-media boundary, configurable
model/search providers, and exact OpenClaw schema
validation inside the built image. Version 3 intentionally denies `memory-core`
a role — it is absent from `plugins.allow` and memory search is pinned off —
though the harness still loads it into its own default memory slot, which
`README.md` documents. This gate tests that deliberate Version 3 contract
directly.

Run from the Version 3.0 root:

```sh
python3 -B -m unittest discover -s tests/v3 -p 'test_*.py' -v
python3 -B -m unittest discover -s tests/infrastructure -p 'test_*.py' -v
python3 -B -m unittest discover -s tests/g6 -p 'test*.py' -v
python3 -B scripts/run_g6_image.py --image <built-image>
```

`run_g6_image.py` validates inert, Slack, Teams, Discord, and Telegram renders
with OpenClaw's own `config validate` command in network-disabled, read-only,
capability-dropped containers. It also verifies the locked Lobster/channel
package inventory, DuckDuckGo, Firecrawl, Tavily, Ollama, the trusted-context
extension, exact direct Debian versions, and rejection of an unknown field.
This proves the G6 image/configuration boundary; it does not contact a provider
or convert deployment commissioning into a package test.
