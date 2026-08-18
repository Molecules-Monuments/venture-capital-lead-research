#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Run the frozen 100k-company/1m-fact entity-resolution scale gate.

The benchmark creates a disposable PostgreSQL cluster, applies the migration
series once (the state a real deployment reaches), loads the declared reference
cardinalities, and calls the real resolver helper through the runtime database
role.  It never targets a configured database and removes the cluster on exit.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row


# This gate loads scripts/run_g4.py (and through it scripts/check_env.py) by
# path, which would byte-compile both into scripts/__pycache__ and make
# `verify_release.py --pristine` report undeclared files. Suppress it so the
# gate stays safe to run even when someone omits `-B`.
sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent.parent
COMPANY_COUNT = 100_000
FACT_COUNT = 1_000_000
FACTS_PER_COMPANY = FACT_COUNT // COMPANY_COUNT
FUZZY_CASES = 100
EXACT_CASES = 60
# Each fuzzy case is a confusable cluster: one target plus this many trigram-close
# distractor companies. Their presence is what makes the benchmark discriminate
# resolver ranking quality instead of resolving a name with no near-neighbours.
DISTRACTORS_PER_CLUSTER = 4
MAX_P95_MS = 250.0
MIN_FUZZY_RECALL = 0.90
# Ranking precision: the top-ranked candidate must be the true target, not a
# confusable near-neighbour. A resolver that cannot rank the exact-ish match above
# its look-alikes fails this even though recall may still be high.
MIN_FUZZY_PRECISION_AT_1 = 0.90
# The dataset must actually contain confusables: on average a fuzzy query must
# surface more than one candidate, or precision@1 would be the old 1.0 artifact.
MIN_MEAN_CANDIDATES = 1.5


# Sixteen letters index a hex digit, so an md5 maps to a distinctive, purely
# alphabetic pseudo-word. Distinct per-cluster base words keep clusters from
# bleeding into each other (a query matches only its own cluster's members), so
# the trigram `%` predicate stays selective and index-accelerated at scale.
_LETTERS = "abcdefghijklmnop"
_BASE_LEN = 14
_SUB_POSITIONS = (3, 6, 9, 11)  # distractor substitution sites
_DELETE_POSITION = 7            # query deletion site (distinct from the above)


def cluster_target_name(k: int) -> str:
    # Names only, never a security property — and the explicit flag is what
    # keeps this working on a FIPS-mode host, where a bare md5() raises.
    digest = hashlib.md5(f"cluster:{k}".encode(), usedforsecurity=False).hexdigest()
    return "".join(_LETTERS[int(ch, 16)] for ch in digest[:_BASE_LEN])


def cluster_distractor_names(k: int) -> list[str]:
    base = cluster_target_name(k)
    names = []
    for pos in _SUB_POSITIONS:
        rotated = _LETTERS[(_LETTERS.index(base[pos]) + 1) % len(_LETTERS)]
        names.append(base[:pos] + rotated + base[pos + 1:])
    return names


def cluster_query_name(k: int) -> str:
    # One character deleted at a site none of the distractors touch: the query is
    # one edit from the target and two from every distractor, so a correctly
    # ranking resolver places the target first among its confusable neighbours.
    base = cluster_target_name(k)
    return base[:_DELETE_POSITION] + base[_DELETE_POSITION + 1:]


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


run_g4 = load_module("openclaw_scale_run_g4", PACKAGE / "scripts/run_g4.py")
vcops = load_module(
    "openclaw_scale_vcops", PACKAGE / "workspaces/vc-chief/vc/bin/vcops.py"
)


def one_row(cur: Any) -> Any:
    """Return the row the preceding statement is required to have produced.

    Every call site follows a RETURNING or an EXPLAIN, both of which always
    yield exactly one row. fetchone() is nonetheless Optional, and subscripting
    the None case raised a bare TypeError that said nothing about which
    statement misbehaved.
    """
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("expected one row from the preceding statement, got none")
    return row


