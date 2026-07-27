#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Fail closed when the publication customization profile is missing or incomplete."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The sibling import below byte-compiles check_env into scripts/__pycache__,
# which then makes `verify_release.py --pristine` report an undeclared file and
# tells the operator their package is untrustworthy. Suppress it here so the
# validator stays safe to run even when someone omits `-B`.
sys.dont_write_bytecode = True

from check_env import parse_dotenv  # noqa: E402


REQUIRED_SECTIONS = {
    "organization",
    "investment_policy",
    "operating_policy",
    "models",
    "search",
    "approvals",
    "privacy_retention",
    "channels",
    "agent_profile",
    "review",
}
REVIEW_FLAGS = {
    ("investment_policy", "hard_exclusions_reviewed"),
    ("investment_policy", "rubric_reviewed"),
    ("operating_policy", "research_profiles_reviewed"),
    ("operating_policy", "source_allowlist_reviewed"),
    ("operating_policy", "cost_budget_reviewed"),
    ("operating_policy", "memo_template_reviewed"),
    ("models", "untrusted_input_policy_reviewed"),
    ("models", "provider_selection_reviewed"),
    ("search", "provider_selection_reviewed"),
    ("search", "source_quality_reviewed"),
    ("approvals", "separation_of_duties_reviewed"),
    ("privacy_retention", "lawful_bases_reviewed"),
    ("privacy_retention", "confidentiality_classes_reviewed"),
    ("privacy_retention", "retention_schedule_reviewed"),
    ("privacy_retention", "deletion_and_legal_hold_tested"),
    ("privacy_retention", "remote_processor_reviewed"),
    ("channels", "stable_identity_allowlist_reviewed"),
    ("channels", "attachment_intake_reviewed"),
    ("channels", "preference_memory_reviewed"),
    ("agent_profile", "schema_and_eval_updates_completed"),
}
PLACEHOLDER = re.compile(r"CUSTOMIZE|<[^>]+>|REPLACE|PLACEHOLDER", re.IGNORECASE)
PACKAGE = Path(__file__).resolve().parent.parent
REQUIRED_REVIEWED_ARTIFACTS = {
    "config/openclaw.json",
    "tests/g3/routing_cases.jsonl",
    "tests/g3/scoring_boundary_cases.jsonl",
    "workspaces/vc-chief/USER.md",
    "workspaces/vc-chief/vc/approval-policy.md",
    "workspaces/vc-chief/vc/channel_policy.md",
    "workspaces/vc-chief/vc/data_retention.md",
    "workspaces/vc-chief/vc/document_intake.md",
    "workspaces/vc-chief/vc/evals/memo-eval.jsonl",
    "workspaces/vc-chief/vc/evals/routing-eval.jsonl",
    "workspaces/vc-chief/vc/evals/scoring-eval.jsonl",
    "workspaces/vc-chief/vc/exclusion_criteria.md",
    "workspaces/vc-chief/vc/prequalification.md",
    "workspaces/vc-chief/vc/primary_sources.md",
    "workspaces/vc-chief/vc/research_depth.md",
    "workspaces/vc-chief/vc/scoring-rubric.v3.json",
    "workspaces/vc-chief/vc/thesis.md",
    "workspaces/vc-chief/vc/trust_boundaries.md",
    "workspaces/vc-chief/vc/third_party_connectors.md",
}
CHANNEL_DESTINATION_FIELDS = {
    "slack": ("SLACK_ALLOWED_CHANNEL_ID",),
    "msteams": ("MSTEAMS_ALLOWED_CHANNEL_ID",),
    "discord": ("DISCORD_ALLOWED_CHANNEL_ID",),
    "telegram": ("TELEGRAM_ALLOWED_GROUP_ID",),
}


class DuplicateKeyError(ValueError):
    pass


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def nonempty_stable_ids(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) and not re.search(r"\s", item) for item in value)
        and len(value) == len(set(value))
    )


def object_sections(profile: dict[str, Any], errors: list[str]) -> dict[str, dict[str, Any]]:
    sections: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_SECTIONS:
        value = profile.get(name)
        if not isinstance(value, dict):
            errors.append(f"{name} must be one JSON object")
            sections[name] = {}
        else:
            sections[name] = value
    return sections


