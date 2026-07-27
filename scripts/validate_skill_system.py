#!/usr/bin/env python3
"""Fail-closed production validator for Version 3 skills, agents, tools, and routes."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


PACKAGE = Path(__file__).resolve().parent.parent
CONFIG_PATH = PACKAGE / "config/openclaw.json"
SKILLS_ROOT = PACKAGE / "workspaces/shared-skills"
WORKSPACES_ROOT = PACKAGE / "workspaces"
RESOLVER_PATH = PACKAGE / "workspaces/vc-chief/vc/RESOLVER.md"
HOOK_PATH = PACKAGE / "runtime-extensions/vc-trusted-context/index.js"
VCRUN_PATH = PACKAGE / "workspaces/vc-chief/vc/bin/vcrun.py"

EXPECTED_AGENTS = {
    "data-steward",
    "document-intake-analyst",
    "founder-researcher",
    "inbound-intake-analyst",
    "lead-router",
    "lead-signal-detector",
    "market-mapper",
    "memo-writer",
    "outbound-scout",
    "qualification-analyst",
    "traction-analyst",
    "vc-chief",
}
EXPECTED_SKILLS = {
    "approval-gates",
    "compiled-truth",
    "contradiction-check",
    "controlled-evolution",
    "data-persistence",
    "document-extraction",
    "eval-fixture-check",
    "evidence-research",
    "evidence-scoring",
    "governance-lint",
    "inbound-intake",
    "knowledge-modeling",
    "lead-memory-lookup",
    "lead-routing",
    "lead-signal-detection",
    "memo-writing",
    "outbound-sourcing",
    "quiet-hours-reporting",
    "research-depth-control",
    "resolver-check",
    "schema-proposal",
    "skillify",
    "source-improvement",
    "system-health-check",
    "trajectory-check",
    "trust-boundary",
}
EXPECTED_WORKFLOW_STEPS = {
    "contradiction-record": [
        "preflight", "workflow_start", "workflow_running", "contradiction_check",
        "workflow_succeeded",
    ],
    "document-ingest": [
        "preflight", "document_preview", "document_request", "workflow_start",
        "workflow_running", "document_extract", "workflow_succeeded",
    ],
    "evidence-record": [
        "preflight", "workflow_start", "workflow_running", "evidence_persist",
        "fact_promote", "workflow_succeeded",
    ],
    "document-lead-intake": [
        "preflight", "workflow_request_claim", "company_resolve_create", "create_lead",
        "workflow_start", "workflow_running", "document_associate", "workflow_succeeded",
    ],
    "evaluate-lead": [
        "preflight", "lead_show", "workflow_start", "workflow_running", "prequalify",
        "persist_approval", "compiled_truth", "evaluation_save", "workflow_succeeded",
    ],
    "inbound-intake": [
        "preflight", "document_preview", "workflow_request_claim", "company_resolve_create",
        "create_lead", "workflow_start", "workflow_running", "document_extract",
        "workflow_succeeded",
    ],
    "inbound-text-intake": [
        "preflight", "workflow_request_claim", "company_resolve_create", "create_lead",
        "workflow_start", "workflow_running", "workflow_succeeded",
    ],
    "memo-record": [
        "preflight", "workflow_start", "workflow_running", "memo_persist",
        "workflow_succeeded",
    ],
    "orchestration-record": [
        "preflight", "workflow_start", "workflow_running", "orchestration_record",
        "workflow_succeeded",
    ],
    "proposal-record": [
        "preflight", "workflow_start", "workflow_running", "proposal_record",
        "workflow_succeeded",
    ],
    "outbound-scout": [
        "preflight", "workflow_request_claim", "company_resolve_create", "create_lead",
        "workflow_start", "workflow_running", "workflow_succeeded",
    ],
    "preference-forget": [
        "preflight", "workflow_start", "workflow_running", "preference_forget",
        "workflow_succeeded",
    ],
    "preference-observe": [
        "preflight", "workflow_start", "workflow_running", "preference_observe",
        "workflow_succeeded",
    ],
    "runtime-preflight": [
        "preflight", "workflow_start", "workflow_running", "runtime_preflight",
        "workflow_succeeded",
    ],
    "source-scan": [
        "preflight", "workflow_start", "workflow_running", "source_scan",
        "workflow_succeeded",
    ],
    "source-unwatch": [
        "preflight", "workflow_start", "workflow_running", "source_unwatch",
        "workflow_succeeded",
    ],
    "source-watch": [
        "preflight", "workflow_start", "workflow_running", "source_watch",
        "workflow_succeeded",
    ],
    "trajectory-record": [
        "preflight", "workflow_start", "workflow_running", "trajectory_check",
        "workflow_succeeded",
    ],
}


class DuplicateKeyError(ValueError):
    pass


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader: UniqueSafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise DuplicateKeyError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str


def relative(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


def add(findings: list[Finding], code: str, path: Path | str, message: str) -> None:
    findings.append(Finding(code, relative(path) if isinstance(path, Path) else path, message))


def load_config(findings: list[Finding]) -> dict[str, Any]:
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, json.JSONDecodeError, DuplicateKeyError) as exc:
        add(findings, "config_parse", CONFIG_PATH, str(exc))
        return {}
    if not isinstance(value, dict):
        add(findings, "config_shape", CONFIG_PATH, "root must be an object")
        return {}
    return value


def parse_skill(path: Path, findings: list[Finding]) -> tuple[str | None, str]:
    try:
        body = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        add(findings, "skill_read", path, str(exc))
        return None, ""
    match = re.match(r"^---\n(.*?)\n---\n", body, re.DOTALL)
    if not match:
        add(findings, "skill_frontmatter", path, "missing exact YAML frontmatter")
        return None, body
    try:
        metadata = yaml.load(match.group(1), Loader=UniqueSafeLoader)
    except (yaml.YAMLError, DuplicateKeyError) as exc:
        add(findings, "skill_frontmatter", path, str(exc))
        return None, body
    if not isinstance(metadata, dict) or set(metadata) != {"name", "description"}:
        add(findings, "skill_metadata", path, "frontmatter must contain only name and description")
        return None, body
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        add(findings, "skill_name", path, "name must be lowercase hyphen-case and at most 64 characters")
        name = None
    if not isinstance(description, str) or not description.strip() or len(description.encode("utf-8")) > 160:
        add(findings, "skill_description", path, "description must be non-empty and at most 160 UTF-8 bytes")
    if name is not None and path.parent.name != name:
        add(findings, "skill_directory", path, "directory and frontmatter name differ")
    headings = set(re.findall(r"(?m)^## (.+?)\s*$", body))
    for required in ("Inputs", "Contract", "Evidence and failures"):
        if required not in headings:
            add(findings, "skill_section", path, f"missing production section: {required}")
    if not any(item == "Output" or item.startswith("Output ") for item in headings):
        add(findings, "skill_section", path, "missing Output or Output boundary section")
    if not re.search(r"\b(?:forbidden|never|must not|fail closed|block)\b", body, re.IGNORECASE):
        add(findings, "skill_boundary", path, "no explicit failure/prohibition boundary")
    for schema_name in re.findall(r"/workspaces/schemas/([A-Za-z0-9_.-]+)", body):
        schema = PACKAGE / "workspaces/schemas" / schema_name
        if not schema.is_file():
            add(findings, "skill_schema", path, f"schema reference does not exist: {schema_name}")
    for stale in ("V2 caps", "four parameterized fixed", "25 discovered skills"):
        if stale in body:
            add(findings, "skill_stale", path, f"stale release text: {stale}")
    return name, body


def documented_tools(path: Path, heading: str) -> set[str]:
    body = path.read_text(encoding="utf-8")
    section = body.split(f"## {heading}", 1)[1].split("## ", 1)[0]
    return set(re.findall(r"(?m)^- `([^`]+)`$", section))


def validate_skills_and_agents(config: dict[str, Any], findings: list[Finding]) -> None:
    skill_paths = sorted(SKILLS_ROOT.glob("*/SKILL.md"))
    skill_bodies: dict[str, str] = {}
    for path in skill_paths:
        name, body = parse_skill(path, findings)
        if name is not None:
            if name in skill_bodies:
                add(findings, "skill_duplicate", path, f"duplicate skill name: {name}")
            skill_bodies[name] = body
    actual_skills = set(skill_bodies)
    if actual_skills != EXPECTED_SKILLS:
        add(
            findings, "skill_inventory", SKILLS_ROOT,
            f"expected={sorted(EXPECTED_SKILLS)} actual={sorted(actual_skills)}",
        )

    agents = config.get("agents", {}).get("list", []) if config else []
    if not isinstance(agents, list) or not all(isinstance(item, dict) for item in agents):
        add(findings, "agent_config", CONFIG_PATH, "agents.list must be an object array")
        return
    agent_map = {item.get("id"): item for item in agents if isinstance(item.get("id"), str)}
    if set(agent_map) != EXPECTED_AGENTS or len(agent_map) != len(agents):
        add(findings, "agent_inventory", CONFIG_PATH, f"expected={sorted(EXPECTED_AGENTS)} actual={sorted(agent_map)}")

    entries = config.get("skills", {}).get("entries", {})
    if not isinstance(entries, dict) or set(entries) != actual_skills:
        add(findings, "skill_entries", CONFIG_PATH, "skills.entries must exactly match discovered skills")
    elif any(value != {"enabled": True} for value in entries.values()):
        add(findings, "skill_entries", CONFIG_PATH, "every packaged skill entry must be enabled explicitly")
    assigned = {skill for agent in agents for skill in agent.get("skills", []) if isinstance(skill, str)}
    if assigned != actual_skills:
        add(findings, "skill_assignment", CONFIG_PATH, "configured agent skill union must match discovered skills")

    for agent_id, agent in agent_map.items():
        agent_path = WORKSPACES_ROOT / agent_id / "AGENTS.md"
        tools_path = WORKSPACES_ROOT / agent_id / "TOOLS.md"
        if not agent_path.is_file() or not tools_path.is_file():
            add(findings, "agent_files", WORKSPACES_ROOT / agent_id, "AGENTS.md and TOOLS.md are required")
            continue
        body = agent_path.read_text(encoding="utf-8")
        headings = set(re.findall(r"(?m)^## (.+?)\s*$", body))
        for required in ("Inputs", "Evidence and trust"):
            if required not in headings:
                add(findings, "agent_section", agent_path, f"missing section: {required}")
        if not any(item.startswith("Output") for item in headings):
            add(findings, "agent_section", agent_path, "missing Output section")
        if not any("prohibition" in item.lower() for item in headings):
            add(findings, "agent_section", agent_path, "missing prohibitions section")
        if not re.search(r"\b(?:fail closed|forbidden|never|must not|do not)\b", body, re.IGNORECASE):
            add(findings, "agent_boundary", agent_path, "no explicit fail-closed/prohibition rule")
        try:
            allowed = documented_tools(tools_path, "Allowed tool IDs")
            denied = documented_tools(tools_path, "Denied tool IDs")
        except (OSError, IndexError, UnicodeError) as exc:
            add(findings, "tool_document", tools_path, str(exc))
            continue
        configured_tools = agent.get("tools", {})
        if allowed != set(configured_tools.get("allow", [])):
            add(findings, "tool_allow_drift", tools_path, "documented allowlist differs from config")
        if denied != set(configured_tools.get("deny", [])):
            add(findings, "tool_deny_drift", tools_path, "documented denylist differs from config")

    chief = agent_map.get("vc-chief", {})
    if "skill_workshop" not in chief.get("tools", {}).get("allow", []):
        add(findings, "workshop_authority", CONFIG_PATH, "vc-chief must receive the guarded Skill Workshop tool")
    if "skill_workshop" not in config.get("tools", {}).get("alsoAllow", []):
        add(findings, "workshop_authority", CONFIG_PATH, "the coding profile must retain Skill Workshop before exact agent filtering")
    for agent_id, agent in agent_map.items():
        if agent_id == "vc-chief":
            continue
        tools = agent.get("tools", {})
        if "skill_workshop" in tools.get("allow", []) or "skill_workshop" not in tools.get("deny", []):
            add(findings, "workshop_authority", CONFIG_PATH, f"{agent_id} must explicitly deny Skill Workshop")
    if "skill_workshop" in config.get("tools", {}).get("deny", []):
        add(findings, "workshop_authority", CONFIG_PATH, "global deny would shadow the chief's exact allow")
    if "skill_workshop" not in config.get("tools", {}).get("subagents", {}).get("tools", {}).get("deny", []):
        add(findings, "workshop_authority", CONFIG_PATH, "subagent defaults must deny Skill Workshop")
    workshop = config.get("skills", {}).get("workshop", {})
    if workshop.get("autonomous") != {"enabled": False} or workshop.get("approvalPolicy") != "pending":
        add(findings, "workshop_config", CONFIG_PATH, "autonomous review must be disabled and approval policy pending")
    if workshop.get("allowSymlinkTargetWrites") is not False or workshop.get("maxPending") != 10 or workshop.get("maxSkillBytes") != 40000:
        add(findings, "workshop_config", CONFIG_PATH, "reviewed Workshop bounds changed")

    skillify = skill_bodies.get("skillify", "")
    for marker in (
        "action=create", "action=inspect", "action=revise", "pending_operator_release",
        "scripts/validate_skill_system.py", "official `skill-creator` validator",
        "router/configuration/agent/schema/test/documentation",
    ):
        if marker not in skillify:
            add(findings, "skillify_contract", SKILLS_ROOT / "skillify/SKILL.md", f"missing marker: {marker}")
    evolution = skill_bodies.get("controlled-evolution", "")
    if "delegation to `skillify`" not in evolution or "never activates" not in evolution:
        add(findings, "evolution_contract", SKILLS_ROOT / "controlled-evolution/SKILL.md", "pending-only skill path is incomplete")


def validate_router_and_hook(findings: list[Finding]) -> None:
    resolver = RESOLVER_PATH.read_text(encoding="utf-8")
    if "discovers 26 shared skills" not in resolver:
        add(findings, "resolver_inventory", RESOLVER_PATH, "resolver must declare the exact discovered inventory")
    for skill in EXPECTED_SKILLS:
        if f"`{skill}`" not in resolver:
            add(findings, "resolver_skill", RESOLVER_PATH, f"skill absent from resolver: {skill}")
    for marker in (
        "Explicit request for a reusable skill", "complete pending Workshop artifact",
        "operator repository release", "pending Workshop packaging only through `skillify`",
    ):
        if marker not in resolver:
            add(findings, "resolver_skillify", RESOLVER_PATH, f"missing guarded skill route marker: {marker}")

    hook = HOOK_PATH.read_text(encoding="utf-8")
    for marker in (
        'api.on("before_tool_call", guardSkillWorkshop)',
        'event?.toolName !== "skill_workshop"',
        'ctx?.agentId !== "vc-chief"',
        'new Set(["create", "update", "revise", "list", "inspect"])',
        "operator-controlled repository release",
    ):
        if marker not in hook:
            add(findings, "workshop_hook", HOOK_PATH, f"missing fail-closed guard marker: {marker}")


def validate_resolver_routing(config: dict[str, Any], workflows: dict[str, Any], findings: list[Finding]) -> None:
    """Real routing validation: every route must map to things that exist and are usable.

    Replaces the prior string-presence 'resolver-check' that could not catch a
    dead route (e.g. an origin with no lead-creation workflow, or a router enum
    that drifted from the skill inventory).
    """
    resolver = RESOLVER_PATH.read_text(encoding="utf-8")

    # 1. lead-router output enums must exactly match the effective inventory, so
    #    the router can never emit a skill/agent the system does not have.
    router_schema_path = PACKAGE / "workspaces/schemas/lead-router.output.schema.json"
    try:
        router_schema = json.loads(router_schema_path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        defs = router_schema.get("$defs", {})
        skill_enum = set(defs.get("skill", {}).get("enum", []))
        agent_enum = set(defs.get("agent", {}).get("enum", []))
        if skill_enum != EXPECTED_SKILLS:
            add(findings, "router_skill_enum", router_schema_path,
                f"lead-router skill enum drifts from inventory: missing={sorted(EXPECTED_SKILLS - skill_enum)} "
                f"extra={sorted(skill_enum - EXPECTED_SKILLS)}")
        # The router routes only to routable specialists: never to the
        # orchestrator vc-chief (its parent/spawner) or to itself (lead-router).
        # The enum must be exactly that subset, so this check also catches a
        # regression that re-adds either non-routable agent.
        routable_agents = EXPECTED_AGENTS - {"vc-chief", "lead-router"}
        if agent_enum != routable_agents:
            add(findings, "router_agent_enum", router_schema_path,
                f"lead-router agent enum drifts from the routable roster: missing={sorted(routable_agents - agent_enum)} "
                f"extra={sorted(agent_enum - routable_agents)}")
    except (OSError, ValueError, DuplicateKeyError) as exc:
        add(findings, "router_schema", router_schema_path, f"{type(exc).__name__}: {exc}")

    # 2. The lead-entry workflow selectors the resolver routes to must each be a
    #    real vcrun selector AND be named in RESOLVER.md. (The prior token-scan
    #    here was circular: it derived "is this token a workflow?" from the same
    #    selector set it then compared against, so the drift branch could never
    #    fire. These are the concrete entry points a route hands off to; a rename
    #    or removal of any one is exactly a dead route.)
    for selector in ("document-lead-intake", "inbound-text-intake", "outbound-scout"):
        if selector not in workflows:
            add(findings, "resolver_workflow", RESOLVER_PATH,
                f"resolver routes to lead-entry workflow `{selector}` but it is not a vcrun selector")
        elif f"`{selector}`" not in resolver:
            add(findings, "resolver_workflow", RESOLVER_PATH,
                f"lead-entry workflow `{selector}` is a vcrun selector but RESOLVER.md never routes to it")

    # 3. Lead-creation origin coverage: every origin_group a route implies must
    #    have at least one fixed workflow that creates a lead with it. This is a
    #    coarse gate on the origin_group axis (inbound/outbound); the finer
    #    text-inbound entry itself is covered by the inbound-text-intake selector
    #    check in part 2 above.
    workflow_root = PACKAGE / "workspaces/vc-chief/vc/workflows"
    created_origins: set[str] = set()
    for path in workflow_root.glob("*.lobster"):
        for match in re.finditer(r"--origin-group\s+(\S+)", path.read_text(encoding="utf-8")):
            created_origins.add(match.group(1).strip())
    for required in ("inbound", "outbound"):
        if required not in created_origins:
            add(findings, "resolver_origin_coverage", workflow_root,
                f"no fixed workflow creates a lead with origin_group={required}; a resolver route to it is a dead end")

    # 4. Every specialist RESOLVER routes work to must exist and hold the skill
    #    it is routed through (a route to a skill the agent cannot use is dead).
    agent_skills = {
        agent.get("id"): set(agent.get("skills", []))
        for agent in (config.get("agents", {}).get("list", []) if config else [])
        if isinstance(agent, dict)
    }
    for skill, agent in (
        ("evidence-research", "founder-researcher"),
        ("evidence-research", "market-mapper"),
        ("evidence-scoring", "qualification-analyst"),
        ("memo-writing", "memo-writer"),
        ("outbound-sourcing", "outbound-scout"),
        ("lead-routing", "lead-router"),
        ("document-extraction", "document-intake-analyst"),
    ):
        if skill not in agent_skills.get(agent, set()):
            add(findings, "resolver_route_grant", CONFIG_PATH,
                f"resolver routes `{skill}` to `{agent}` but that agent is not granted the skill")


def load_vcrun(findings: list[Finding]) -> dict[str, Any]:
    try:
        spec = importlib.util.spec_from_file_location("v3_skill_system_vcrun", VCRUN_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot construct module specification")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.WORKFLOWS
    except Exception as exc:  # bounded validator error
        add(findings, "vcrun_import", VCRUN_PATH, f"{type(exc).__name__}: {exc}")
        return {}


def validate_workflows(findings: list[Finding]) -> None:
    workflow_root = PACKAGE / "workspaces/vc-chief/vc/workflows"
    actual = {path.stem: path for path in workflow_root.glob("*.lobster")}
    if set(actual) != set(EXPECTED_WORKFLOW_STEPS):
        add(findings, "workflow_inventory", workflow_root, f"expected={sorted(EXPECTED_WORKFLOW_STEPS)} actual={sorted(actual)}")
    contracts = load_vcrun(findings)
    if set(contracts) != set(EXPECTED_WORKFLOW_STEPS):
        add(findings, "workflow_selector", VCRUN_PATH, "vcrun selectors differ from the fixed workflow inventory")
    for workflow, expected_steps in EXPECTED_WORKFLOW_STEPS.items():
        path = actual.get(workflow)
        if path is None:
            continue
        try:
            body = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueSafeLoader)
        except (OSError, UnicodeError, yaml.YAMLError, DuplicateKeyError) as exc:
            add(findings, "workflow_parse", path, str(exc))
            continue
        if not isinstance(body, dict):
            add(findings, "workflow_shape", path, "workflow root must be an object")
            continue
        if body.get("name") != f"vc-{workflow}-v3":
            add(findings, "workflow_name", path, "workflow name must be the exact Version 3 name")
        steps = body.get("steps", [])
        actual_steps = [item.get("id") for item in steps if isinstance(item, dict)]
        if actual_steps != expected_steps:
            add(findings, "workflow_steps", path, f"expected={expected_steps} actual={actual_steps}")
        if expected_steps[-1] != "workflow_succeeded":
            add(findings, "workflow_terminal", path, "workflow inventory lacks a terminal success step")
        contract = contracts.get(workflow, {})
        contract_args = set(contract.get("keys", set())) | set(contract.get("optional_keys", set()))
        if isinstance(body.get("args"), dict) and set(body["args"]) != contract_args:
            add(findings, "workflow_args", path, "workflow args differ from vcrun's exact contract")

    process = subprocess.run(
        [sys.executable, "-B", str(PACKAGE / "scripts/validate_workflows.py")],
        cwd=PACKAGE,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        add(findings, "workflow_static", PACKAGE / "scripts/validate_workflows.py", (process.stdout + process.stderr)[-4000:])


def main() -> int:
    findings: list[Finding] = []
    config = load_config(findings)
    validate_skills_and_agents(config, findings)
    validate_router_and_hook(findings)
    validate_workflows(findings)
    validate_resolver_routing(config, load_vcrun(findings), findings)
    report = {
        "result": "PASS" if not findings else "FAIL",
        "skills": len(list(SKILLS_ROOT.glob("*/SKILL.md"))),
        "agents": len(list(WORKSPACES_ROOT.glob("*/AGENTS.md"))),
        "workflows": len(list((PACKAGE / "workspaces/vc-chief/vc/workflows").glob("*.lobster"))),
        "findings": [asdict(item) for item in findings],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