def percentile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    position = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[position]


def seed_confusable_clusters(owner_url: str) -> dict[int, int]:
    """Seed FUZZY_CASES confusable clusters (one target + distractors each) and
    return {cluster -> target company_id}. The distractors give every fuzzy query
    trigram-close competitors, so precision@1 measures real ranking quality."""
    targets: dict[int, int] = {}
    with psycopg.connect(owner_url) as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0")
        for k in range(1, FUZZY_CASES + 1):
            members = [(cluster_target_name(k), True)]
            members += [(name, False) for name in cluster_distractor_names(k)]
            for idx, (name, is_target) in enumerate(members):
                cur.execute(
                    "INSERT INTO companies (name, canonical_domain) VALUES (%s, %s) RETURNING id",
                    (name, f"cluster-{k}-{idx}.invalid"),
                )
                company_id = int(one_row(cur)[0])
                cur.execute(
                    """INSERT INTO company_aliases
                         (company_id, alias_kind, alias_value, normalized_alias,
                          status, confidentiality, confidence, created_by)
                       VALUES (%s, 'canonical_name', %s, %s, 'active', 'internal', 1.000, 'scale-cluster')""",
                    (company_id, name, vcops.normalize_identity_name(name)),
                )
                if is_target:
                    targets[k] = company_id
    with psycopg.connect(owner_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("ANALYZE companies, company_aliases")
    return targets


def seed_reference_data(owner_url: str) -> dict[str, float]:
    timings: dict[str, float] = {}
    started = time.perf_counter()
    with psycopg.connect(owner_url) as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0")
        cur.execute(
            """INSERT INTO companies (name, canonical_domain)
               SELECT 'Scale Company ' || lpad(i::text, 6, '0'),
                      'scale-' || i::text || '.invalid'
               FROM generate_series(1, %s) AS generated(i)""",
            (COMPANY_COUNT,),
        )
        # normalize() BEFORE btrim(), the same order migration 006's backfill
        # uses. btrim() with no character argument strips only U+0020, while
        # NFKC maps U+00A0 and U+3000 onto U+0020 -- so trimming first lets
        # normalisation reintroduce edge whitespace and the derived value fails
        # company_aliases' own `btrim(normalized_alias) = normalized_alias`
        # CHECK. This seed carried the trim-first spelling after 006 was
        # corrected. It never aborted, because the benchmark's own names are
        # ASCII ('Scale Company 000001'), which is the worse failure: the scale
        # gate's corpus would have been derived by a normalisation rule the
        # deployed migration no longer performs, so the retrieval figures would
        # not have been measured over production's data.
        cur.execute(
            """INSERT INTO company_aliases
                 (company_id, alias_kind, alias_value, normalized_alias,
                  status, confidentiality, confidence, created_by)
               SELECT id, 'canonical_name', name,
                      lower(btrim(normalize(name, NFKC))),
                      'active', 'internal', 1.000, 'scale-benchmark'
               FROM companies"""
        )
        cur.execute(
            """INSERT INTO company_domains
                 (company_id, hostname, domain_kind, status, confidentiality,
                  confidence, verified_at, created_by)
               SELECT id, canonical_domain, 'primary', 'verified', 'internal',
                      1.000, clock_timestamp(), 'scale-benchmark'
               FROM companies"""
        )
    timings["companies_aliases_domains"] = time.perf_counter() - started

    started = time.perf_counter()
    with psycopg.connect(owner_url) as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0")
        cur.execute(
            """INSERT INTO sources
                 (source_kind, title, canonical_uri, trust_level, confidentiality)
               VALUES ('internal_analysis', 'Scale benchmark source',
                       'https://scale.invalid/source', 'internal_admin', 'internal')
               RETURNING id"""
        )
        source_id = int(one_row(cur)[0])
        # The benchmark measures the production query path, not bulk-ingest
        # trigger throughput. Constraints and indexes remain active; disabling
        # user triggers only avoids one million redundant lineage checks while
        # loading synthetic, lead-less facts.
        cur.execute("ALTER TABLE facts DISABLE TRIGGER USER")
        cur.execute(
            """INSERT INTO facts
                 (company_id, fact_type, definition, value_kind, value_numeric,
                  fact_status, confidence, created_by)
               SELECT c.id, 'scale_metric_' || metric::text,
                      'synthetic scale benchmark metric', 'numeric', metric,
                      'verified_fact', 1.000, 'scale-benchmark'
               FROM companies c
               CROSS JOIN generate_series(1, %s) AS generated(metric)""",
            (FACTS_PER_COMPANY,),
        )
        cur.execute("ALTER TABLE facts ENABLE TRIGGER USER")
        cur.execute(
            """INSERT INTO fact_sources
                 (fact_id, source_id, evidence_role, citation_label, source_locator)
               SELECT id, %s, 'primary', 'scale-' || id::text,
                      'scale:fact:' || id::text
               FROM facts""",
            (source_id,),
        )
    timings["facts_and_provenance"] = time.perf_counter() - started

    started = time.perf_counter()
    with psycopg.connect(owner_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "ANALYZE companies, company_aliases, company_domains, facts, fact_sources, sources"
        )
    timings["analyze"] = time.perf_counter() - started
    return timings


def explain_plans(runtime_url: str, fuzzy_target: str) -> dict[str, Any]:
    plans: dict[str, Any] = {}
    # dict_row is psycopg's own documented RowFactory; ty 0.0.65 does not
    # match it against connect()'s row_factory overloads.
    with psycopg.connect(runtime_url, row_factory=dict_row) as conn, conn.cursor() as cur:  # ty: ignore[invalid-argument-type]
        cur.execute("SELECT set_config('pg_trgm.similarity_threshold', '0.18', true)")
        cur.execute(
            """EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
               SELECT c.id,c.name,c.canonical_domain,c.status,a.confidentiality,
                      a.confidence,a.alias_kind
               FROM company_aliases a JOIN companies c ON c.id=a.company_id
               WHERE a.normalized_alias=%s AND a.status='active'
                 AND a.valid_to IS NULL""",
            ("scale company 050001",),
        )
        plans["exact_alias"] = one_row(cur)["QUERY PLAN"][0]
        cur.execute(
            """EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
               SELECT c.id,c.name,c.canonical_domain,c.status,a.alias_value,
                      a.normalized_alias,a.confidentiality
               FROM company_aliases a JOIN companies c ON c.id=a.company_id
               WHERE a.normalized_alias %% %s
                 AND a.status='active' AND a.valid_to IS NULL
               ORDER BY similarity(a.normalized_alias,%s) DESC,a.updated_at DESC,a.id
               LIMIT 500""",
            (fuzzy_target, fuzzy_target),
        )
        plans["fuzzy_candidate"] = one_row(cur)["QUERY PLAN"][0]
        cur.execute(
            """EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
               SELECT f.id
               FROM facts f
               JOIN fact_sources fs ON fs.fact_id=f.id
               JOIN sources s ON s.id=fs.source_id
               WHERE f.company_id=50000 AND f.fact_status='verified_fact'
                 AND NOT EXISTS (
                   SELECT 1 FROM facts newer WHERE newer.supersedes_fact_id=f.id
                 )
               ORDER BY f.observed_at DESC,f.id DESC,fs.id
               LIMIT 200"""
        )
        plans["current_facts"] = one_row(cur)["QUERY PLAN"][0]
    return plans


def run_benchmark(runtime_url: str, cluster_targets: dict[int, int]) -> dict[str, Any]:
    exact_latencies: list[float] = []
    fuzzy_latencies: list[float] = []
    fuzzy_recall_hits = 0     # target present anywhere in the candidate set
    fuzzy_top1_hits = 0       # target is the top-ranked candidate (precision@1)
    fuzzy_candidate_total = 0

    # dict_row is psycopg's own documented RowFactory; ty 0.0.65 does not
    # match it against connect()'s row_factory overloads.
    with psycopg.connect(runtime_url, row_factory=dict_row) as conn, conn.cursor() as cur:  # ty: ignore[invalid-argument-type]
        cur.execute("SET statement_timeout = '5s'")
        for offset in range(EXACT_CASES):
            company_id = 1 + (offset * (COMPANY_COUNT - 1) // (EXACT_CASES - 1))
            identity = {
                "domain": f"scale-{company_id}.invalid",
                "normalized_name": None,
                "normalized_alias": None,
            }
            started = time.perf_counter()
            result = vcops._resolve_entity(
                cur,
                identity=identity,
                purpose="research",
                requester_id="scale:exact",
                max_confidentiality="internal",
                limit=20,
            )
            exact_latencies.append((time.perf_counter() - started) * 1000)
            if result["decision"]["outcome"] != "existing":
                raise RuntimeError(f"exact resolver miss for company {company_id}")
            if int(result["decision"]["matched_company_id"]) != company_id:
                raise RuntimeError(f"exact resolver mismatch for company {company_id}")
            if len(result["current_facts"]) != FACTS_PER_COMPANY:
                raise RuntimeError(f"fact retrieval mismatch for company {company_id}")

        for k in range(1, FUZZY_CASES + 1):
            target_id = cluster_targets[k]
            query_name = cluster_query_name(k)
            identity = {
                "name": query_name,
                "normalized_name": vcops.normalize_identity_name(query_name),
                "normalized_alias": None,
            }
            started = time.perf_counter()
            result = vcops._resolve_entity(
                cur,
                identity=identity,
                purpose="research",
                requester_id="scale:fuzzy",
                max_confidentiality="internal",
                limit=20,
            )
            fuzzy_latencies.append((time.perf_counter() - started) * 1000)
            candidates = result["decision"]["candidates"]
            ranked_ids = [int(candidate["company_id"]) for candidate in candidates]
            fuzzy_candidate_total += len(ranked_ids)
            fuzzy_recall_hits += int(target_id in ranked_ids)
            fuzzy_top1_hits += int(bool(ranked_ids) and ranked_ids[0] == target_id)

    all_latencies = exact_latencies + fuzzy_latencies
    recall = fuzzy_recall_hits / FUZZY_CASES
    precision_at_1 = fuzzy_top1_hits / FUZZY_CASES
    mean_candidates = fuzzy_candidate_total / FUZZY_CASES
    return {
        # Cases whose target the resolver actually returned first: the exact
        # cases that completed (each one raises above on a miss, so reaching
        # here means all of them resolved their domain key) plus the fuzzy cases
        # that ranked the true target at position 1. This is the per-case tally
        # main() reports; `thresholds_met` below is a verdict, not a count, and
        # conflating the two is what made the emitted `passed`/`failed` pair
        # incapable of expressing 150/160.
        "resolved_cases": len(exact_latencies) + fuzzy_top1_hits,
        "exact": {
            "cases": len(exact_latencies),
            "p50_ms": round(statistics.median(exact_latencies), 3),
            "p95_ms": round(percentile(exact_latencies, 0.95), 3),
            "max_ms": round(max(exact_latencies), 3),
        },
        "fuzzy": {
            "cases": FUZZY_CASES,
            "distractors_per_cluster": DISTRACTORS_PER_CLUSTER,
            "recall_hits": fuzzy_recall_hits,
            "top1_hits": fuzzy_top1_hits,
            "mean_candidates_per_case": round(mean_candidates, 3),
            "recall": round(recall, 4),
            "precision_at_1": round(precision_at_1, 4),
            "p50_ms": round(statistics.median(fuzzy_latencies), 3),
            "p95_ms": round(percentile(fuzzy_latencies, 0.95), 3),
            "max_ms": round(max(fuzzy_latencies), 3),
        },
        "overall_p95_ms": round(percentile(all_latencies, 0.95), 3),
        "thresholds": {
            "max_p95_ms": MAX_P95_MS,
            "minimum_fuzzy_recall": MIN_FUZZY_RECALL,
            "minimum_fuzzy_precision_at_1": MIN_FUZZY_PRECISION_AT_1,
            "minimum_mean_candidates": MIN_MEAN_CANDIDATES,
        },
        # Named `thresholds_met`, not `passed`, because it sat one dictionary
        # away from the report's integer `passed` counter and was assigned to
        # it: the four frozen thresholds are a release verdict over the whole
        # run, never a count of cases.
        "thresholds_met": (
            percentile(all_latencies, 0.95) <= MAX_P95_MS
            and recall >= MIN_FUZZY_RECALL
            and precision_at_1 >= MIN_FUZZY_PRECISION_AT_1
            and mean_candidates >= MIN_MEAN_CANDIDATES
        ),
    }


def main() -> int:
    started = time.perf_counter()
    report: dict[str, Any] = {
        "suite": "retrieval-scale",
        "target_version": "3.0",
        "reference_dataset": {
            "companies": COMPANY_COUNT,
            "facts": FACT_COUNT,
            "facts_per_company": FACTS_PER_COMPANY,
            "confusable_clusters": FUZZY_CASES,
            "distractors_per_cluster": DISTRACTORS_PER_CLUSTER,
        },
        "cases": EXACT_CASES + FUZZY_CASES,
        # passed/failed are per-case counts over `cases`, as in run_g6_image.py
        # -- not a restatement of `result`. Until the benchmark returns, no case
        # has resolved, so every one of them counts as unresolved; an aborted
        # run therefore reports 0/160 rather than the old 0 passed / 1 failed,
        # which did not sum to `cases` and invited the same conflation that made
        # a completed run unable to report anything but 160/160 or 0/160.
        "passed": 0,
        "failed": EXACT_CASES + FUZZY_CASES,
        "skipped": 0,
        "blocked": 0,
        "command_or_method": "python3 scripts/run_retrieval_scale.py",
        "failures": [],
        "evidence_paths": ["scripts/run_retrieval_scale.py"],
    }
    try:
        with run_g4.disposable_postgres() as owner_url:
            seed_timings = seed_reference_data(owner_url)
            cluster_targets = seed_confusable_clusters(owner_url)
            runtime_url = owner_url.replace("user=postgres", "user=openclaw_runtime")
            benchmark = run_benchmark(runtime_url, cluster_targets)
            plans = explain_plans(runtime_url, cluster_query_name(50))
            resolved = benchmark["resolved_cases"]
            report.update(
                {
                    # `result` stays governed by the four frozen thresholds; the
                    # counters report what the run measured. They can disagree
                    # on purpose: the thresholds admit up to ten fuzzy misses,
                    # so a legitimately passing run can read 150/160, which the
                    # old `report["cases"] if <bool> else 0` could never say.
                    "result": "PASS" if benchmark["thresholds_met"] else "FAIL",
                    "passed": resolved,
                    "failed": report["cases"] - resolved,
                    "seed_duration_seconds": {
                        key: round(value, 3) for key, value in seed_timings.items()
                    },
                    "benchmark": benchmark,
                    "query_plans": plans,
                }
            )
            if not benchmark["thresholds_met"]:
                report["failures"].append("one or more frozen retrieval thresholds missed")
    except Exception as exc:
        report.update({"result": "FAIL"})
        report["failures"].append(f"{type(exc).__name__}: {exc}")
    report["duration_ms"] = round((time.perf_counter() - started) * 1000)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report.get("result") == "PASS" else 1


if __name__ == "__main__":
    # Never inherit a configured application database into this destructive
    # synthetic-load process; the disposable cluster is created internally.
    os.environ.pop("DATABASE_URL", None)
    raise SystemExit(main())
