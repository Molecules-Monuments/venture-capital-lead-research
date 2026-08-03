# SPDX-License-Identifier: 0BSD
import json
import os
import shutil
import subprocess
import unittest
import uuid


DATABASE_URL = os.environ.get("DATABASE_URL", "")
PSQL = shutil.which("psql")
MIGRATION_CHECKSUMS = json.loads(os.environ.get("G4_MIGRATION_CHECKSUMS", "{}"))


class DatabaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DATABASE_URL:
            raise AssertionError("DATABASE_URL is required; database tests may not skip")
        if not PSQL:
            raise AssertionError("psql is required; database tests may not skip")
        cls.prefix = "g4_" + uuid.uuid4().hex[:12]
        cls.company_id = int(cls.query("INSERT INTO companies (name) VALUES ('G4 adversarial company') RETURNING id"))
        cls.other_company_id = int(cls.query("INSERT INTO companies (name) VALUES ('G4 other company') RETURNING id"))
        cls.lead_one = int(cls.query(
            "INSERT INTO leads (company_id, lead_title, origin_group, idempotency_key) "
            f"VALUES ({cls.company_id}, 'G4 lead one', 'inbound', '{cls.prefix}_lead_1') RETURNING id"
        ))
        cls.lead_two = int(cls.query(
            "INSERT INTO leads (company_id, lead_title, origin_group, idempotency_key) "
            f"VALUES ({cls.company_id}, 'G4 lead two', 'inbound', '{cls.prefix}_lead_2') RETURNING id"
        ))
        cls.other_lead = int(cls.query(
            "INSERT INTO leads (company_id, lead_title, origin_group, idempotency_key) "
            f"VALUES ({cls.other_company_id}, 'G4 other lead', 'inbound', '{cls.prefix}_lead_other') RETURNING id"
        ))
        cls.source_id = int(cls.query(
            "INSERT INTO sources (source_kind, title, canonical_uri, trust_level) "
            f"VALUES ('primary_document', 'G4 source', 'https://g4.invalid/{cls.prefix}', 'untrusted_upload') RETURNING id"
        ))
        cls.artifact_hash = ("a" * 48) + uuid.uuid4().hex[:16]
        cls.artifact_id = int(cls.query(
            "INSERT INTO evidence_artifacts "
            "(sha256, artifact_type, storage_tier, trust_boundary, storage_uri, mime_type, size_bytes) "
            f"VALUES ('{cls.artifact_hash}', 'document', 'workspace_file', 'untrusted_upload', "
            f"'/inbox/{cls.prefix}.pdf', 'application/pdf', 10) RETURNING id"
        ))

    @classmethod
    def query(cls, sql, expect_ok=True):
        proc = subprocess.run(
            [str(PSQL), "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", DATABASE_URL, "-c", sql],
            text=True,
            capture_output=True,
            timeout=30,
        )
        if expect_ok and proc.returncode:
            raise AssertionError(f"SQL failed: {sql}\nstdout={proc.stdout}\nstderr={proc.stderr}")
        if not expect_ok and proc.returncode == 0:
            raise AssertionError(f"SQL unexpectedly succeeded: {sql}\nstdout={proc.stdout}")
        return proc.stdout.strip()

    def test_artifact_identity_is_global_but_provenance_is_many_to_many(self):
        self.query(
            "INSERT INTO lead_artifacts (lead_id, artifact_id, source_id, association_role, source_locator) "
            f"VALUES ({self.lead_one}, {self.artifact_id}, {self.source_id}, 'submission', 'page 1')"
        )
        self.query(
            "INSERT INTO lead_artifacts (lead_id, artifact_id, source_id, association_role, source_locator) "
            f"VALUES ({self.lead_two}, {self.artifact_id}, {self.source_id}, 'submission', 'page 1')"
        )
        count = self.query(f"SELECT count(*) FROM lead_artifacts WHERE artifact_id = {self.artifact_id}")
        self.assertEqual(count, "2")
        self.query(
            "INSERT INTO lead_artifacts (lead_id, artifact_id, source_id, association_role) "
            f"VALUES ({self.lead_one}, {self.artifact_id}, {self.source_id}, 'submission')",
            expect_ok=False,
        )
        self.query(
            "INSERT INTO evidence_artifacts "
            "(sha256, artifact_type, storage_tier, trust_boundary, storage_uri) "
            f"VALUES ('{self.artifact_hash}', 'document', 'workspace_file', 'untrusted_upload', '/inbox/duplicate.pdf')",
            expect_ok=False,
        )

    def test_workflow_transition_version_idempotency_and_sticky_cancel(self):
        run_id = f"{self.prefix}_run"
        workflow_id = "g4.workflow"
        idem = f"{self.prefix}_workflow_idem"
        self.query(
            "INSERT INTO workflow_runs (run_id, workflow_id, lead_id, company_id, idempotency_key, status) "
            f"VALUES ('{run_id}', '{workflow_id}', {self.lead_one}, {self.company_id}, '{idem}', 'queued')"
        )
        transitioned = self.query(
            f"SELECT status || '|' || record_version || '|' || flow_revision "
            f"FROM transition_workflow_run('{run_id}', 1, 'running', 7, 'g4')"
        )
        self.assertEqual(transitioned, "running|2|7")
        self.query(
            f"SELECT * FROM transition_workflow_run('{run_id}', 1, 'succeeded', 8, 'g4')",
            expect_ok=False,
        )
        cancelled = self.query(
            f"SELECT status || '|' || record_version || '|' || (cancel_requested_at IS NOT NULL)::text "
            f"FROM transition_workflow_run('{run_id}', 2, 'cancelled', 8, 'g4')"
        )
        self.assertEqual(cancelled, "cancelled|3|true")
        self.query(
            f"SELECT * FROM transition_workflow_run('{run_id}', 3, 'running', 9, 'g4')",
            expect_ok=False,
        )
        self.query(
            "INSERT INTO workflow_runs (run_id, workflow_id, lead_id, company_id, idempotency_key) "
            f"VALUES ('{run_id}_duplicate', '{workflow_id}', {self.lead_one}, {self.company_id}, '{idem}')",
            expect_ok=False,
        )

    def test_workflow_scope_exempts_reviewed_leadless_workflows_and_no_others(self):
        replaced = self.query(
            "SELECT count(*) FILTER (WHERE conname = 'workflow_runs_scope_check') || '|' || "
            "count(*) FILTER (WHERE conname = 'workflow_runs_check') "
            "FROM pg_constraint WHERE conrelid = 'public.workflow_runs'::regclass"
        )
        self.assertEqual(replaced, "1|0")
        for workflow_id in ("preference-observe", "preference-forget", "document-ingest"):
            status = self.query(
                "INSERT INTO workflow_runs (run_id, workflow_id, idempotency_key) "
                f"VALUES ('{self.prefix}_{workflow_id}', '{workflow_id}', '{self.prefix}_{workflow_id}') "
                "RETURNING status"
            )
            self.assertEqual(status, "queued")
        self.query(
            "INSERT INTO workflow_runs (run_id, workflow_id, idempotency_key) "
            f"VALUES ('{self.prefix}_nonexempt', 'g4.nonexempt-workflow', '{self.prefix}_nonexempt')",
            expect_ok=False,
        )

    def test_domain_history_is_append_only_and_lineage_fails_closed(self):
        self.query(
            "INSERT INTO workflow_runs (run_id, workflow_id, lead_id, company_id, idempotency_key) "
            f"VALUES ('{self.prefix}_bad_lineage', 'g4.bad.lineage', {self.lead_one}, "
            f"{self.other_company_id}, '{self.prefix}_bad_lineage')",
            expect_ok=False,
        )
        fact_id = int(self.query(
            "INSERT INTO facts "
            "(company_id,lead_id,fact_type,definition,value_kind,value_text,original_value,fact_status,confidence,created_by) "
            f"VALUES ({self.company_id},{self.lead_one},'g4_append','append only','text','original','original',"
            "'verified_fact',0.9,'g4') RETURNING id"
        ))
        self.query(
            f"INSERT INTO fact_sources (fact_id,source_id,evidence_role) VALUES ({fact_id},{self.source_id},'primary')"
        )
        self.query(f"UPDATE facts SET value_text='tampered' WHERE id={fact_id}", expect_ok=False)
        self.query(f"DELETE FROM facts WHERE id={fact_id}", expect_ok=False)
        self.query(
            f"UPDATE fact_sources SET evidence_role='supporting' WHERE fact_id={fact_id} AND source_id={self.source_id}",
            expect_ok=False,
        )
        self.query(
            "INSERT INTO facts "
            "(company_id,lead_id,fact_type,definition,value_kind,value_text,original_value,fact_status,confidence,created_by) "
            f"VALUES ({self.other_company_id},{self.lead_one},'g4_bad','bad lineage','text','bad','bad',"
            "'verified_fact',0.9,'g4')",
            expect_ok=False,
        )

    def insert_pending_approval(self, suffix, *, expired=False):
        token = (suffix[0] * 64) if suffix[0] in "abcdef" else ("b" * 64)
        scope_hash = "c" * 64
        payload_hash = "d" * 64
        times = (
            "clock_timestamp() - interval '3 hours', clock_timestamp() - interval '1 hour'"
            if expired else
            "clock_timestamp() - interval '2 minutes', clock_timestamp() + interval '10 minutes'"
        )
        approval_id = self.query(
            "INSERT INTO approvals "
            "(request_id, idempotency_key, token_hash, scope_hash, scope, action_preview, action_type, "
            "target_system, lead_id, payload_hash, status, requested_by, requested_at, expires_at) VALUES "
            f"('{self.prefix}_{suffix}_request', '{self.prefix}_{suffix}_idem', '{token}', '{scope_hash}', "
            f"'{{\"lead_id\":{self.lead_one}}}'::jsonb, '{{\"operation\":\"write\"}}'::jsonb, "
            f"'crm.write', 'crm-test', {self.lead_one}, '{payload_hash}', 'pending', 'g4', {times}) RETURNING id"
        )
        return int(approval_id), token, scope_hash, payload_hash

    def test_approval_scope_expiry_and_replay_are_fail_closed(self):
        approval_id, token, scope_hash, payload_hash = self.insert_pending_approval("b_live")
        decision = self.query(
            f"SELECT status FROM decide_approval('{self.prefix}_b_live_request', 'approved', "
            "'operator-g4', 'channel-g4', 'g4 approval', 'g4')"
        )
        self.assertEqual(decision, "approved")
        self.query(
            f"SELECT * FROM consume_approval('{token}', '{'e' * 64}', 'crm.write', 'crm-test', "
            f"'{payload_hash}', '{self.prefix}_wrong_scope_tx', 'g4')",
            expect_ok=False,
        )
        consumed = self.query(
            f"SELECT status || '|' || (consumed_at IS NOT NULL)::text FROM consume_approval("
            f"'{token}', '{scope_hash}', 'crm.write', 'crm-test', '{payload_hash}', '{self.prefix}_tx', 'g4')"
        )
        self.assertEqual(consumed, "consumed|true")
        self.query(
            f"SELECT * FROM consume_approval('{token}', '{scope_hash}', 'crm.write', 'crm-test', "
            f"'{payload_hash}', '{self.prefix}_replay_tx', 'g4')",
            expect_ok=False,
        )
        status = self.query(f"SELECT status FROM approvals WHERE id = {approval_id}")
        self.assertEqual(status, "consumed")
        _, expired_token, expired_scope, expired_payload = self.insert_pending_approval("a_expired", expired=True)
        self.query(
            f"SELECT * FROM decide_approval('{self.prefix}_a_expired_request', 'approved', "
            "'operator-g4', 'channel-g4', 'expired approval', 'g4')",
            expect_ok=False,
        )
        self.query(
            f"SELECT * FROM consume_approval('{expired_token}', '{expired_scope}', 'crm.write', 'crm-test', "
            f"'{expired_payload}', '{self.prefix}_expired_tx', 'g4')",
            expect_ok=False,
        )

    def test_notification_dedupe_retry_attempt_history_and_claim_replay(self):
        idem = f"{self.prefix}_notification"
        dedupe = f"{self.prefix}_dedupe"
        outbox_id = int(self.query(
            "INSERT INTO notification_outbox "
            "(idempotency_key, dedupe_key, provider, provider_account_id, destination_id, lead_id, "
            "severity, status, subject, body_hash, payload, policy_version, deliver_after) VALUES "
            f"('{idem}', '{dedupe}', 'slack', 'account-g4', 'channel-g4', {self.lead_one}, 'normal', "
            f"'queued', 'G4 notice', '{'e' * 64}', '{{}}'::jsonb, 'g4', clock_timestamp() - interval '1 second') RETURNING id"
        ))
        self.query(
            "INSERT INTO notification_outbox "
            "(idempotency_key, dedupe_key, provider, provider_account_id, destination_id, severity, "
            "status, subject, body_hash, policy_version) VALUES "
            f"('{idem}_other', '{dedupe}', 'slack', 'account-g4', 'channel-g4', 'normal', 'queued', "
            f"'duplicate', '{'f' * 64}', 'g4')",
            expect_ok=False,
        )
        claimed = self.query(
            "SELECT id || '|' || status || '|' || claim_id || '|' || attempt_count "
            "FROM claim_notification('g4-worker', 60)"
        ).split("|")
        self.assertEqual(int(claimed[0]), outbox_id)
        self.assertEqual(claimed[1], "dispatching")
        first_claim = claimed[2]
        self.assertEqual(claimed[3], "1")
        retried = self.query(
            f"SELECT status || '|' || attempt_count || '|' || (next_attempt_at IS NOT NULL)::text "
            f"FROM finish_notification_attempt({outbox_id}, '{first_claim}', 'retryable_failure', "
            f"'req-1', '503', NULL, 'provider_unavailable', 'retry', 0)"
        )
        self.assertEqual(retried, "retry|1|true")
        second = self.query(
            "SELECT id || '|' || claim_id || '|' || attempt_count FROM claim_notification('g4-worker', 60)"
        ).split("|")
        self.assertEqual(int(second[0]), outbox_id)
        second_claim = second[1]
        self.assertEqual(second[2], "2")
        self.query(
            f"SELECT * FROM finish_notification_attempt({outbox_id}, '{first_claim}', 'succeeded', "
            "'stale-request', '200', 'stale-message')",
            expect_ok=False,
        )
        sent = self.query(
            f"SELECT status || '|' || provider_message_id FROM finish_notification_attempt("
            f"{outbox_id}, '{second_claim}', 'succeeded', 'req-2', '200', 'provider-message-g4')"
        )
        self.assertEqual(sent, "sent|provider-message-g4")
        attempt_count = self.query(f"SELECT count(*) FROM notification_attempts WHERE outbox_id = {outbox_id}")
        self.assertEqual(attempt_count, "2")
        held_id = int(self.query(
            "INSERT INTO notification_outbox "
            "(idempotency_key, dedupe_key, provider, provider_account_id, destination_id, severity, status, "
            "subject, body_hash, payload, policy_version, deliver_after) VALUES "
            f"('{idem}_held', '{dedupe}_held', 'msteams', 'account-g4', 'channel-g4', 'normal', 'held', "
            f"'Held G4 notice', '{'a' * 64}', '{{}}'::jsonb, 'g4', clock_timestamp() - interval '1 second') RETURNING id"
        ))
        released = self.query(f"SELECT status FROM release_held_notification({held_id}, 'g4')")
        self.assertEqual(released, "queued")
        cancelled = self.query(f"SELECT status FROM cancel_notification({held_id}, 'g4')")
        self.assertEqual(cancelled, "cancelled")
        future_id = int(self.query(
            "INSERT INTO notification_outbox "
            "(idempotency_key, dedupe_key, provider, provider_account_id, destination_id, severity, status, "
            "subject, body_hash, payload, policy_version, deliver_after) VALUES "
            f"('{idem}_future', '{dedupe}_future', 'msteams', 'account-g4', 'channel-g4', 'normal', 'held', "
            f"'Future G4 notice', '{'b' * 64}', '{{}}'::jsonb, 'g4', clock_timestamp() + interval '1 hour') RETURNING id"
        ))
        self.query(f"SELECT status FROM release_held_notification({future_id}, 'g4')", expect_ok=False)
        self.assertEqual(self.query(f"SELECT status FROM cancel_notification({future_id}, 'g4')"), "cancelled")

    def test_audit_is_append_only_even_for_owner_and_runtime_is_least_privilege(self):
        audit_id = int(self.query(
            "INSERT INTO audit_events (event_type, actor_id, actor_type, entity_table, entity_id, details) "
            f"VALUES ('g4.audit', 'g4', 'service', 'leads', '{self.lead_one}', '{{}}'::jsonb) RETURNING id"
        ))
        self.query(f"UPDATE audit_events SET actor_id = 'tampered' WHERE id = {audit_id}", expect_ok=False)
        self.query(f"DELETE FROM audit_events WHERE id = {audit_id}", expect_ok=False)
        privileges = self.query(
            "SELECT "
            "has_schema_privilege('openclaw_runtime','public','CREATE')::text || '|' || "
            "has_database_privilege('openclaw_runtime',current_database(),'TEMP')::text || '|' || "
            "has_table_privilege('openclaw_runtime','audit_events','INSERT')::text || '|' || "
            "has_table_privilege('openclaw_runtime','audit_events','UPDATE')::text || '|' || "
            "has_table_privilege('openclaw_runtime','audit_events','DELETE')::text || '|' || "
            "has_table_privilege('openclaw_runtime','leads','DELETE')::text || '|' || "
            "has_table_privilege('openclaw_runtime','workflow_runs','UPDATE')::text || '|' || "
            "has_table_privilege('openclaw_runtime','approvals','UPDATE')::text || '|' || "
            "has_table_privilege('openclaw_runtime','notification_outbox','UPDATE')::text || '|' || "
            "has_table_privilege('openclaw_runtime','notification_attempts','UPDATE')::text || '|' || "
            "has_function_privilege('openclaw_runtime','transition_workflow_run(text,bigint,text,bigint,text,jsonb,text,text)','EXECUTE')::text || '|' || "
            "has_function_privilege('openclaw_runtime','request_workflow_cancel(text,bigint,text,text)','EXECUTE')::text || '|' || "
            "has_function_privilege('openclaw_runtime','decide_approval(text,text,text,text,text,text)','EXECUTE')::text || '|' || "
            "has_function_privilege('openclaw_runtime','consume_approval(text,text,text,text,text,text,text)','EXECUTE')::text || '|' || "
            "has_function_privilege('openclaw_runtime','claim_notification(text,integer)','EXECUTE')::text || '|' || "
            "has_function_privilege('openclaw_runtime','finish_notification_attempt(bigint,text,text,text,text,text,text,text,integer)','EXECUTE')::text || '|' || "
            "has_function_privilege('openclaw_runtime','release_held_notification(bigint,text)','EXECUTE')::text || '|' || "
            "has_function_privilege('openclaw_runtime','cancel_notification(bigint,text)','EXECUTE')::text"
        )
        self.assertEqual(
            privileges,
            "false|false|true|false|false|false|false|false|false|false|true|true|true|true|true|true|true|true",
        )
        self.query("SET ROLE openclaw_runtime; CREATE TABLE g4_forbidden_ddl (id integer)", expect_ok=False)

    def test_double_applied_migrations_leave_one_version_and_no_equivalent_unique_indexes(self):
        self.assertTrue(MIGRATION_CHECKSUMS, "validator must supply expected migration checksums")
        for version, expected in sorted(MIGRATION_CHECKSUMS.items()):
            with self.subTest(version=version):
                self.assertEqual(self.query(f"SELECT count(*) FROM schema_migrations WHERE version = '{version}'"), "1")
                self.assertEqual(self.query(f"SELECT checksum_sha256 FROM schema_migrations WHERE version = '{version}'"), expected)
        checksum_column = self.query(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='schema_migrations' AND column_name='checksum_sha256'"
        )
        self.assertEqual(checksum_column, "1", "schema_migrations must record an externally computed checksum")
        self.assertEqual(
            self.query("SELECT count(*) FROM schema_migrations WHERE checksum_sha256 IS NULL OR btrim(checksum_sha256) = ''"),
            "0",
        )
        duplicate_unique = self.query(
            "WITH normalized AS ("
            " SELECT schemaname, tablename, regexp_replace(indexdef, "
            " '^CREATE UNIQUE INDEX [^ ]+ ', 'CREATE UNIQUE INDEX ') AS definition"
            " FROM pg_indexes WHERE schemaname='public' AND indexdef LIKE 'CREATE UNIQUE INDEX%'"
            ") SELECT count(*) FROM ("
            " SELECT schemaname, tablename, definition FROM normalized "
            " GROUP BY schemaname, tablename, definition HAVING count(*) > 1"
            ") duplicate_definitions"
        )
        self.assertEqual(duplicate_unique, "0", "equivalent duplicate unique indexes remain after migrations")


if __name__ == "__main__":
    unittest.main(verbosity=2)
