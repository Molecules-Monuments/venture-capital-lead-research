#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Fail-closed static validator for the fixed Version 3 Lobster workflows.

The validator treats workflow YAML and command text as untrusted. Command and
option inventories are derived from vcops.build_parser(), so CLI/workflow drift
is a release failure. It never executes a workflow or opens the database.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml


PACKAGE = Path(__file__).resolve().parent.parent
WORKFLOWS = PACKAGE / "workspaces/vc-chief/vc/workflows"
VCOPS = PACKAGE / "workspaces/vc-chief/vc/bin/vcops.py"
WRAPPERS = {
    "/workspaces/vc-chief/vc/bin/agent/vcops",
    "/workspaces/vc-chief/vc/bin/vcops-workflow",
}
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
STEP_REF_RE = re.compile(r"\$([A-Za-z0-9_-]+)\.([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)")
SAFE_STEP_PATHS = {
    "approved",
    "json.evaluation",
    "json.sha256",
    "json.document.sha256",
    "json.verified_context.account_id",
    "json.verified_context.event_id",
    "json.verified_context.provider",
    "json.verified_context.sender_id",
    "json.company.id",
    "json.fact.id",
    "json.lead.id",
    "json.snapshot.id",
    "json.snapshot.evidence_packet_hash",
    "json.workflow_request.id",
    "json.workflow_run.id",
    "json.workflow_run.run_id",
    "json.workflow_run.record_version",
}
SHELL_BUILTINS = {"env", "export", "printenv", "set", "source", "."}


class DuplicateKeyError(ValueError):
    pass


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader: UniqueSafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise DuplicateKeyError(f"duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _unique_mapping,
)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    step_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_vcops_parser() -> tuple[argparse.ArgumentParser | None, list[Finding]]:
    try:
        spec = importlib.util.spec_from_file_location("v3_workflow_vcops", VCOPS)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot construct vcops import spec")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        parser = module.build_parser()
        if not isinstance(parser, argparse.ArgumentParser):
            raise TypeError("build_parser did not return ArgumentParser")
        return parser, []
    except Exception as exc:  # fail closed with a bounded public error
        return None, [Finding("vcops_parser", f"cannot load reviewed vcops parser: {type(exc).__name__}: {exc}")]


def _command_parsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _substitute_bounded_references(command: str) -> str:
    command = STEP_REF_RE.sub("1", command)
    command = re.sub(r"\$(?:LOBSTER_ARG|VCOPS)_[A-Z][A-Z0-9_]*", "1", command)
    return command


def _validate_command(
    command: str,
    *,
    step_id: str,
    prior_ids: set[str],
    all_ids: set[str],
    command_parsers: dict[str, argparse.ArgumentParser],
) -> list[Finding]:
    findings: list[Finding] = []
    if "$(" in command or "`" in command:
        findings.append(Finding("command_substitution", "shell command substitution is forbidden", step_id))
    if re.search(r"\$\{[^}]+\}", command):
        findings.append(Finding("raw_env", "raw shell/template expansion is forbidden", step_id))
    if re.search(r"(?<![\"'])\$LOBSTER_ARG_[A-Z][A-Z0-9_]*", command):
        findings.append(Finding("arg_unquoted", "Lobster arguments must be double-quoted", step_id))
    if "openclaw.invoke" in command:
        findings.append(Finding("openclaw_invoke", "arbitrary OpenClaw tool invocation is forbidden", step_id))
    if re.search(r"(?:^|\s)--unsafe(?:-|\b)|(?:^|\s)--unsafe-ground(?:\s|$)", command):
        findings.append(Finding("unsafe_authority", "unsafe authority flags are forbidden", step_id))

    for referenced_step, path in STEP_REF_RE.findall(command):
        if not path.startswith("json.") and path != "approved":
            findings.append(Finding("step_ref_legacy", f"legacy step reference: {referenced_step}.{path}", step_id))
        elif referenced_step not in prior_ids:
            code = "step_ref_order" if referenced_step in all_ids else "step_ref_unknown"
            findings.append(Finding(code, f"step reference is not a completed predecessor: {referenced_step}", step_id))
        if path not in SAFE_STEP_PATHS:
            findings.append(Finding("step_ref_unbounded", f"unreviewed step-output path: {path}", step_id))

    try:
        tokens = shlex.split(_substitute_bounded_references(command), posix=True)
    except ValueError as exc:
        findings.append(Finding("shell_parse", f"command cannot be parsed safely: {exc}", step_id))
        return findings
    if not tokens:
        findings.append(Finding("command_empty", "run command is empty", step_id))
        return findings
    if tokens[0] in SHELL_BUILTINS:
        findings.append(Finding("shell_builtin", f"shell/environment introspection is forbidden: {tokens[0]}", step_id))
        return findings
    if tokens[0] not in WRAPPERS:
        if "openclaw.invoke" not in command and tokens[0] not in SHELL_BUILTINS:
            findings.append(Finding("command_wrapper", f"unreviewed executable: {tokens[0]}", step_id))
        return findings
    if len(tokens) < 2 or tokens[1] not in command_parsers:
        findings.append(Finding("command_unknown", f"unknown vcops command: {tokens[1] if len(tokens) > 1 else ''}", step_id))
        return findings
    if tokens[1] in {"approval-decide", "approval-consume", "notification-claim", "notification-mark"}:
        findings.append(Finding("approval_boundary", f"operator/dispatcher command forbidden in workflow: {tokens[1]}", step_id))
    allowed_options = set(command_parsers[tokens[1]]._option_string_actions)
    for token in tokens[2:]:
        if token.startswith("--") and token.split("=", 1)[0] not in allowed_options:
            findings.append(Finding("option_unknown", f"unknown option for {tokens[1]}: {token}", step_id))
    return findings


