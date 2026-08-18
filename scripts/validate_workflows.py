#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Fail-closed static validator for the fixed Version 3 Lobster workflows.

The validator treats workflow YAML and command text as untrusted. Option
inventories are derived from vcops.build_parser() and the accepted command set
is derived per wrapper from vcops's own WORKFLOW_COMMANDS /
AGENT_READ_ONLY_COMMANDS, so CLI/workflow drift is a release failure. It never
executes a workflow or opens the database.
"""

from __future__ import annotations

import argparse
import collections.abc
import functools
import importlib.util
import json
import os
import re
import shlex
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml
import yaml.constructor
import yaml.resolver


# The inventory below is derived by loading vcops.py by path, which would
# byte-compile it into workspaces/vc-chief/vc/bin/__pycache__ and make
# `verify_release.py --pristine` report an undeclared file. Suppress it so the
# validator stays safe to run even when someone omits `-B`.
sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent.parent
WORKFLOWS = PACKAGE / "workspaces/vc-chief/vc/workflows"
VCOPS = PACKAGE / "workspaces/vc-chief/vc/bin/vcops.py"
# Each wrapper `exec`s vcops.py through `env -i` with one mode flag set, and
# vcops refuses any command outside that mode's own set (vcops.py:6410,6416).
# The parser-wide subcommand inventory is therefore NOT the world a workflow
# step can reach: at the time this mapping was added the parser had 53
# subcommands while WORKFLOW_COMMANDS had 39 and AGENT_READ_ONLY_COMMANDS 16.
# Validating against the parser alone accepted ten commands the workflow lane
# refuses at runtime — including `data-erase-lead`, whose full option set
# passed both release-gate validators with zero findings — so the gate could
# certify a workflow that the runtime is the only thing left to stop. Derive
# the accepted set per wrapper from the runtime's own enumerable sets instead.
WRAPPER_COMMAND_SETS = {
    "/workspaces/vc-chief/vc/bin/agent/vcops": "AGENT_READ_ONLY_COMMANDS",
    "/workspaces/vc-chief/vc/bin/vcops-workflow": "WORKFLOW_COMMANDS",
}
WRAPPERS = frozenset(WRAPPER_COMMAND_SETS)
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
# Lobster 2026.6.11 accepts far more of a workflow file than this package
# authors. `command:` is a full alias of `run:` (the runner resolves
# `step.run ?? step.command`), `when:` takes precedence over `condition:`, and
# `pipeline:`/`workflow:`/`parallel:`/`for_each:` are additional execution
# forms. A key this validator does not know about is therefore not inert: it
# would execute, or gate execution, entirely unchecked. Validate against a
# closed authoring subset instead of against the keys we happen to inspect.
ALLOWED_STEP_KEYS = {"id", "run", "stdin", "env", "condition", "timeout_ms", "approval"}
ALLOWED_WORKFLOW_KEYS = {"name", "args", "steps"}
# Approving the `run:` text does not approve the executable that runs it. The
# pinned runtime resolves the inline shell from the step environment
# (`resolveInlineShellCommand` in lobster's shell.js reads `LOBSTER_SHELL` and,
# when set, executes THAT binary with the run text demoted to an `-lc`
# argument), so an unconstrained env key silently replaces the immutable path
# this validator just checked. Constrain the KEY names to the closed `VCOPS_`
# namespace that all eighteen shipped workflows use, making LOBSTER_SHELL,
# PATH, IFS, LD_PRELOAD and every other execution-influencing key a release
# failure. This is the "caller-controlled ... environment key" rejection
# docs/TASKFLOW_LOBSTER_COMPATIBILITY.md requires of a static release
# validator, without which the G5 "steps invoke only the exact immutable
# vcops path" claim is about the command text rather than the invocation.
STEP_ENV_KEY_RE = re.compile(r"VCOPS_[A-Z0-9_]+")


class DuplicateKeyError(ValueError):
    pass


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader: UniqueSafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        # Replacing SafeConstructor.construct_mapping means re-performing its
        # hashability guard. YAML permits a complex key (`? [a, b]`), which
        # arrives here as a list; without this the `key in result` lookup below
        # raises TypeError outside every handler in this module and the
        # validator aborts with a traceback that never names the file, instead
        # of the bounded `yaml_parse` finding. ConstructorError is a
        # yaml.YAMLError, which validate_workflow() already catches.
        if not isinstance(key, collections.abc.Hashable):
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                "found unhashable key", key_node.start_mark,
            )
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


@functools.lru_cache(maxsize=1)
def _load_vcops_module() -> Any:
    """Execute the reviewed vcops module by path, once per process.

    Two derivations read this module — the option inventory via build_parser()
    and the per-wrapper command sets — and `validate_workflow` asks for the
    latter once per workflow file. Without the cache the eighteen-file run
    would exec vcops.py nineteen times for no benefit. lru_cache does not
    memoize exceptions, so a failed load stays a failed load on every call.
    """
    spec = importlib.util.spec_from_file_location("v3_workflow_vcops", VCOPS)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot construct vcops import spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wrapper_command_sets() -> dict[str, frozenset[str]]:
    """Map each reviewed wrapper to the command set its mode actually permits.

    Reject an empty or wrongly-typed set rather than falling back to the
    parser-wide inventory: a silently empty set here would restore exactly the
    over-acceptance this derivation exists to remove.
    """
    module = _load_vcops_module()
    sets: dict[str, frozenset[str]] = {}
    for wrapper, attribute in WRAPPER_COMMAND_SETS.items():
        names = getattr(module, attribute)
        if not isinstance(names, (set, frozenset)) or not names or not all(isinstance(name, str) for name in names):
            raise TypeError(f"vcops.{attribute} is not a non-empty set of command names")
        sets[wrapper] = frozenset(names)
    return sets


def _load_vcops_parser() -> tuple[argparse.ArgumentParser | None, list[Finding]]:
    try:
        module = _load_vcops_module()
        parser = module.build_parser()
        if not isinstance(parser, argparse.ArgumentParser):
            raise TypeError("build_parser did not return ArgumentParser")
        # Fail closed here rather than at first use: the per-wrapper command
        # sets gate as much as the parser does, and a run that loaded one but
        # not the other would report PASS over an unvalidated command surface.
        _wrapper_command_sets()
        return parser, []
    except Exception as exc:  # fail closed with a bounded public error
        return None, [Finding("vcops_parser", f"cannot load reviewed vcops parser: {type(exc).__name__}: {exc}")]


def _command_parsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            # choices is typed loosely; every value is an ArgumentParser at
            # runtime, and filtering states that instead of asserting it.
            return {
                name: sub
                for name, sub in action.choices.items()
                if isinstance(sub, argparse.ArgumentParser)
            }
    return {}


def _substitute_bounded_references(command: str) -> str:
    command = STEP_REF_RE.sub("1", command)
    command = re.sub(r"\$(?:LOBSTER_ARG|VCOPS)_[A-Z][A-Z0-9_]*", "1", command)
    return command


def _shell_active_text(command: str, *, expansion: bool = False) -> str:
    """Blank out the text `/bin/sh -lc` cannot act on, preserving length.

    Control operators (including a newline, which terminates a command just as
    `;` does) are inert inside either quote style, so both are blanked for the
    operator scan. Parameter expansion is inert only inside single quotes, so
    `expansion=True` keeps double-quoted text. Scanning the raw string instead
    would both miss a newline smuggled through a YAML block scalar and reject
    an ordinary quoted argument such as `--name "Ben & Co"`.
    """
    rendered: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        character = command[index]
        if quote is None:
            if character in "'\"":
                quote = character
                rendered.append(" ")
            elif character == "\\":
                # A backslash escapes the next character out of shell meaning.
                rendered.append(" ")
                index += 1
                if index < len(command):
                    rendered.append(" ")
            else:
                rendered.append(character)
        elif character == quote:
            quote = None
            rendered.append(" ")
        elif quote == '"' and character == "\\":
            rendered.append(" ")
            index += 1
            if index < len(command):
                rendered.append(" ")
        else:
            rendered.append(character if (expansion and quote == '"') else " ")
        index += 1
    return "".join(rendered)


def _double_quoted_mask(command: str) -> list[bool]:
    """Mark, per character index, whether `/bin/sh -lc` reads it inside `"`.

    `_shell_active_text` answers "can the shell act on this position"; this
    answers "is this position inside a double-quoted region", which is the
    property that actually contains a channel-controlled expansion. Testing
    the single preceding byte does not: `""$X`, `"p"$X` and `"a"$X"b"` all put
    a quote character immediately before the `$` while leaving the expansion
    itself unquoted, so it word-splits and glob-expands exactly as bare `$X`
    does.

    Backslash handling matches `_shell_active_text`: a backslash and the
    character it escapes are both marked unquoted. That makes the escaped
    spellings (`\\$X`, `"\\$X"`) report as unquoted even though they expand to
    nothing at all. Rejecting an inert spelling is the fail-closed direction,
    and no shipped workflow uses one — the whole workflow inventory validates
    with zero findings under this rule — so this stays a rejection rather than
    a carve-out.
    """
    mask = [False] * len(command)
    quote: str | None = None
    index = 0
    while index < len(command):
        character = command[index]
        if quote is None:
            if character in "'\"":
                quote = character
            elif character == "\\":
                # The escaped character is outside any quoting too.
                index += 1
        elif character == quote:
            quote = None
        elif quote == '"' and character == "\\":
            index += 1
        else:
            mask[index] = quote == '"'
        index += 1
    return mask


def _validate_command(
    command: str,
    *,
    step_id: str,
    prior_ids: set[str],
    all_ids: set[str],
    command_parsers: dict[str, argparse.ArgumentParser],
    wrapper_commands: dict[str, frozenset[str]],
) -> list[Finding]:
    findings: list[Finding] = []
    if "$(" in command or "`" in command:
        findings.append(Finding("command_substitution", "shell command substitution is forbidden", step_id))
    if re.search(r"\$\{[^}]+\}", command):
        findings.append(Finding("raw_env", "raw shell/template expansion is forbidden", step_id))
    # Both reference families carry channel-controlled values ($VCOPS_* step
    # env is fed from trusted-context fields such as sender_id, which are
    # length-bounded but not charset-bounded), so the expansion has to sit
    # inside a double-quoted region or the `/bin/sh -lc` layer word-splits and
    # globs it. Decide that against the command's quote state, not against the
    # byte before the `$`: a preceding-character test passes `""$X` and
    # `"a"$X"b"`, which are unquoted expansions with a quote character in front
    # of them. Same alternation as _substitute_bounded_references, which erases
    # these references before the later scans.
    quoted = _double_quoted_mask(command)
    for reference in sorted({
        match.group(0)
        for match in re.finditer(r"\$(?:LOBSTER_ARG|VCOPS)_[A-Z][A-Z0-9_]*", command)
        if not quoted[match.start()]
    }):
        findings.append(
            Finding(
                "arg_unquoted",
                "Lobster argument and step-env references must sit inside a "
                f"double-quoted region: {reference}",
                step_id,
            )
        )
    if "openclaw.invoke" in command:
        findings.append(Finding("openclaw_invoke", "arbitrary OpenClaw tool invocation is forbidden", step_id))
    if re.search(r"(?:^|\s)--unsafe(?:-|\b)|(?:^|\s)--unsafe-ground(?:\s|$)", command):
        findings.append(Finding("unsafe_authority", "unsafe authority flags are forbidden", step_id))

    for referenced_step, path in STEP_REF_RE.findall(command):
        # A direct step reference in run text is substituted TEXTUALLY, before
        # the shell sees it, so quoting cannot contain it the way it contains
        # $LOBSTER_ARG_*/$VCOPS_* (which Lobster sets as real environment
        # variables that `sh` does not re-parse). A value carrying a double
        # quote escapes its own quotes and injects. The arg_unquoted rule above
        # therefore does not cover this surface at all: carry step values
        # through a quoted VCOPS_ step-env entry instead. No shipped workflow
        # puts a step reference in run text, so this is a closed surface.
        findings.append(
            Finding(
                "step_ref_in_command",
                "step reference must be carried through a quoted VCOPS_ step-env "
                f"value, not spliced into run text: {referenced_step}.{path}",
                step_id,
            )
        )
        if not path.startswith("json.") and path != "approved":
            findings.append(Finding("step_ref_legacy", f"legacy step reference: {referenced_step}.{path}", step_id))
        elif referenced_step not in prior_ids:
            code = "step_ref_order" if referenced_step in all_ids else "step_ref_unknown"
            findings.append(Finding(code, f"step reference is not a completed predecessor: {referenced_step}", step_id))
        if path not in SAFE_STEP_PATHS:
            findings.append(Finding("step_ref_unbounded", f"unreviewed step-output path: {path}", step_id))

    # The runner is `/bin/sh -lc` with the full gateway environment, so any
    # chaining/redirection operator, and any word expansion the shell performs
    # before argv is built, sidesteps every command and option allowlist below.
    # The four scanned here are command substitution and `${...}` (above),
    # parameter expansion, pathname (glob) expansion, and tilde expansion.
    # Scan after bounded-reference substitution: whatever `$name` remains is
    # not a reviewed reference. Every scan looks only at shell-active text, so
    # a quoted literal is not a false positive and a newline cannot smuggle a
    # second command past them.
    sanitized = _substitute_bounded_references(command)
    active = _shell_active_text(sanitized)
    if re.search(r"[;|&<>\n\r]", active):
        findings.append(Finding("shell_operator", "shell chaining/redirection/backgrounding is forbidden", step_id))
    expandable = _shell_active_text(sanitized, expansion=True)
    for name in sorted({match.group(1) for match in re.finditer(r"\$(?!\{)([A-Za-z_][A-Za-z0-9_]*)", expandable)}):
        findings.append(Finding("raw_env", f"raw environment expansion is forbidden: ${name}", step_id))
    # Pathname (glob) and tilde expansion were the two the scans above missed.
    # Both are inert inside either quote style, which is why they run against
    # `active` rather than `expandable`.
    #
    # Glob is the sharper of the two because it changes the argv WORD COUNT,
    # not just a word's value: `--path "$LOBSTER_ARG_DOCUMENT_PATH"*` puts the
    # reference inside a double-quoted region, so the arg_unquoted rule above
    # certifies it as unsplittable, and the trailing unquoted `*` then hands
    # the whole word back to pathname expansion anyway. Measured against
    # /bin/sh with a stub at the wrapper path, that text delivered two `--path`
    # values chosen by directory contents, and `--path /tmp/media/*` delivered
    # a `/tmp/media/--confidentiality` word that no option allowlist ever saw.
    # `--path ~/x.pdf` likewise reached the helper as `/home/node/x.pdf`.
    #
    # This costs the shipped inventory nothing: measured over the eighteen
    # workflows, no `run:` step carries a shell-active `*`, `?`, `[` or `~`,
    # because every path argument is a fully double-quoted whole-value
    # reference. tests/g5 asserts the whole inventory yields zero findings, so
    # a workflow that later needs one fails there rather than silently.
    if re.search(r"[*?\[]", active):
        findings.append(
            Finding(
                "glob_expansion",
                "unquoted pathname-expansion characters (* ? [) are forbidden: "
                "the shell replaces the word with matching filenames before vcops sees argv",
                step_id,
            )
        )
    if re.search(r"(?:^|\s)~", active):
        findings.append(
            Finding(
                "tilde_expansion",
                "an unquoted leading ~ is forbidden: the shell rewrites the word to a home directory "
                "before vcops sees argv",
                step_id,
            )
        )

    try:
        tokens = shlex.split(sanitized, posix=True)
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
    # Allowlisted is not the same as present: the wrapper these steps invoke
    # must actually exist and be executable in the package, or every workflow
    # fails at runtime while this gate reports PASS.
    wrapper = PACKAGE / tokens[0].lstrip("/")
    if not wrapper.is_file():
        findings.append(Finding("command_wrapper_missing", f"{tokens[0]} does not exist in the package", step_id))
    elif not os.access(wrapper, os.X_OK):
        findings.append(Finding("command_wrapper_not_executable", f"{tokens[0]} is not executable", step_id))
    if len(tokens) < 2 or tokens[1] not in command_parsers:
        findings.append(Finding("command_unknown", f"unknown vcops command: {tokens[1] if len(tokens) > 1 else ''}", step_id))
        return findings
    # The wrapper decides the mode, and the mode decides the command set. A
    # command outside the invoking wrapper's set is refused by vcops at
    # runtime, so accepting it here means the gate certifies a workflow that
    # cannot run — and, worse, that the gate is not what stops an operator-lane
    # command such as `data-erase-lead` from being written into a workflow.
    permitted = wrapper_commands.get(tokens[0], frozenset())
    if tokens[1] not in permitted:
        findings.append(
            Finding(
                "command_wrapper_scope",
                f"{tokens[1]} is outside the command set {tokens[0]} permits "
                f"({WRAPPER_COMMAND_SETS.get(tokens[0], 'no reviewed set')})",
                step_id,
            )
        )
    # Subsumed by the derived rule above (none of these four is in either
    # runtime set), and kept because it names the boundary that was crossed
    # rather than only the set that was left; tests/g5 pins this code.
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
    # `UnicodeError` covers the decode half of read_text: UnicodeDecodeError is
    # a ValueError, so it is none of the other three types, and without it a
    # workflow saved in a non-UTF-8 encoding aborts the `fixed-workflows` gate
    # step with a traceback that does not name the offending workflow file.
    # scripts/validate_skill_system.py reads the same *.lobster set and reports
    # a decode failure over it as workflow_parse / workflow_read.
    try:
        wrapper_commands = _wrapper_command_sets()
    except Exception as exc:  # fail closed with a bounded public error
        return [Finding("vcops_command_sets", f"cannot load reviewed vcops command sets: {type(exc).__name__}: {exc}")], {}
    try:
        body = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueSafeLoader)  # noqa: S506  # SafeLoader subclass; adds duplicate-key rejection
    except (OSError, UnicodeError, yaml.YAMLError, DuplicateKeyError) as exc:
        return [Finding("yaml_parse", f"workflow YAML rejected: {exc}")], {}
    if not isinstance(body, dict) or not isinstance(body.get("steps"), list):
        return [Finding("workflow_shape", "workflow must be an object with a steps array")], {}

    findings: list[Finding] = []
    # Top-level `env:` and `cwd:` are merged into every step's environment and
    # base directory by Lobster, so they are execution surface too.
    for key in sorted(str(name) for name in set(body) - ALLOWED_WORKFLOW_KEYS):
        findings.append(
            Finding(
                "workflow_key_unknown",
                f"unreviewed workflow key: {key} (allowed: {', '.join(sorted(ALLOWED_WORKFLOW_KEYS))})",
            )
        )
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
        for key in sorted(str(name) for name in set(step) - ALLOWED_STEP_KEYS):
            findings.append(
                Finding(
                    "step_key_unknown",
                    f"unreviewed step key: {key} (allowed: {', '.join(sorted(ALLOWED_STEP_KEYS))})",
                    rendered_id,
                )
            )
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
                    if not STEP_ENV_KEY_RE.fullmatch(key):
                        findings.append(
                            Finding(
                                "env_key",
                                f"step environment key outside the reviewed VCOPS_ namespace: {key}",
                                rendered_id,
                            )
                        )
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
                        wrapper_commands=wrapper_commands,
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
        paths = list(args.paths) or sorted(WORKFLOWS.glob("*.lobster"))
        if not paths:
            # Fail closed, mirroring run_g4's "no numbered migrations found":
            # an empty inventory validated successfully would report PASS
            # while proving nothing.
            findings.append(Finding("workflow_inventory_empty", "no workflow files found to validate"))
        for path in paths:
            path_findings, _ = validate_workflow(path, vcops_parser)
            findings.extend(path_findings)
    report = {"result": "PASS" if not findings else "FAIL", "findings": [item.as_dict() for item in findings]}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