def placeholder_paths(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(placeholder_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(placeholder_paths(child, f"{path}[{index}]"))
    elif isinstance(value, str) and PLACEHOLDER.search(value):
        found.append(path)
    return found


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "config/customization-profile.json")
    env_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    errors: list[str] = []
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise OSError("customization profile must be a regular, non-symlink file of at most 2 MiB")
        profile = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, json.JSONDecodeError, DuplicateKeyError) as exc:
        print(json.dumps({"result": "FAIL", "errors": [str(exc)]}, indent=2))
        return 1

    if not isinstance(profile, dict):
        errors.append("profile must be one JSON object")
        profile = {}
    if profile.get("profile_version") != "3.0":
        errors.append("profile_version must be 3.0")
    if profile.get("status") != "reviewed":
        errors.append("status must be reviewed after accountable human review")
    missing = sorted(REQUIRED_SECTIONS - set(profile))
    if missing:
        errors.append(f"missing required sections: {missing}")
    placeholders = placeholder_paths(profile)
    if placeholders:
        errors.append(f"unresolved customization placeholders: {placeholders}")

    sections = object_sections(profile, errors)
    for section, field in sorted(REVIEW_FLAGS):
        if sections[section].get(field) is not True:
            errors.append(f"{section}.{field} must be true")

    investment = sections["investment_policy"]
    for key in ("stages", "sectors", "geographies"):
        if not isinstance(investment.get(key), list) or not investment[key]:
            errors.append(f"investment_policy.{key} must be a non-empty list")
    models = sections["models"]
    for key in ("primary", "fast"):
        if not isinstance(models.get(key), str) or not re.fullmatch(r"[^\s/]+/[^\s/]+", models[key]):
            errors.append(f"models.{key} must be a concrete provider/model reference")
    if models.get("provider") not in {"openai", "ollama", "custom"}:
        errors.append("models.provider must be openai, ollama, or custom")
    search = sections["search"]
    if search.get("provider") not in {
        "auto", "duckduckgo", "firecrawl", "tavily", "brave", "perplexity", "exa", "searxng", "parallel-free"
    }:
        errors.append(
            "search.provider must be one of auto, duckduckgo, firecrawl, tavily, "
            "brave, perplexity, exa, searxng, parallel-free"
        )
    if search.get("fetch_provider") not in {"default", "firecrawl"}:
        errors.append("search.fetch_provider must be default or firecrawl")
    approvals = sections["approvals"]
    if not nonempty_stable_ids(approvals.get("stable_approver_ids")):
        errors.append("approvals.stable_approver_ids must be a non-empty unique stable-ID list")
    selected = sections["channels"].get("selected")
    if selected not in {"none", *CHANNEL_DESTINATION_FIELDS}:
        errors.append("channels.selected must be none, slack, msteams, discord, or telegram")
    allowed_channel_ids = approvals.get("allowed_channel_ids")
    if selected == "none":
        if allowed_channel_ids != []:
            errors.append("approvals.allowed_channel_ids must be empty when channels.selected is none")
    elif not nonempty_stable_ids(allowed_channel_ids):
        errors.append("approvals.allowed_channel_ids must be a non-empty unique stable-ID list")
    review = sections["review"]
    approved_at = str(review.get("approved_at", ""))
    try:
        parsed_approval = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        if "T" not in approved_at or parsed_approval.tzinfo is None or parsed_approval.utcoffset() is None:
            raise ValueError
    except ValueError:
        errors.append("review.approved_at must be a valid timezone-aware RFC3339 timestamp")
    organization = sections["organization"]
    try:
        ZoneInfo(str(organization.get("timezone", "")))
    except (ZoneInfoNotFoundError, ValueError):
        errors.append("organization.timezone must be a valid IANA timezone")
    if review.get("approved_by") == organization.get("deployment_owner"):
        errors.append("review.approved_by must differ from organization.deployment_owner")
    artifacts = review.get("reviewed_artifacts")
    if not isinstance(artifacts, dict):
        errors.append("review.reviewed_artifacts must be a path-to-SHA256 object")
    else:
        missing_artifacts = sorted(REQUIRED_REVIEWED_ARTIFACTS - set(artifacts))
        if missing_artifacts:
            errors.append(f"review.reviewed_artifacts is missing required files: {missing_artifacts}")
        for relative, expected_hash in sorted(artifacts.items()):
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts or relative_path.as_posix() != relative:
                errors.append(f"unsafe reviewed artifact path: {relative!r}")
                continue
            if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                errors.append(f"reviewed artifact hash must be lowercase SHA-256: {relative}")
                continue
            artifact_path = PACKAGE / relative_path
            if not artifact_path.is_file() or artifact_path.is_symlink():
                errors.append(f"reviewed artifact is missing or not a regular package file: {relative}")
                continue
            actual_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                errors.append(f"reviewed artifact changed after review: {relative}")

    if env_path is not None:
        try:
            env = parse_dotenv(env_path)
        except (OSError, ValueError) as exc:
            errors.append(f"reviewed environment is invalid: {exc}")
            env = {}
        bindings = {
            "organization.timezone": (organization.get("timezone"), env.get("TZ")),
            "models.primary": (models.get("primary"), env.get("VC_PRIMARY_MODEL")),
            "models.fast": (models.get("fast"), env.get("VC_FAST_MODEL")),
            "models.provider": (models.get("provider"), env.get("VC_MODEL_PROVIDER")),
            "search.provider": (search.get("provider"), env.get("VC_WEB_SEARCH_PROVIDER")),
            "search.fetch_provider": (search.get("fetch_provider"), env.get("VC_WEB_FETCH_PROVIDER")),
            "channels.selected": (selected, env.get("PRIMARY_CHANNEL")),
        }
        for label, (reviewed_value, deployed_value) in bindings.items():
            if reviewed_value != deployed_value:
                errors.append(
                    f"{label} does not match the reviewed environment: "
                    f"profile={reviewed_value!r}, env={deployed_value!r}"
                )
        expected_destinations = (
            []
            if selected == "none"
            else [env.get(field, "") for field in CHANNEL_DESTINATION_FIELDS.get(selected, ())]
        )
        if allowed_channel_ids != expected_destinations:
            errors.append(
                "approvals.allowed_channel_ids must exactly match the selected environment "
                f"destination IDs: {expected_destinations}"
            )

    report = {
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
        "checked_file": str(path),
        "checked_environment": str(env_path) if env_path is not None else None,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