def _validate_data_references(
    value: str,
    *,
    field: str,
    step_id: str,
    prior_ids: set[str],
    all_ids: set[str],
) -> list[Finding]:
    """Validate interpolation in stdin, condition, and step-env surfaces."""
    findings: list[Finding] = []
    if "$(" in value or "`" in value:
        findings.append(Finding("command_substitution", f"substitution is forbidden in {field}", step_id))
    if re.search(r"\$\{[^}]+\}", value):
        findings.append(Finding("raw_env", f"raw expansion is forbidden in {field}", step_id))
    for referenced_step, path in STEP_REF_RE.findall(value):
        if not path.startswith("json.") and path != "approved":
            findings.append(Finding("step_ref_legacy", f"legacy {field} reference: {referenced_step}.{path}", step_id))
        elif referenced_step not in prior_ids:
            code = "step_ref_order" if referenced_step in all_ids else "step_ref_unknown"
            findings.append(Finding(code, f"{field} reference is not a completed predecessor: {referenced_step}", step_id))
        if path not in SAFE_STEP_PATHS:
            findings.append(Finding("step_ref_unbounded", f"unreviewed {field} output path: {path}", step_id))
    return findings


def validate_workflow(
    path: Path,
    parser: argparse.ArgumentParser,
) -> tuple[list[Finding], dict[str, Any]]:
    # This validator enforces structural and helper-contract safety. The exact
    # per-workflow lifecycle step inventory (workflow_start/running/succeed) is
    # enforced by scripts/validate_skill_system.py's EXPECTED_WORKFLOW_STEPS.
    try:
        body = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueSafeLoader)
    except (OSError, yaml.YAMLError, DuplicateKeyError) as exc:
        return [Finding("yaml_parse", f"workflow YAML rejected: {exc}")], {}
    if not isinstance(body, dict) or not isinstance(body.get("steps"), list):
        return [Finding("workflow_shape", "workflow must be an object with a steps array")], {}

    findings: list[Finding] = []
    steps = body["steps"]
    ids = [step.get("id") for step in steps if isinstance(step, dict)]
    all_ids = {value for value in ids if isinstance(value, str)}
    seen: set[str] = set()
    command_parsers = _command_parsers(parser)
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            findings.append(Finding("step_shape", f"step {index + 1} is not an object"))
            continue
        step_id = step.get("id")
        rendered_id = step_id if isinstance(step_id, str) else None
        if not isinstance(step_id, str) or not ID_RE.fullmatch(step_id):
            findings.append(Finding("step_id", "step id is missing or invalid", rendered_id))
        elif step_id in seen:
            findings.append(Finding("step_duplicate", f"duplicate step id: {step_id}", step_id))
        if step.get("approval") is False:
            findings.append(Finding("approval_bypass", "approval:false cannot bypass a reviewed checkpoint", rendered_id))
        for field in ("stdin", "condition"):
            if field not in step:
                continue
            if not isinstance(step[field], str):
                findings.append(Finding("reference_shape", f"{field} must be a string", rendered_id))
            else:
                findings.extend(
                    _validate_data_references(
                        step[field], field=field, step_id=rendered_id or f"step-{index + 1}",
                        prior_ids=seen, all_ids=all_ids,
                    )
                )
        if "env" in step:
            if not isinstance(step["env"], dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in step["env"].items()
            ):
                findings.append(Finding("reference_shape", "env must map string keys to string values", rendered_id))
            else:
                for key, value in step["env"].items():
                    findings.extend(
                        _validate_data_references(
                            value, field=f"env.{key}", step_id=rendered_id or f"step-{index + 1}",
                            prior_ids=seen, all_ids=all_ids,
                        )
                    )
        if "run" in step:
            if not isinstance(step["run"], str):
                findings.append(Finding("command_shape", "run must be a string", rendered_id))
            else:
                findings.extend(
                    _validate_command(
                        step["run"], step_id=rendered_id or f"step-{index + 1}",
                        prior_ids=seen, all_ids=all_ids, command_parsers=command_parsers,
                    )
                )
            timeout = step.get("timeout_ms")
            if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 420_000:
                findings.append(Finding("timeout", "run steps require timeout_ms from 1 to 420000", rendered_id))
        if isinstance(step_id, str):
            seen.add(step_id)
    return findings, body


def main(argv: Sequence[str] | None = None) -> int:
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument("paths", nargs="*", type=Path)
    args = arg_parser.parse_args(argv)
    vcops_parser, findings = _load_vcops_parser()
    if vcops_parser is not None:
        for path in args.paths or sorted(WORKFLOWS.glob("*.lobster")):
            path_findings, _ = validate_workflow(path, vcops_parser)
            findings.extend(path_findings)
    report = {"result": "PASS" if not findings else "FAIL", "findings": [item.as_dict() for item in findings]}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
