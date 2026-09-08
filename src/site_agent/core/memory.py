"""memory.py — per-instance sqlite state for the agent.

One database per site instance, stored in the instance's data/ directory.
Schema is versioned via PRAGMA user_version; migrations run automatically on
open so upgrading the package never erases what she learned.
"""

from __future__ import annotations

import datetime
from functools import wraps
import json
import re
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from .contracts import (
    ActionState,
    ApprovalRequest,
    ApprovalStatus,
    Artifact,
    ContractError,
    OwnerAction,
    ProviderReceipt,
    validate_action_transition,
    validate_approval_transition,
    safe_payload,
    safe_provider_message,
)
from .design_contracts import (
    DesignContextSnapshot,
    DesignOperationKind,
    DesignRunStatus,
    SiteIntake,
    validate_design_operation_kind,
    validate_design_run_transition,
    canonical_hash,
    canonical_json,
    safe_relative_path,
    validate_design_phase,
    validate_design_phase_status,
)
from .design_intake_contracts import (
    DESIGN_INTAKE_SCHEMA_VERSION,
    DesignIntakeDraft,
    IntakeAssetBinding,
    IntakeSessionState,
)
from .customer_context_contracts import (
    AcceptanceManifest,
    CustomerContextSnapshot,
)
from .media_contracts import MediaAnalysisStatus, MediaAsset
from .incubation_contracts import (
    CustomerAdaGenesis,
    IncubationActivity,
    IncubationActivityCategory,
    IncubationDeduction,
    IncubationInsight,
    InfusionRun,
    InfusionRunStatus,
    ProvisioningBundle,
    ResearchFinding,
    ResearchJob,
    ResearchRequest,
    ResearchSource,
)

SCHEMA_VERSION = 37

MIGRATIONS: dict[int, list[str]] = {
    1: [
        """CREATE TABLE IF NOT EXISTS kv (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_observations_ts ON observations (ts)""",
        """CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            kind TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
        )""",
        """CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'article',
            title TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            meta TEXT NOT NULL DEFAULT '{}'
        )""",
        """CREATE TABLE IF NOT EXISTS metrics_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            source TEXT NOT NULL,
            data TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS llm_costs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL
        )""",
    ],
    2: [
        "ALTER TABLE observations ADD COLUMN meta TEXT NOT NULL DEFAULT '{}'",
    ],
    3: [
        """CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_ts TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT 'New conversation'
        )""",
        """CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id),
            ts TEXT NOT NULL,
            role TEXT NOT NULL,
            text TEXT NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON chat_messages (conversation_id, id)""",
        """CREATE TABLE IF NOT EXISTS publishes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL DEFAULT '',
            commit_sha TEXT NOT NULL DEFAULT '',
            draft_id INTEGER
        )""",
    ],
    4: [
        """CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            ts REAL NOT NULL DEFAULT 0,
            embedding TEXT NOT NULL DEFAULT '[]'
        )""",
        """CREATE INDEX IF NOT EXISTS idx_memories_kind_ts ON memories (kind, ts)""",
    ],
    5: [
        "ALTER TABLE publishes ADD COLUMN reverted_ts TEXT",
    ],
    6: [
        """CREATE TABLE IF NOT EXISTS chat_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id),
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            steps TEXT NOT NULL DEFAULT '[]',
            result TEXT,
            error TEXT,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            claimed_by TEXT,
            heartbeat_ts REAL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_chat_jobs_status ON chat_jobs (status, id)""",
    ],
    7: [
        "ALTER TABLE chat_jobs ADD COLUMN message_id INTEGER REFERENCES chat_messages(id)",
    ],
    8: [
        "ALTER TABLE publishes ADD COLUMN parent_sha TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE publishes ADD COLUMN actor TEXT NOT NULL DEFAULT 'ada'",
        "ALTER TABLE publishes ADD COLUMN version_type TEXT NOT NULL DEFAULT 'edit'",
    ],
    9: [
        "ALTER TABLE conversations ADD COLUMN archived_ts TEXT",
    ],
    10: [
        """CREATE TABLE IF NOT EXISTS artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision INTEGER NOT NULL DEFAULT 1,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            renderer TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            source_action_id INTEGER,
            content_hash TEXT NOT NULL,
            preview_data TEXT NOT NULL DEFAULT '{}',
            created_ts TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS owner_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            capability_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            action_label TEXT NOT NULL,
            priority TEXT NOT NULL,
            requirement TEXT NOT NULL,
            state TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            dedupe_key TEXT NOT NULL,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            snoozed_until TEXT,
            conversation_id INTEGER,
            artifact_id INTEGER,
            approval_id INTEGER,
            draft_id INTEGER,
            payload_version INTEGER NOT NULL DEFAULT 1,
            payload TEXT NOT NULL DEFAULT '{}'
        )""",
        """CREATE TABLE IF NOT EXISTS approval_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_id INTEGER NOT NULL,
            artifact_hash TEXT NOT NULL,
            effect_class TEXT NOT NULL,
            owner_action_label TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            action_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            decided_ts TEXT,
            owner_feedback TEXT,
            execution_job_id INTEGER,
            provider_receipt_id INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS provider_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider_id TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            action_id INTEGER,
            approval_id INTEGER,
            idempotency_key TEXT NOT NULL,
            external_object_id TEXT,
            external_url TEXT,
            status TEXT NOT NULL,
            safe_message TEXT NOT NULL DEFAULT '',
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_owner_actions_state_priority ON owner_actions (state, priority, id)",
        "CREATE INDEX IF NOT EXISTS idx_owner_actions_refs ON owner_actions (conversation_id, artifact_id, approval_id, draft_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_owner_actions_active_dedupe ON owner_actions (dedupe_key) WHERE state NOT IN ('completed', 'dismissed', 'stale')",
        "CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests (status, id)",
        "CREATE INDEX IF NOT EXISTS idx_approval_requests_refs ON approval_requests (artifact_id, action_id, provider_id)",
        "CREATE INDEX IF NOT EXISTS idx_provider_receipts_refs ON provider_receipts (provider_id, approval_id, action_id)",
    ],
    11: [
        "ALTER TABLE conversations ADD COLUMN deleted_ts TEXT",
        "CREATE INDEX IF NOT EXISTS idx_conversations_visibility ON conversations (deleted_ts, archived_ts, id)",
    ],
    12: [
        "ALTER TABLE owner_actions ADD COLUMN job_id INTEGER",
        "CREATE INDEX IF NOT EXISTS idx_owner_actions_job ON owner_actions (job_id, state, id)",
    ],
    13: [
        """UPDATE approval_requests
           SET provider_receipt_id = (
               SELECT MAX(newer.id)
               FROM provider_receipts AS newer
               WHERE newer.idempotency_key = (
                   SELECT older.idempotency_key
                   FROM provider_receipts AS older
                   WHERE older.id = approval_requests.provider_receipt_id
               )
           )
           WHERE provider_receipt_id IS NOT NULL
             AND provider_receipt_id NOT IN (
                 SELECT MAX(id) FROM provider_receipts GROUP BY idempotency_key
             )""",
        "DELETE FROM provider_receipts WHERE id NOT IN (SELECT MAX(id) FROM provider_receipts GROUP BY idempotency_key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_receipts_idempotency ON provider_receipts (idempotency_key)",
    ],
    14: [
        """CREATE TABLE IF NOT EXISTS social_preparations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_hash TEXT NOT NULL,
            request_json TEXT NOT NULL DEFAULT '{}',
            provider_operation_id TEXT,
            provider_post_id TEXT,
            artifact_id INTEGER,
            approval_id INTEGER,
            action_id INTEGER,
            job_id INTEGER,
            status TEXT NOT NULL DEFAULT 'submitting',
            error TEXT,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_social_preparations_status ON social_preparations (status, id)",
    ],
    15: [
        """CREATE TABLE IF NOT EXISTS seo_research_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period TEXT NOT NULL,
            package_version TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            brief TEXT NOT NULL DEFAULT '{}',
            report_id TEXT,
            status TEXT NOT NULL DEFAULT 'preparing',
            error TEXT,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            requested_ts TEXT,
            completed_ts TEXT,
            UNIQUE(period, package_version)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_seo_research_requests_status ON seo_research_requests (status, id)",
        """CREATE TABLE IF NOT EXISTS seo_seed_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seed TEXT NOT NULL,
            language TEXT NOT NULL,
            market TEXT NOT NULL,
            cluster TEXT NOT NULL DEFAULT '',
            objective TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'active',
            first_researched_ts TEXT,
            last_researched_ts TEXT,
            research_count INTEGER NOT NULL DEFAULT 0,
            latest_report_id TEXT,
            usefulness TEXT,
            freshness TEXT NOT NULL DEFAULT 'new',
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            UNIQUE(seed, language, market)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_seo_seed_registry_market ON seo_seed_registry (language, market, freshness, priority)",
        """CREATE TABLE IF NOT EXISTS seo_seed_selections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL REFERENCES seo_research_requests(id),
            seed_id INTEGER NOT NULL REFERENCES seo_seed_registry(id),
            ordinal INTEGER NOT NULL,
            slot_type TEXT NOT NULL,
            rationale TEXT NOT NULL DEFAULT '',
            UNIQUE(request_id, ordinal),
            UNIQUE(request_id, seed_id)
        )""",
        """CREATE TABLE IF NOT EXISTS strategy_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id TEXT NOT NULL UNIQUE,
            period TEXT NOT NULL,
            report_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            summary TEXT NOT NULL DEFAULT '',
            report_json TEXT NOT NULL DEFAULT '{}',
            report_draft_id INTEGER,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_strategy_cycles_period ON strategy_cycles (period, id)",
        """CREATE TABLE IF NOT EXISTS strategy_initiatives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id INTEGER NOT NULL REFERENCES strategy_cycles(id),
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            hypothesis TEXT NOT NULL DEFAULT '',
            rationale TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            expected_json TEXT NOT NULL DEFAULT '{}',
            language TEXT,
            market TEXT,
            priority TEXT NOT NULL DEFAULT 'normal',
            state TEXT NOT NULL DEFAULT 'proposed',
            review_30_ts TEXT,
            review_90_ts TEXT,
            review_180_ts TEXT,
            owner_action_id INTEGER,
            artifact_id INTEGER,
            approval_id INTEGER,
            draft_id INTEGER,
            receipt_id INTEGER,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_strategy_initiatives_cycle_state ON strategy_initiatives (cycle_id, state, priority, id)",
        """CREATE TABLE IF NOT EXISTS strategy_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            initiative_id INTEGER NOT NULL REFERENCES strategy_initiatives(id),
            decision TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            owner_feedback TEXT NOT NULL DEFAULT '',
            created_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_strategy_decisions_initiative ON strategy_decisions (initiative_id, id)",
        """CREATE TABLE IF NOT EXISTS strategy_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            initiative_id INTEGER NOT NULL REFERENCES strategy_initiatives(id),
            horizon_days INTEGER NOT NULL,
            baseline_json TEXT NOT NULL DEFAULT '{}',
            observed_json TEXT NOT NULL DEFAULT '{}',
            assessment TEXT NOT NULL,
            confidence TEXT NOT NULL DEFAULT 'low',
            notes TEXT NOT NULL DEFAULT '',
            measured_ts TEXT NOT NULL,
            UNIQUE(initiative_id, horizon_days)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_strategy_outcomes_due ON strategy_outcomes (horizon_days, measured_ts)",
    ],
    16: [
        "ALTER TABLE strategy_cycles ADD COLUMN report_artifact_id INTEGER",
        "ALTER TABLE strategy_initiatives ADD COLUMN parent_initiative_id INTEGER",
    ],
    17: [
        """CREATE TABLE IF NOT EXISTS seo_site_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'preparing',
            evidence_hash TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            summary TEXT NOT NULL DEFAULT '',
            artifact_id INTEGER,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            completed_ts TEXT,
            error TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_seo_site_reports_status ON seo_site_reports (status, period)",
        """CREATE TABLE IF NOT EXISTS article_ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_key TEXT NOT NULL UNIQUE,
            idea_hash TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'selected',
            idea_json TEXT NOT NULL DEFAULT '{}',
            research_run_id TEXT,
            research_result_hash TEXT,
            provider_task_id TEXT,
            research_cost_micros INTEGER,
            research_note_json TEXT,
            draft_id INTEGER,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            researched_ts TEXT,
            drafted_ts TEXT,
            error TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_article_ideas_status ON article_ideas (status, id)",
        "CREATE INDEX IF NOT EXISTS idx_article_ideas_created ON article_ideas (created_ts, id)",
    ],
    18: [
        "ALTER TABLE article_ideas ADD COLUMN research_result_json TEXT NOT NULL DEFAULT '[]'",
        "ALTER TABLE publishes ADD COLUMN commit_message TEXT NOT NULL DEFAULT ''",
    ],
    19: [
        "ALTER TABLE article_ideas ADD COLUMN serp_run_id TEXT",
    ],
    20: [
        """CREATE TABLE IF NOT EXISTS rejected_article_ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_key TEXT NOT NULL,
            raw TEXT NOT NULL DEFAULT '',
            parsed_json TEXT NOT NULL DEFAULT '{}',
            reason TEXT NOT NULL DEFAULT '',
            created_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_rejected_article_ideas_cycle ON rejected_article_ideas (cycle_key, id)",
    ],
    21: [
        """CREATE TABLE IF NOT EXISTS media_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            status TEXT NOT NULL,
            media_kind TEXT NOT NULL,
            source_kind TEXT NOT NULL DEFAULT 'owner_upload',
            original_name TEXT NOT NULL,
            content_type TEXT NOT NULL,
            original_size INTEGER NOT NULL,
            original_sha256 TEXT NOT NULL UNIQUE,
            storage_id TEXT NOT NULL UNIQUE,
            original_key TEXT NOT NULL,
            normalized_key TEXT NOT NULL DEFAULT '',
            thumbnail_key TEXT NOT NULL DEFAULT '',
            page_keys_json TEXT NOT NULL DEFAULT '[]',
            width INTEGER,
            height INTEGER,
            page_count INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            ocr_text TEXT NOT NULL DEFAULT '',
            proposed_knowledge TEXT NOT NULL DEFAULT '',
            analysis_json TEXT NOT NULL DEFAULT '{}',
            provider_id TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            analysis_version INTEGER NOT NULL DEFAULT 1,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            archived_ts TEXT,
            protected_ts TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_media_assets_status_id ON media_assets (status, id)",
        "CREATE INDEX IF NOT EXISTS idx_media_assets_created ON media_assets (created_ts)",
        "CREATE INDEX IF NOT EXISTS idx_media_assets_archived ON media_assets (archived_ts)",
        """CREATE TABLE IF NOT EXISTS business_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL REFERENCES media_assets(id),
            revision INTEGER NOT NULL DEFAULT 1,
            body TEXT NOT NULL,
            status TEXT NOT NULL,
            artifact_id INTEGER REFERENCES artifacts(id),
            approval_id INTEGER REFERENCES approval_requests(id),
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            decided_ts TEXT,
            UNIQUE(asset_id, revision)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_business_knowledge_status ON business_knowledge (status, updated_ts)",
        "CREATE INDEX IF NOT EXISTS idx_business_knowledge_asset ON business_knowledge (asset_id)",
        "ALTER TABLE chat_messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]'",
    ],
    22: [
        """CREATE TABLE IF NOT EXISTS design_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            intake_json TEXT NOT NULL DEFAULT '{}',
            intake_hash TEXT NOT NULL DEFAULT '',
            base_sha TEXT NOT NULL DEFAULT '',
            candidate_sha TEXT NOT NULL DEFAULT '',
            candidate_ref TEXT NOT NULL DEFAULT '',
            publishable INTEGER NOT NULL DEFAULT 0 CHECK (publishable IN (0, 1)),
            design_manifest_json TEXT NOT NULL DEFAULT '{}',
            design_manifest_hash TEXT NOT NULL DEFAULT '',
            quality_report_json TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            draft_id INTEGER,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS design_run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES design_runs(run_id) ON DELETE CASCADE,
            stage TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_design_runs_status ON design_runs (status, id)",
        "CREATE INDEX IF NOT EXISTS idx_design_runs_mode ON design_runs (mode, id)",
        "CREATE INDEX IF NOT EXISTS idx_design_run_events_run ON design_run_events (run_id, id)",
    ],
    23: [
        "ALTER TABLE design_runs ADD COLUMN quality_report_hash TEXT NOT NULL DEFAULT ''",
    ],
    24: [
        "ALTER TABLE design_runs ADD COLUMN design_manifest_path TEXT NOT NULL DEFAULT ''",
    ],
    25: [
        "ALTER TABLE design_runs ADD COLUMN planning_json TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE design_runs ADD COLUMN planning_hash TEXT NOT NULL DEFAULT ''",
    ],
    26: [
        "ALTER TABLE design_runs ADD COLUMN context_snapshot_json TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE design_runs ADD COLUMN context_snapshot_hash TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE design_runs ADD COLUMN owner_request TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE design_runs ADD COLUMN conversation_id INTEGER",
        "ALTER TABLE design_runs ADD COLUMN source_message_id INTEGER",
        "ALTER TABLE design_runs ADD COLUMN chat_job_id INTEGER",
    ],
    27: [
        "ALTER TABLE design_runs ADD COLUMN parent_run_id TEXT REFERENCES design_runs(run_id)",
        "ALTER TABLE design_runs ADD COLUMN operation_kind TEXT NOT NULL DEFAULT 'initial_build'",
        "ALTER TABLE design_runs ADD COLUMN source_candidate_sha TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE design_runs ADD COLUMN opencode_session_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE design_runs ADD COLUMN transcript_path TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE design_runs ADD COLUMN transcript_artifact_id INTEGER REFERENCES artifacts(id)",
        "ALTER TABLE design_runs ADD COLUMN build_artifact_id INTEGER REFERENCES artifacts(id)",
        "ALTER TABLE design_runs ADD COLUMN screenshot_artifact_id INTEGER REFERENCES artifacts(id)",
        "ALTER TABLE design_runs ADD COLUMN visual_critique_hash TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE design_runs ADD COLUMN provider_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE design_runs ADD COLUMN model_id TEXT NOT NULL DEFAULT ''",
        "CREATE INDEX IF NOT EXISTS idx_design_runs_parent ON design_runs (parent_run_id, id)",
    ],
    28: [
        "ALTER TABLE design_runs ADD COLUMN transcript_hash TEXT NOT NULL DEFAULT ''",
    ],
    29: [
        "ALTER TABLE chat_jobs ADD COLUMN operation_kind TEXT NOT NULL DEFAULT 'chat'",
        "ALTER TABLE chat_jobs ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE chat_jobs ADD COLUMN intake_session_id TEXT",
        "CREATE INDEX IF NOT EXISTS idx_chat_jobs_operation ON chat_jobs (operation_kind, status, id)",
        """CREATE TABLE IF NOT EXISTS design_intake_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL UNIQUE,
            conversation_id INTEGER,
            status TEXT NOT NULL DEFAULT 'collecting',
            revision INTEGER NOT NULL DEFAULT 0,
            draft_json TEXT NOT NULL DEFAULT '{}',
            draft_hash TEXT NOT NULL DEFAULT '',
            confirmed_revision INTEGER,
            confirmed_hash TEXT NOT NULL DEFAULT '',
            confirmed_ts TEXT,
            design_run_id TEXT,
            build_started_ts TEXT,
            build_error TEXT NOT NULL DEFAULT '',
            latest_message_id INTEGER,
            latest_advice_job_id INTEGER,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT ''
        )""",
        """CREATE TABLE IF NOT EXISTS design_intake_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES design_intake_sessions(session_id) ON DELETE CASCADE,
            revision INTEGER NOT NULL,
            draft_json TEXT NOT NULL,
            draft_hash TEXT NOT NULL,
            source_kind TEXT NOT NULL DEFAULT 'owner_message',
            source_message_id INTEGER,
            created_ts TEXT NOT NULL,
            UNIQUE(session_id, revision)
        )""",
        """CREATE TABLE IF NOT EXISTS design_intake_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES design_intake_sessions(session_id) ON DELETE CASCADE,
            asset_id INTEGER NOT NULL REFERENCES media_assets(id),
            position INTEGER NOT NULL,
            usage TEXT NOT NULL DEFAULT 'undecided',
            reference_aspects_json TEXT NOT NULL DEFAULT '[]',
            owner_note TEXT NOT NULL DEFAULT '',
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            UNIQUE(session_id, asset_id),
            UNIQUE(session_id, position)
        )""",
        """CREATE TABLE IF NOT EXISTS design_intake_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES design_intake_sessions(session_id) ON DELETE CASCADE,
            run_id TEXT,
            kind TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            created_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_design_intake_sessions_status ON design_intake_sessions (status, updated_ts)",
        "CREATE INDEX IF NOT EXISTS idx_design_intake_revisions_session ON design_intake_revisions (session_id, revision)",
        "CREATE INDEX IF NOT EXISTS idx_design_intake_assets_session ON design_intake_assets (session_id, position)",
        "CREATE INDEX IF NOT EXISTS idx_design_intake_feedback_session ON design_intake_feedback (session_id, id)",
    ],
    30: [
        "ALTER TABLE chat_jobs ADD COLUMN idempotency_key TEXT",
        "ALTER TABLE design_runs ADD COLUMN intake_session_id TEXT",
        "ALTER TABLE design_runs ADD COLUMN intake_revision_id INTEGER",
        "ALTER TABLE design_intake_revisions ADD COLUMN site_intake_json TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE design_intake_revisions ADD COLUMN site_intake_hash TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE design_intake_revisions ADD COLUMN summary_json TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE design_intake_revisions ADD COLUMN confirmation_message_id INTEGER",
        "UPDATE chat_jobs SET operation_kind = 'owner_chat' WHERE operation_kind = 'chat'",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_jobs_idempotency ON chat_jobs (operation_kind, intake_session_id, idempotency_key) WHERE idempotency_key IS NOT NULL",
        """CREATE TABLE IF NOT EXISTS design_intake_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES design_intake_sessions(session_id) ON DELETE CASCADE,
            operation TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json TEXT NOT NULL DEFAULT '{}',
            created_ts TEXT NOT NULL,
            UNIQUE(session_id, operation, idempotency_key)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_design_intake_operations_session ON design_intake_operations (session_id, operation, id)",
        """CREATE TABLE IF NOT EXISTS design_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES design_runs(run_id) ON DELETE CASCADE,
            session_id TEXT NOT NULL REFERENCES design_intake_sessions(session_id) ON DELETE CASCADE,
            disposition TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            created_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_design_feedback_session ON design_feedback (session_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_design_runs_intake ON design_runs (intake_session_id, intake_revision_id)",
    ],
    31: [
        """CREATE TABLE IF NOT EXISTS customer_genesis_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision INTEGER NOT NULL,
            genesis_json TEXT NOT NULL,
            genesis_hash TEXT NOT NULL,
            source_kind TEXT NOT NULL DEFAULT 'genesis_update',
            accepted INTEGER NOT NULL DEFAULT 0,
            created_ts TEXT NOT NULL,
            UNIQUE(revision)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_customer_genesis_revision ON customer_genesis_revisions (revision DESC, id DESC)",
        """CREATE TABLE IF NOT EXISTS research_sources (
            source_id TEXT PRIMARY KEY,
            source_json TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            excluded INTEGER NOT NULL DEFAULT 0,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS research_findings (
            finding_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            finding_json TEXT NOT NULL,
            finding_hash TEXT NOT NULL,
            created_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_research_findings_source ON research_findings (source_id, created_ts)",
        """CREATE TABLE IF NOT EXISTS provisioning_bundles (
            bundle_id TEXT PRIMARY KEY,
            bundle_hash TEXT NOT NULL UNIQUE,
            bundle_json TEXT NOT NULL,
            created_ts TEXT NOT NULL
        )""",
    ],
    32: [
        """CREATE TABLE IF NOT EXISTS incubation_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id TEXT NOT NULL UNIQUE,
            occurred_at TEXT NOT NULL,
            category TEXT NOT NULL,
            kind TEXT NOT NULL,
            state TEXT NOT NULL,
            summary TEXT NOT NULL,
            provenance TEXT NOT NULL,
            confidence REAL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            conversation_id INTEGER,
            message_id INTEGER,
            chat_job_id INTEGER,
            intake_session_id TEXT,
            intake_revision INTEGER,
            research_request_id TEXT,
            source_id TEXT,
            finding_ids_json TEXT NOT NULL DEFAULT '[]',
            genesis_revision INTEGER,
            design_run_id TEXT,
            provider_id TEXT,
            activity_hash TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_incubation_activity_category_id ON incubation_activity (category, id)",
        "CREATE INDEX IF NOT EXISTS idx_incubation_activity_chat_job ON incubation_activity (chat_job_id)",
        "CREATE INDEX IF NOT EXISTS idx_incubation_activity_source ON incubation_activity (source_id)",
        "CREATE INDEX IF NOT EXISTS idx_incubation_activity_design_run ON incubation_activity (design_run_id)",
        """CREATE TABLE IF NOT EXISTS research_requests (
            request_id TEXT PRIMARY KEY,
            dedupe_key TEXT NOT NULL UNIQUE,
            request_json TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_research_requests_status ON research_requests (status, updated_ts)",
        """CREATE TABLE IF NOT EXISTS research_jobs (
            job_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL REFERENCES research_requests(request_id),
            job_json TEXT NOT NULL,
            job_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 0,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_research_jobs_request ON research_jobs (request_id, created_ts)",
        "CREATE INDEX IF NOT EXISTS idx_research_jobs_status ON research_jobs (status, updated_ts)",
        """CREATE TABLE IF NOT EXISTS incubation_insights (
            insight_id TEXT PRIMARY KEY,
            insight_json TEXT NOT NULL,
            insight_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            created_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_incubation_insights_status ON incubation_insights (status, created_ts)",
    ],
    33: [
        """CREATE TABLE IF NOT EXISTS incubation_deductions (
            deduction_id TEXT PRIMARY KEY,
            deduction_json TEXT NOT NULL,
            deduction_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            created_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_incubation_deductions_status ON incubation_deductions (status, created_ts)",
        """CREATE TABLE IF NOT EXISTS infusion_runs (
            run_id TEXT PRIMARY KEY,
            trigger TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            budget_tokens INTEGER NOT NULL DEFAULT 0,
            snapshot_hash TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            claimed_by TEXT,
            started_ts TEXT,
            finished_ts TEXT,
            error TEXT NOT NULL DEFAULT '',
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_infusion_runs_status ON infusion_runs (status, updated_ts)",
    ],
    34: [
        "ALTER TABLE media_assets ADD COLUMN analysis_status TEXT NOT NULL DEFAULT 'pending'",
        "ALTER TABLE media_assets ADD COLUMN analysis_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE media_assets ADD COLUMN analysis_error TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE media_assets ADD COLUMN analysis_updated_ts TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE design_intake_operations ADD COLUMN run_id TEXT",
        "ALTER TABLE design_intake_operations ADD COLUMN confirmed_revision_id INTEGER",
        "ALTER TABLE design_intake_operations ADD COLUMN confirmed_revision INTEGER",
        "ALTER TABLE design_intake_operations ADD COLUMN state TEXT NOT NULL DEFAULT 'recorded'",
        "ALTER TABLE design_intake_operations ADD COLUMN force_new INTEGER NOT NULL DEFAULT 0 CHECK (force_new IN (0, 1))",
        "ALTER TABLE design_intake_operations ADD COLUMN error TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE design_intake_operations ADD COLUMN updated_ts TEXT NOT NULL DEFAULT ''",
        """UPDATE media_assets SET
           status = CASE
               WHEN COALESCE(normalized_key, '') <> '' AND COALESCE(thumbnail_key, '') <> '' THEN 'ready'
               ELSE status
           END,
           analysis_status = CASE
               WHEN json_valid(COALESCE(analysis_json, '{}')) = 1
                    AND substr(ltrim(COALESCE(analysis_json, '{}')), 1, 1) = '{'
                    AND trim(COALESCE(analysis_json, '{}')) <> '{}' THEN 'ready'
               WHEN status = 'failed'
                    AND COALESCE(normalized_key, '') <> ''
                    AND COALESCE(thumbnail_key, '') <> '' THEN 'failed'
               ELSE 'pending'
           END,
           analysis_error = CASE
               WHEN status = 'failed'
                    AND COALESCE(normalized_key, '') <> ''
                    AND COALESCE(thumbnail_key, '') <> ''
                    AND NOT (
                        json_valid(COALESCE(analysis_json, '{}')) = 1
                        AND substr(ltrim(COALESCE(analysis_json, '{}')), 1, 1) = '{'
                        AND trim(COALESCE(analysis_json, '{}')) <> '{}'
                    ) THEN substr(COALESCE(last_error, ''), 1, 500)
               ELSE ''
           END,
           analysis_updated_ts = COALESCE(NULLIF(updated_ts, ''), created_ts, ''),
           last_error = CASE
               WHEN COALESCE(normalized_key, '') <> '' AND COALESCE(thumbnail_key, '') <> '' THEN ''
               ELSE last_error
           END""",
        "UPDATE design_intake_operations SET updated_ts = created_ts WHERE updated_ts = ''",
        "CREATE INDEX IF NOT EXISTS idx_media_assets_analysis_status_id ON media_assets (analysis_status, id)",
        "CREATE INDEX IF NOT EXISTS idx_design_intake_operations_build_reservation ON design_intake_operations (session_id, operation, request_hash, state)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_design_intake_build_active_request ON design_intake_operations (session_id, operation, request_hash) WHERE operation = 'build' AND force_new = 0 AND state IN ('reserved', 'submitted')",
    ],
    35: [
        """CREATE TABLE IF NOT EXISTS customer_context_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            context_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            context_hash TEXT NOT NULL,
            context_json TEXT NOT NULL,
            source_incubation_id TEXT NOT NULL,
            source_design_run_id TEXT NOT NULL,
            accepted INTEGER NOT NULL DEFAULT 0 CHECK (accepted IN (0, 1)),
            created_ts TEXT NOT NULL,
            UNIQUE (context_id, revision),
            UNIQUE (context_id, context_hash)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_customer_context_source ON customer_context_revisions (source_incubation_id, created_ts)",
        "CREATE INDEX IF NOT EXISTS idx_customer_context_accepted ON customer_context_revisions (accepted, created_ts)",
        """CREATE TABLE IF NOT EXISTS acceptance_manifests (
            manifest_id TEXT PRIMARY KEY,
            incubation_id TEXT NOT NULL,
            context_id TEXT NOT NULL,
            context_hash TEXT NOT NULL,
            manifest_hash TEXT NOT NULL UNIQUE,
            manifest_json TEXT NOT NULL,
            created_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_acceptance_manifests_incubation ON acceptance_manifests (incubation_id, created_ts)",
        """CREATE TABLE IF NOT EXISTS provisioning_imports (
            import_id TEXT PRIMARY KEY,
            bundle_id TEXT NOT NULL UNIQUE,
            bundle_hash TEXT NOT NULL,
            stage TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_provisioning_imports_stage ON provisioning_imports (stage, updated_ts)",
        """CREATE TABLE IF NOT EXISTS provisioning_id_maps (
            import_id TEXT NOT NULL REFERENCES provisioning_imports(import_id) ON DELETE CASCADE,
            entity_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            destination_id TEXT NOT NULL,
            PRIMARY KEY (import_id, entity_type, source_id)
        )""",
        """CREATE TABLE IF NOT EXISTS website_handoff_receipts (
            receipt_id TEXT PRIMARY KEY,
            manifest_id TEXT NOT NULL,
            candidate_sha TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_commit TEXT NOT NULL DEFAULT '',
            destination_path TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_ts TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_website_handoff_manifest ON website_handoff_receipts (manifest_id, created_ts)",
    ],
    36: [
        "ALTER TABLE design_runs ADD COLUMN customer_context_id TEXT",
        "ALTER TABLE design_runs ADD COLUMN customer_context_hash TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE design_runs ADD COLUMN customer_context_revision INTEGER",
        "CREATE INDEX IF NOT EXISTS idx_design_runs_customer_context ON design_runs (customer_context_id, customer_context_revision)",
    ],
    37: [
        """CREATE TABLE IF NOT EXISTS design_run_phase_artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES design_runs(run_id) ON DELETE CASCADE,
            phase TEXT NOT NULL,
            variant_key TEXT NOT NULL DEFAULT '',
            attempt INTEGER NOT NULL CHECK (attempt >= 1 AND attempt <= 2),
            status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
            base_sha TEXT NOT NULL,
            context_snapshot_hash TEXT NOT NULL DEFAULT '',
            input_hashes_json TEXT NOT NULL DEFAULT '[]',
            payload_json TEXT NOT NULL DEFAULT '{}',
            output_hash TEXT NOT NULL DEFAULT '',
            artifact_id INTEGER,
            provider_id TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            transcript_artifact_id INTEGER,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            reported_cost_usd REAL,
            error_code TEXT NOT NULL DEFAULT '',
            error_detail TEXT NOT NULL DEFAULT '',
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            UNIQUE(run_id, phase, variant_key, attempt)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_design_phase_artifacts_run ON design_run_phase_artifacts (run_id, phase, variant_key, status)",
        "CREATE INDEX IF NOT EXISTS idx_design_phase_artifacts_status ON design_run_phase_artifacts (status, updated_ts)",
    ],
}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _locked(fn):
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper


class Memory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        current = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for version in range(current + 1, SCHEMA_VERSION + 1):
            statements = MIGRATIONS.get(version, [])
            with self.conn:
                for statement in statements:
                    self.conn.execute(statement)
                self.conn.execute(f"PRAGMA user_version = {version}")
        # A crash can leave a claimed asset behind. It is safe to retry only the
        # media pipeline; never replay a website or chat mutation implicitly.
        with self.conn:
            self.conn.execute(
                "UPDATE media_assets SET status = 'queued', last_error = ? "
                "WHERE status = 'processing'",
                ("interrupted by server restart; queued for retry",),
            )

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    @_locked
    def get_schema_version(self) -> int:
        """Return the migrated schema version without exposing SQLite to services."""
        row = self.conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    @_locked
    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    @_locked
    def kv_set(self, key: str, value: Any) -> None:
        encoded = value if isinstance(value, str) else json.dumps(value)
        with self.conn:
            self.conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, encoded),
            )

    @_locked
    def record_observation(
        self,
        source: str,
        text: str,
        meta: dict[str, Any] | None = None,
        *,
        timestamp: str | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO observations (ts, source, text, meta) VALUES (?, ?, ?, ?)",
                (str(timestamp or _now()), source, text, json.dumps(meta or {})),
            )
        return cur.lastrowid

    @_locked
    def recent_observations(self, limit: int = 20, source: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM observations"
        params: list[Any] = []
        if source:
            query += " WHERE source = ?"
            params.append(source)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = [dict(r) for r in self.conn.execute(query, params)]
        for row in rows:
            try:
                row["meta"] = json.loads(row.get("meta") or "{}")
            except (json.JSONDecodeError, TypeError):
                row["meta"] = {}
        return rows

    @_locked
    def observations_since(
        self,
        after_id: int = 0,
        sources: list[str] | tuple[str, ...] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return observations after an id in durable insertion order."""
        query = "SELECT * FROM observations WHERE id > ?"
        params: list[Any] = [after_id]
        if sources:
            query += " AND source IN (" + ",".join("?" for _ in sources) + ")"
            params.extend(sources)
        query += " ORDER BY id ASC LIMIT ?"
        params.append(max(1, min(int(limit), 5000)))
        rows = [dict(row) for row in self.conn.execute(query, params)]
        for row in rows:
            try:
                row["meta"] = json.loads(row.get("meta") or "{}")
            except (json.JSONDecodeError, TypeError):
                row["meta"] = {}
        return rows

    @_locked
    def record_action(self, kind: str, detail: str = "") -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO actions (ts, kind, detail) VALUES (?, ?, ?)",
                (_now(), kind, detail[:500]),
            )
        return cur.lastrowid

    @_locked
    def recent_actions(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,)
            )
        ]

    @_locked
    def create_owner_action(self, action: OwnerAction) -> OwnerAction:
        if action.id is not None:
            raise ContractError("new owner action must not already have an id")
        record = action.to_record()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO owner_actions "
                "(capability_id, provider_id, title, summary, action_label, priority, requirement, state, "
                "source_ref, dedupe_key, created_ts, updated_ts, snoozed_until, conversation_id, artifact_id, "
                "job_id, approval_id, draft_id, payload_version, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["capability_id"], record["provider_id"], record["title"], record["summary"],
                    record["action_label"], record["priority"], record["requirement"], record["state"],
                    record["source_ref"], record["dedupe_key"], record["created_ts"], record["updated_ts"],
                    record["snoozed_until"], record["conversation_id"], record["artifact_id"], record["job_id"],
                    record["approval_id"], record["draft_id"], record["payload_version"], record["payload"],
                ),
            )
        return replace(action, id=cur.lastrowid)

    @_locked
    def get_owner_action(self, action_id: int) -> OwnerAction | None:
        row = self.conn.execute("SELECT * FROM owner_actions WHERE id = ?", (action_id,)).fetchone()
        return OwnerAction.from_record(dict(row)) if row else None

    @_locked
    def find_owner_action(self, dedupe_key: str, include_terminal: bool = False) -> OwnerAction | None:
        query = "SELECT * FROM owner_actions WHERE dedupe_key = ?"
        if not include_terminal:
            query += " AND state NOT IN ('completed', 'dismissed', 'stale')"
        query += " ORDER BY id DESC LIMIT 1"
        row = self.conn.execute(query, (dedupe_key,)).fetchone()
        return OwnerAction.from_record(dict(row)) if row else None

    @_locked
    def list_owner_actions(
        self,
        states: list[str] | tuple[str, ...] | None = None,
        limit: int = 100,
        *,
        job_id: int | None = None,
    ) -> list[OwnerAction]:
        query = "SELECT * FROM owner_actions"
        params: list[Any] = []
        clauses: list[str] = []
        if states:
            values = [ActionState(state).value for state in states]
            clauses.append("state IN (" + ",".join("?" for _ in values) + ")")
            params.extend(values)
        if job_id is not None:
            clauses.append("job_id = ?")
            params.append(job_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [OwnerAction.from_record(dict(row)) for row in self.conn.execute(query, params)]

    @_locked
    def transition_owner_action(
        self,
        action_id: int,
        state: ActionState | str,
        *,
        snoozed_until: str | None = None,
    ) -> OwnerAction | None:
        row = self.conn.execute("SELECT * FROM owner_actions WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            return None
        current = OwnerAction.from_record(dict(row))
        try:
            target = ActionState(state)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"invalid owner action state: {state}") from exc
        validate_action_transition(current.state, target)
        if target == ActionState.SNOOZED and not snoozed_until:
            raise ContractError("snoozed actions require snoozed_until")
        next_snoozed_until = snoozed_until if target == ActionState.SNOOZED else None
        updated_ts = _now()
        with self.conn:
            self.conn.execute(
                "UPDATE owner_actions SET state = ?, snoozed_until = ?, updated_ts = ? WHERE id = ?",
                (target.value, next_snoozed_until, updated_ts, action_id),
            )
        return replace(current, state=target, snoozed_until=next_snoozed_until, updated_ts=updated_ts)

    @_locked
    def link_owner_action(
        self,
        action_id: int | None,
        *,
        conversation_id: int | None = None,
        job_id: int | None = None,
        artifact_id: int | None = None,
        approval_id: int | None = None,
        draft_id: int | None = None,
    ) -> OwnerAction:
        if action_id is None:
            raise ContractError("owner action id is required")
        action = self.get_owner_action(action_id)
        if action is None:
            raise KeyError(f"no such owner action: {action_id}")
        fields: list[str] = []
        values: list[Any] = []
        for name, value in (
            ("conversation_id", conversation_id),
            ("job_id", job_id),
            ("artifact_id", artifact_id),
            ("approval_id", approval_id),
            ("draft_id", draft_id),
        ):
            if value is not None:
                fields.append(f"{name} = ?")
                values.append(value)
        if not fields:
            return action
        updated_ts = _now()
        fields.append("updated_ts = ?")
        values.extend((updated_ts, action_id))
        with self.conn:
            self.conn.execute(
                f"UPDATE owner_actions SET {', '.join(fields)} WHERE id = ?", values
            )
        return replace(
            action,
            conversation_id=conversation_id if conversation_id is not None else action.conversation_id,
            job_id=job_id if job_id is not None else action.job_id,
            artifact_id=artifact_id if artifact_id is not None else action.artifact_id,
            approval_id=approval_id if approval_id is not None else action.approval_id,
            draft_id=draft_id if draft_id is not None else action.draft_id,
            updated_ts=updated_ts,
        )

    @_locked
    def create_artifact(self, artifact: Artifact) -> Artifact:
        if artifact.artifact_id is not None:
            raise ContractError("new artifact must not already have an id")
        record = artifact.to_record()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO artifacts "
                "(revision, kind, title, summary, renderer, capability_id, provider_id, source_action_id, content_hash, preview_data, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["revision"], record["kind"], record["title"], record["summary"], record["renderer"],
                    record["capability_id"], record["provider_id"], record["source_action_id"],
                    record["content_hash"], record["preview_data"], record["created_ts"],
                ),
            )
        return replace(artifact, artifact_id=cur.lastrowid)

    @staticmethod
    def _design_phase_record(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for field_name in ("input_hashes_json", "payload_json"):
            value = result.get(field_name)
            try:
                result[field_name.removesuffix("_json")] = json.loads(value or ("[]" if field_name == "input_hashes_json" else "{}"))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ContractError(f"design phase {field_name} is not valid JSON") from exc
        return result

    @_locked
    def claim_design_phase(
        self,
        run_id: str,
        phase: str,
        *,
        variant_key: str = "",
        base_sha: str,
        context_snapshot_hash: str = "",
        input_hashes: tuple[str, ...] | list[str] = (),
        max_attempts: int = 2,
        provider_id: str = "",
        model: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        """Claim one finite specialist phase, or return its existing state.

        A completed artifact is authoritative and is returned without creating
        another attempt. A running artifact is also returned so a second
        worker cannot dispatch the same specialist concurrently.
        """
        phase = validate_design_phase(phase)
        run_id = str(run_id).strip()
        variant_key = str(variant_key).strip()
        if not run_id:
            raise ContractError("run_id must not be empty")
        if not re.fullmatch(r"[0-9a-f]{40}", str(base_sha).lower()):
            raise ContractError("base_sha is not a valid commit hash")
        base_sha = str(base_sha).lower()
        if context_snapshot_hash and not re.fullmatch(r"[0-9a-f]{64}", str(context_snapshot_hash).lower()):
            raise ContractError("context_snapshot_hash is not a valid content hash")
        context_snapshot_hash = str(context_snapshot_hash).lower()
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 2:
            raise ContractError("max_attempts must be between 1 and 2")
        hashes = [str(item).strip().lower() for item in input_hashes]
        if len(hashes) > 32 or any(not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", item) for item in hashes):
            raise ContractError("input_hashes contains an invalid content hash")
        with self.conn:
            row = self.conn.execute(
                "SELECT * FROM design_run_phase_artifacts "
                "WHERE run_id = ? AND phase = ? AND variant_key = ? "
                "AND status IN ('running', 'completed') ORDER BY id DESC LIMIT 1",
                (run_id, phase, variant_key),
            ).fetchone()
            if row is not None:
                result = self._design_phase_record(row)
                result["claimed"] = False
                return result
            attempt_row = self.conn.execute(
                "SELECT COALESCE(MAX(attempt), 0) AS attempt FROM design_run_phase_artifacts "
                "WHERE run_id = ? AND phase = ? AND variant_key = ?",
                (run_id, phase, variant_key),
            ).fetchone()
            attempt = int(attempt_row["attempt"] or 0) + 1
            if attempt > max_attempts:
                raise ContractError(f"design phase {phase}/{variant_key} exhausted its attempts")
            now = _now()
            cur = self.conn.execute(
                "INSERT INTO design_run_phase_artifacts "
                "(run_id, phase, variant_key, attempt, status, base_sha, context_snapshot_hash, "
                "input_hashes_json, provider_id, model, session_id, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, phase, variant_key, attempt, base_sha, context_snapshot_hash,
                    canonical_json(hashes), str(provider_id).strip()[:200], str(model).strip()[:240],
                    str(session_id).strip()[:240], now, now,
                ),
            )
            row = self.conn.execute(
                "SELECT * FROM design_run_phase_artifacts WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        result = self._design_phase_record(row)
        result["claimed"] = True
        return result

    @_locked
    def complete_design_phase(
        self,
        phase_artifact_id: int,
        payload: dict[str, Any],
        *,
        output_hash: str = "",
        artifact_id: int | None = None,
        transcript_artifact_id: int | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        reported_cost_usd: float | None = None,
    ) -> dict[str, Any]:
        if isinstance(phase_artifact_id, bool) or not isinstance(phase_artifact_id, int) or phase_artifact_id < 1:
            raise ContractError("phase_artifact_id must be a positive integer")
        if not isinstance(payload, dict):
            raise ContractError("phase payload must be an object")
        encoded = canonical_json(payload)
        output_hash = str(output_hash or canonical_hash(payload)).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", output_hash):
            raise ContractError("output_hash is not a valid content hash")
        if isinstance(prompt_tokens, bool) or not isinstance(prompt_tokens, int) or prompt_tokens < 0:
            raise ContractError("prompt_tokens must be a non-negative integer")
        if isinstance(completion_tokens, bool) or not isinstance(completion_tokens, int) or completion_tokens < 0:
            raise ContractError("completion_tokens must be a non-negative integer")
        with self.conn:
            row = self.conn.execute(
                "SELECT * FROM design_run_phase_artifacts WHERE id = ?", (phase_artifact_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"no such design phase artifact: {phase_artifact_id}")
            if row["status"] == "completed":
                existing = self._design_phase_record(row)
                if existing.get("output_hash") != output_hash:
                    raise ContractError("completed design phase cannot be replaced")
                return existing
            if row["status"] != "running":
                raise ContractError("only a running design phase can be completed")
            now = _now()
            self.conn.execute(
                "UPDATE design_run_phase_artifacts SET status = 'completed', payload_json = ?, "
                "output_hash = ?, artifact_id = ?, transcript_artifact_id = ?, prompt_tokens = ?, "
                "completion_tokens = ?, reported_cost_usd = ?, error_code = '', error_detail = '', updated_ts = ? "
                "WHERE id = ?",
                (
                    encoded, output_hash, artifact_id, transcript_artifact_id, prompt_tokens,
                    completion_tokens, reported_cost_usd, now, phase_artifact_id,
                ),
            )
            row = self.conn.execute(
                "SELECT * FROM design_run_phase_artifacts WHERE id = ?", (phase_artifact_id,)
            ).fetchone()
        return self._design_phase_record(row)

    @_locked
    def fail_design_phase(
        self,
        phase_artifact_id: int,
        *,
        error_code: str,
        error_detail: str = "",
    ) -> dict[str, Any]:
        if isinstance(phase_artifact_id, bool) or not isinstance(phase_artifact_id, int) or phase_artifact_id < 1:
            raise ContractError("phase_artifact_id must be a positive integer")
        with self.conn:
            row = self.conn.execute(
                "SELECT * FROM design_run_phase_artifacts WHERE id = ?", (phase_artifact_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"no such design phase artifact: {phase_artifact_id}")
            if row["status"] == "completed":
                return self._design_phase_record(row)
            now = _now()
            self.conn.execute(
                "UPDATE design_run_phase_artifacts SET status = 'failed', error_code = ?, error_detail = ?, updated_ts = ? WHERE id = ?",
                (str(error_code).strip()[:120], str(error_detail).strip()[:2_000], now, phase_artifact_id),
            )
            row = self.conn.execute(
                "SELECT * FROM design_run_phase_artifacts WHERE id = ?", (phase_artifact_id,)
            ).fetchone()
        return self._design_phase_record(row)

    @_locked
    def get_design_phase_artifact(self, phase_artifact_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM design_run_phase_artifacts WHERE id = ?", (phase_artifact_id,)
        ).fetchone()
        return self._design_phase_record(row) if row else None

    @_locked
    def list_design_phase_artifacts(
        self,
        run_id: str,
        *,
        phase: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["run_id = ?"]
        params: list[Any] = [str(run_id).strip()]
        if phase is not None:
            clauses.append("phase = ?")
            params.append(validate_design_phase(phase))
        if status is not None:
            clauses.append("status = ?")
            params.append(validate_design_phase_status(status))
        rows = self.conn.execute(
            "SELECT * FROM design_run_phase_artifacts WHERE "
            + " AND ".join(clauses) + " ORDER BY id ASC", params
        ).fetchall()
        return [self._design_phase_record(row) for row in rows]

    @_locked
    def create_social_artifact(self, preparation_id: int, artifact: Artifact) -> Artifact:
        """Create and link an artifact atomically to its preparation record."""
        row = self.conn.execute(
            "SELECT artifact_id FROM social_preparations WHERE id = ?", (preparation_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such social preparation: {preparation_id}")
        if row["artifact_id"] is not None:
            existing = self.get_artifact(row["artifact_id"])
            if existing is not None:
                return existing
        if artifact.artifact_id is not None:
            raise ContractError("new artifact must not already have an id")
        record = artifact.to_record()
        now = _now()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO artifacts "
                "(revision, kind, title, summary, renderer, capability_id, provider_id, source_action_id, content_hash, preview_data, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["revision"], record["kind"], record["title"], record["summary"], record["renderer"],
                    record["capability_id"], record["provider_id"], record["source_action_id"],
                    record["content_hash"], record["preview_data"], record["created_ts"],
                ),
            )
            self.conn.execute(
                "UPDATE social_preparations SET artifact_id = ?, updated_ts = ? WHERE id = ?",
                (cur.lastrowid, now, preparation_id),
            )
        return replace(artifact, artifact_id=cur.lastrowid)

    @_locked
    def get_social_preparation(self, idempotency_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM social_preparations WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    @_locked
    def get_social_preparation_by_id(self, preparation_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM social_preparations WHERE id = ?", (preparation_id,)
        ).fetchone()
        return dict(row) if row else None

    @_locked
    def create_social_preparation(
        self,
        idempotency_key: str,
        request_hash: str,
        request_json: str,
        *,
        action_id: int | None = None,
        job_id: int | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO social_preparations "
                "(idempotency_key, request_hash, request_json, action_id, job_id, status, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, 'submitting', ?, ?)",
                (idempotency_key, request_hash, request_json, action_id, job_id, now, now),
            )
        return self.get_social_preparation_by_id(cur.lastrowid)

    @_locked
    def update_social_preparation(self, preparation_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "provider_operation_id", "provider_post_id", "artifact_id", "approval_id",
            "action_id", "job_id", "status", "error",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if updates:
            updates["updated_ts"] = _now()
            assignments = ", ".join(f"{key} = ?" for key in updates)
            with self.conn:
                self.conn.execute(
                    f"UPDATE social_preparations SET {assignments} WHERE id = ?",
                    [*updates.values(), preparation_id],
                )
        return self.get_social_preparation_by_id(preparation_id)

    @_locked
    def get_artifact(self, artifact_id: int) -> Artifact | None:
        row = self.conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        return Artifact.from_record(dict(row)) if row else None

    @_locked
    def list_artifacts(self, kind: str | None = None, limit: int = 100) -> list[Artifact]:
        query = "SELECT * FROM artifacts"
        params: list[Any] = []
        if kind:
            query += " WHERE kind = ?"
            params.append(kind)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        return [Artifact.from_record(dict(row)) for row in self.conn.execute(query, params)]

    @_locked
    def create_approval_request(self, approval: ApprovalRequest) -> ApprovalRequest:
        if approval.approval_id is not None:
            raise ContractError("new approval request must not already have an id")
        record = approval.to_record()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO approval_requests "
                "(artifact_id, artifact_hash, effect_class, owner_action_label, provider_id, action_id, status, created_ts, updated_ts, decided_ts, owner_feedback, execution_job_id, provider_receipt_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["artifact_id"], record["artifact_hash"], record["effect_class"], record["owner_action_label"],
                    record["provider_id"], record["action_id"], record["status"], record["created_ts"],
                    record["updated_ts"], record["decided_ts"], record["owner_feedback"],
                    record["execution_job_id"], record["provider_receipt_id"],
                ),
            )
        return replace(approval, approval_id=cur.lastrowid)

    @_locked
    def get_approval_request(self, approval_id: int) -> ApprovalRequest | None:
        row = self.conn.execute("SELECT * FROM approval_requests WHERE id = ?", (approval_id,)).fetchone()
        return ApprovalRequest.from_record(dict(row)) if row else None

    @_locked
    def list_approval_requests(
        self,
        status: ApprovalStatus | str | None = None,
        limit: int = 100,
    ) -> list[ApprovalRequest]:
        query = "SELECT * FROM approval_requests"
        params: list[Any] = []
        if status is not None:
            value = status.value if isinstance(status, ApprovalStatus) else ApprovalStatus(status).value
            query += " WHERE status = ?"
            params.append(value)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [ApprovalRequest.from_record(dict(row)) for row in self.conn.execute(query, params)]

    @_locked
    def transition_approval_request(
        self,
        approval_id: int,
        status: ApprovalStatus | str,
        *,
        owner_feedback: str | None = None,
    ) -> ApprovalRequest | None:
        row = self.conn.execute("SELECT * FROM approval_requests WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            return None
        current = ApprovalRequest.from_record(dict(row))
        try:
            target = ApprovalStatus(status)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"invalid approval status: {status}") from exc
        validate_approval_transition(current.status, target)
        updated_ts = _now()
        decided_ts = updated_ts if target != ApprovalStatus.PENDING else current.decided_ts
        feedback = current.owner_feedback if owner_feedback is None else owner_feedback.strip()[:1000]
        with self.conn:
            self.conn.execute(
                "UPDATE approval_requests SET status = ?, updated_ts = ?, decided_ts = ?, owner_feedback = ? WHERE id = ?",
                (target.value, updated_ts, decided_ts, feedback, approval_id),
            )
        return replace(current, status=target, updated_ts=updated_ts, decided_ts=decided_ts, owner_feedback=feedback)

    @_locked
    def create_provider_receipt(self, receipt: ProviderReceipt) -> ProviderReceipt:
        if receipt.receipt_id is not None:
            raise ContractError("new provider receipt must not already have an id")
        record = receipt.to_record()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO provider_receipts "
                "(provider_id, capability_id, action_id, approval_id, idempotency_key, external_object_id, external_url, status, safe_message, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["provider_id"], record["capability_id"], record["action_id"], record["approval_id"],
                    record["idempotency_key"], record["external_object_id"], record["external_url"],
                    record["status"], record["safe_message"], record["created_ts"], record["updated_ts"],
                ),
            )
        return replace(receipt, receipt_id=cur.lastrowid)

    @_locked
    def get_provider_receipt(self, receipt_id: int) -> ProviderReceipt | None:
        row = self.conn.execute("SELECT * FROM provider_receipts WHERE id = ?", (receipt_id,)).fetchone()
        return ProviderReceipt.from_record(dict(row)) if row else None

    @_locked
    def get_provider_receipt_by_idempotency_key(self, idempotency_key: str) -> ProviderReceipt | None:
        row = self.conn.execute(
            "SELECT * FROM provider_receipts WHERE idempotency_key = ? ORDER BY id DESC LIMIT 1",
            (idempotency_key,),
        ).fetchone()
        return ProviderReceipt.from_record(dict(row)) if row else None

    @_locked
    def link_approval_request(
        self,
        approval_id: int,
        *,
        provider_receipt_id: int | None = None,
        execution_job_id: int | None = None,
    ) -> ApprovalRequest:
        approval = self.get_approval_request(approval_id)
        if approval is None:
            raise KeyError(f"no such approval: {approval_id}")
        fields: list[str] = []
        values: list[Any] = []
        if provider_receipt_id is not None:
            fields.append("provider_receipt_id = ?")
            values.append(provider_receipt_id)
        if execution_job_id is not None:
            fields.append("execution_job_id = ?")
            values.append(execution_job_id)
        if not fields:
            return approval
        fields.append("updated_ts = ?")
        values.extend((_now(), approval_id))
        with self.conn:
            self.conn.execute(f"UPDATE approval_requests SET {', '.join(fields)} WHERE id = ?", values)
        return self.get_approval_request(approval_id)

    @_locked
    def save_draft(
        self,
        title: str,
        body: str,
        kind: str = "article",
        meta: dict[str, Any] | None = None,
        draft_id: int | None = None,
    ) -> int:
        now = _now()
        with self.conn:
            if draft_id is None:
                cur = self.conn.execute(
                    "INSERT INTO drafts (created_ts, updated_ts, kind, title, body, status, meta) "
                    "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                    (now, now, kind, title, body, json.dumps(meta or {})),
                )
                return cur.lastrowid
            self.conn.execute(
                "UPDATE drafts SET updated_ts = ?, title = ?, body = ?, meta = ? WHERE id = ?",
                (now, title, body, json.dumps(meta or {}), draft_id),
            )
            return draft_id

    @_locked
    def update_draft_status(self, draft_id: int, status: str) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE drafts SET status = ?, updated_ts = ? WHERE id = ?",
                (status, _now(), draft_id),
            )
        return cur.rowcount > 0

    @_locked
    def add_draft_feedback(self, draft_id: int, feedback: str) -> bool:
        """Attach the owner's rejection note to the draft's meta so the decision
        ledger can show the *reason* a proposal was declined. Structured data,
        not parsed from free text."""
        feedback = (feedback or "").strip()
        if not feedback:
            return False
        try:
            row = self.conn.execute("SELECT meta FROM drafts WHERE id = ?", (draft_id,)).fetchone()
            if row is None:
                return False
            meta = json.loads(row["meta"]) if row["meta"] else {}
            meta["feedback"] = feedback
            with self.conn:
                self.conn.execute(
                    "UPDATE drafts SET meta = ?, updated_ts = ? WHERE id = ?",
                    (json.dumps(meta), _now(), draft_id),
                )
            return True
        except (json.JSONDecodeError, TypeError):
            return False

    @_locked
    def list_drafts(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT * FROM drafts"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = [dict(r) for r in self.conn.execute(query, params)]
        for row in rows:
            try:
                row["meta"] = json.loads(row["meta"])
            except (json.JSONDecodeError, TypeError):
                pass
        return rows

    @staticmethod
    def _design_json(value: Any, field_name: str, *, max_bytes: int = 100_000) -> tuple[str, str]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ContractError(f"{field_name} must contain valid JSON") from exc
        if not isinstance(value, dict):
            raise ContractError(f"{field_name} must be a JSON object")
        cleaned = safe_payload(
            value,
            max_bytes=max_bytes,
            preserve_keys={"tokens", "max_tokens", "output_tokens", "planner_max_tokens", "template_tokens"},
        )
        encoded = canonical_json(cleaned)
        if len(encoded.encode("utf-8")) > max_bytes:
            raise ContractError(f"{field_name} exceeds {max_bytes} bytes")
        return encoded, canonical_hash(cleaned)

    @staticmethod
    def _decode_design_json(value: Any) -> dict[str, Any]:
        try:
            decoded = json.loads(value or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def _design_sha(value: Any, field_name: str, length: int) -> str:
        result = str(value or "").strip().lower()
        if result and not re.fullmatch(rf"[0-9a-f]{{{length}}}", result):
            raise ContractError(f"{field_name} is not a valid Git SHA")
        return result

    @_locked
    def create_design_run(
        self,
        *,
        run_id: str,
        mode: str,
        status: str = DesignRunStatus.CREATED.value,
        intake_json: dict[str, Any],
        intake_hash: str = "",
        base_sha: str = "",
        publishable: bool = False,
        candidate_ref: str = "",
        design_manifest_path: str = "",
        parent_run_id: str | None = None,
        operation_kind: str = DesignOperationKind.INITIAL_BUILD.value,
        source_candidate_sha: str = "",
        owner_request: str = "",
        conversation_id: int | None = None,
        source_message_id: int | None = None,
        chat_job_id: int | None = None,
        intake_session_id: str | None = None,
        intake_revision_id: int | None = None,
    ) -> dict[str, Any]:
        """Create the immutable input snapshot for a design workflow."""
        run_id = str(run_id or "").strip()
        if not run_id or len(run_id) > 120 or not re.fullmatch(r"[A-Za-z0-9._:-]+", run_id):
            raise ContractError("run_id is invalid")
        try:
            mode = str(mode)
            status = DesignRunStatus(status).value
            operation_kind = validate_design_operation_kind(operation_kind)
        except (TypeError, ValueError) as exc:
            raise ContractError("status or operation_kind is invalid") from exc
        if mode not in {"production_candidate", "local_experiment"}:
            raise ContractError("mode is invalid")
        if not isinstance(publishable, bool):
            raise ContractError("publishable must be boolean")
        if mode == "local_experiment" and publishable:
            raise ContractError("local_experiment must not be publishable")
        for value, name in (
            (conversation_id, "conversation_id"),
            (source_message_id, "source_message_id"),
            (chat_job_id, "chat_job_id"),
            (intake_revision_id, "intake_revision_id"),
        ):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise ContractError(f"{name} is invalid")
        if intake_session_id is not None:
            intake_session_id = self._validate_intake_session_id(intake_session_id)
        intake_encoded, computed_hash = self._design_json(intake_json, "intake_json")
        intake_hash = str(intake_hash or computed_hash).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", intake_hash):
            raise ContractError("intake_hash is not a valid content hash")
        base_sha = self._design_sha(base_sha, "base_sha", 40)
        candidate_ref = str(candidate_ref or "").strip()
        if len(candidate_ref) > 240 or ".." in candidate_ref or not re.fullmatch(r"[A-Za-z0-9._/-]*", candidate_ref):
            raise ContractError("candidate_ref is invalid")
        design_manifest_path = str(design_manifest_path or "").strip()
        if design_manifest_path:
            design_manifest_path = safe_relative_path(design_manifest_path, "design_manifest_path")
        parent_run_id = str(parent_run_id or "").strip() or None
        if parent_run_id is not None:
            if parent_run_id == run_id or not re.fullmatch(r"[A-Za-z0-9._:-]+", parent_run_id):
                raise ContractError("parent_run_id is invalid")
            parent = self.get_design_run(parent_run_id)
            if parent is None:
                raise ContractError("parent_run_id does not reference a design run")
        source_candidate_sha = self._design_sha(source_candidate_sha, "source_candidate_sha", 40)
        if parent_run_id:
            parent_record = self.get_design_run(parent_run_id)
            parent_sha = parent_record["candidate_sha"] if parent_record else ""
            if not source_candidate_sha:
                source_candidate_sha = parent_sha
            if not parent_sha or source_candidate_sha != parent_sha:
                raise ContractError("source_candidate_sha must match the parent candidate")
        elif source_candidate_sha:
            raise ContractError("source_candidate_sha requires parent_run_id")
        now = _now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO design_runs "
                "(run_id, mode, status, intake_json, intake_hash, base_sha, candidate_ref, publishable, design_manifest_path, "
                "parent_run_id, operation_kind, source_candidate_sha, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, mode, str(status), intake_encoded, intake_hash, base_sha, candidate_ref,
                 int(publishable), design_manifest_path, parent_run_id, operation_kind,
                 source_candidate_sha, now, now),
            )
            self.conn.execute(
                "UPDATE design_runs SET owner_request = ?, conversation_id = ?, source_message_id = ?, chat_job_id = ? WHERE run_id = ?",
                (safe_provider_message(owner_request, max_chars=20_000), conversation_id, source_message_id, chat_job_id, run_id),
            )
            self.conn.execute(
                "UPDATE design_runs SET intake_session_id = ?, intake_revision_id = ? WHERE run_id = ?",
                (intake_session_id, intake_revision_id, run_id),
            )
        return self.get_design_run(run_id)

    @_locked
    def get_design_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM design_runs WHERE run_id = ?", (str(run_id),)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["publishable"] = bool(result.get("publishable"))
        result["intake_json"] = self._decode_design_json(result.get("intake_json"))
        result["design_manifest_json"] = self._decode_design_json(result.get("design_manifest_json"))
        result["quality_report_json"] = self._decode_design_json(result.get("quality_report_json"))
        result["planning_json"] = self._decode_design_json(result.get("planning_json"))
        result["context_snapshot"] = self._decode_design_json(result.get("context_snapshot_json"))
        return result

    @_locked
    def get_design_run_by_chat_job(self, chat_job_id: int) -> dict[str, Any] | None:
        """Find the design handoff already created by one durable chat job."""
        if isinstance(chat_job_id, bool) or not isinstance(chat_job_id, int) or chat_job_id < 1:
            return None
        row = self.conn.execute(
            "SELECT run_id FROM design_runs WHERE chat_job_id = ? ORDER BY id DESC LIMIT 1",
            (chat_job_id,),
        ).fetchone()
        return self.get_design_run(row["run_id"]) if row else None

    @_locked
    def list_design_run_children(self, parent_run_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return immutable follow-up operations in creation order."""
        if self.get_design_run(parent_run_id) is None:
            return []
        rows = []
        for row in self.conn.execute(
            "SELECT * FROM design_runs WHERE parent_run_id = ? ORDER BY id ASC LIMIT ?",
            (str(parent_run_id), max(1, min(int(limit), 500))),
        ):
            result = dict(row)
            result["publishable"] = bool(result.get("publishable"))
            result["intake_json"] = self._decode_design_json(result.get("intake_json"))
            result["design_manifest_json"] = self._decode_design_json(result.get("design_manifest_json"))
            result["quality_report_json"] = self._decode_design_json(result.get("quality_report_json"))
            result["planning_json"] = self._decode_design_json(result.get("planning_json"))
            result["context_snapshot"] = self._decode_design_json(result.get("context_snapshot_json"))
            rows.append(result)
        return rows

    @_locked
    def list_design_runs(
        self,
        *,
        status: str | None = None,
        mode: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            try:
                status = DesignRunStatus(status).value
            except (TypeError, ValueError) as exc:
                raise ContractError("status is invalid") from exc
            clauses.append("status = ?")
            params.append(status)
        if mode is not None:
            mode = str(mode)
            if mode not in {"production_candidate", "local_experiment"}:
                raise ContractError("mode is invalid")
            clauses.append("mode = ?")
            params.append(mode)
        query = "SELECT * FROM design_runs"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        rows = []
        for row in self.conn.execute(query, params):
            result = dict(row)
            result["publishable"] = bool(result.get("publishable"))
            result["intake_json"] = self._decode_design_json(result.get("intake_json"))
            result["design_manifest_json"] = self._decode_design_json(result.get("design_manifest_json"))
            result["quality_report_json"] = self._decode_design_json(result.get("quality_report_json"))
            result["planning_json"] = self._decode_design_json(result.get("planning_json"))
            result["context_snapshot"] = self._decode_design_json(result.get("context_snapshot_json"))
            rows.append(result)
        return rows

    @_locked
    def update_design_run(self, run_id: str, **fields: Any) -> dict[str, Any] | None:
        """Update mutable evidence fields; status changes use guarded transitions."""
        current = self.get_design_run(run_id)
        if current is None:
            return None
        status = fields.pop("status", None)
        if status is not None:
            validate_design_run_transition(current["status"], status)
        updates: dict[str, Any] = {}
        if "candidate_sha" in fields:
            updates["candidate_sha"] = self._design_sha(fields["candidate_sha"], "candidate_sha", 40)
        if "candidate_ref" in fields:
            candidate_ref = str(fields["candidate_ref"] or "").strip()
            if len(candidate_ref) > 240 or ".." in candidate_ref or not re.fullmatch(r"[A-Za-z0-9._/-]*", candidate_ref):
                raise ContractError("candidate_ref is invalid")
            updates["candidate_ref"] = candidate_ref
        if "source_candidate_sha" in fields:
            updates["source_candidate_sha"] = self._design_sha(
                fields["source_candidate_sha"], "source_candidate_sha", 40
            )
        if "transcript_path" in fields:
            transcript_path = str(fields["transcript_path"] or "").strip()
            updates["transcript_path"] = safe_relative_path(transcript_path, "transcript_path") if transcript_path else ""
        for name in ("opencode_session_id", "provider_id", "model_id"):
            if name in fields:
                value = str(fields[name] or "").strip()
                if len(value) > 240:
                    raise ContractError(f"{name} is too long")
                updates[name] = value
        for name in ("transcript_artifact_id", "build_artifact_id", "screenshot_artifact_id"):
            if name in fields:
                value = fields[name]
                if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                    raise ContractError(f"{name} is invalid")
                updates[name] = value
        if "design_manifest_path" in fields:
            manifest_path = str(fields["design_manifest_path"] or "").strip()
            updates["design_manifest_path"] = safe_relative_path(manifest_path, "design_manifest_path") if manifest_path else ""
        if "design_manifest_json" in fields:
            encoded, computed_hash = self._design_json(fields["design_manifest_json"], "design_manifest_json")
            updates["design_manifest_json"] = encoded
            if "design_manifest_hash" not in fields:
                fields["design_manifest_hash"] = computed_hash
        if "quality_report_json" in fields:
            encoded, computed_hash = self._design_json(fields["quality_report_json"], "quality_report_json")
            updates["quality_report_json"] = encoded
            if "quality_report_hash" not in fields:
                fields["quality_report_hash"] = computed_hash
        if "planning_json" in fields:
            encoded, computed_hash = self._design_json(fields["planning_json"], "planning_json")
            updates["planning_json"] = encoded
            if "planning_hash" not in fields:
                fields["planning_hash"] = computed_hash
        if "context_snapshot" in fields:
            raw_snapshot = fields["context_snapshot"]
            if isinstance(raw_snapshot, DesignContextSnapshot):
                raw_snapshot = raw_snapshot.to_dict()
            parsed_snapshot = DesignContextSnapshot.from_dict(raw_snapshot)
            cleaned_snapshot = safe_payload(
                parsed_snapshot.to_dict(),
                max_bytes=300_000,
                preserve_keys={"tokens", "max_tokens", "output_tokens", "planner_max_tokens", "template_tokens"},
            )
            parsed_snapshot = DesignContextSnapshot.from_dict(cleaned_snapshot)
            encoded, computed_hash = self._design_json(
                parsed_snapshot.to_dict(), "context_snapshot_json", max_bytes=300_000
            )
            updates["context_snapshot_json"] = encoded
            if "context_snapshot_hash" not in fields:
                fields["context_snapshot_hash"] = computed_hash
        for name in (
            "design_manifest_hash", "quality_report_hash", "planning_hash", "context_snapshot_hash",
            "visual_critique_hash", "transcript_hash",
        ):
            if name in fields:
                updates[name] = str(fields[name] or "").strip().lower()
                if updates[name] and not re.fullmatch(r"[0-9a-f]{64}", updates[name]):
                    raise ContractError(f"{name} is not a valid content hash")
        if "customer_context_id" in fields:
            value = str(fields["customer_context_id"] or "").strip()
            if value and not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", value):
                raise ContractError("customer_context_id is invalid")
            updates["customer_context_id"] = value or None
        if "customer_context_hash" in fields:
            value = str(fields["customer_context_hash"] or "").strip().lower()
            if value and not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ContractError("customer_context_hash is invalid")
            updates["customer_context_hash"] = value
        if "customer_context_revision" in fields:
            value = fields["customer_context_revision"]
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise ContractError("customer_context_revision is invalid")
            updates["customer_context_revision"] = value
        if "design_manifest_json" in fields and fields.get("design_manifest_hash"):
            _, computed_hash = self._design_json(fields["design_manifest_json"], "design_manifest_json")
            if computed_hash != str(fields["design_manifest_hash"]).strip().lower():
                raise ContractError("design_manifest_hash does not match design_manifest_json")
        if "quality_report_json" in fields and fields.get("quality_report_hash"):
            _, computed_hash = self._design_json(fields["quality_report_json"], "quality_report_json")
            if computed_hash != str(fields["quality_report_hash"]).strip().lower():
                raise ContractError("quality_report_hash does not match quality_report_json")
        if "planning_json" in fields and fields.get("planning_hash"):
            _, computed_hash = self._design_json(fields["planning_json"], "planning_json")
            if computed_hash != str(fields["planning_hash"]).strip().lower():
                raise ContractError("planning_hash does not match planning_json")
        if "context_snapshot" in fields and fields.get("context_snapshot_hash"):
            raw_snapshot = fields["context_snapshot"]
            if isinstance(raw_snapshot, DesignContextSnapshot):
                raw_snapshot = raw_snapshot.to_dict()
            parsed_snapshot = DesignContextSnapshot.from_dict(raw_snapshot)
            cleaned_snapshot = safe_payload(
                parsed_snapshot.to_dict(),
                max_bytes=300_000,
                preserve_keys={"tokens", "max_tokens", "output_tokens", "planner_max_tokens", "template_tokens"},
            )
            computed_hash = DesignContextSnapshot.from_dict(cleaned_snapshot).content_hash
            if computed_hash != str(fields["context_snapshot_hash"]).strip().lower():
                raise ContractError("context_snapshot_hash does not match context_snapshot")
        if "context_snapshot" not in fields and fields.get("context_snapshot_hash"):
            current_snapshot = current.get("context_snapshot") or {}
            if not current_snapshot:
                raise ContractError("context_snapshot_hash requires context_snapshot")
            if DesignContextSnapshot.from_dict(current_snapshot).content_hash != str(fields["context_snapshot_hash"]).strip().lower():
                raise ContractError("context_snapshot_hash does not match stored context_snapshot")
        if "parent_run_id" in fields or "operation_kind" in fields:
            raise ContractError("parent_run_id and operation_kind are immutable")
        if "error" in fields:
            updates["error"] = safe_provider_message(fields["error"], max_chars=500)
        if "draft_id" in fields:
            draft_id = fields["draft_id"]
            if draft_id is not None and (isinstance(draft_id, bool) or not isinstance(draft_id, int) or draft_id < 1):
                raise ContractError("draft_id is invalid")
            updates["draft_id"] = draft_id
        for name in ("conversation_id", "source_message_id", "chat_job_id"):
            if name in fields:
                value = fields[name]
                if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                    raise ContractError(f"{name} is invalid")
                updates[name] = value
        if "owner_request" in fields:
            updates["owner_request"] = safe_provider_message(fields["owner_request"], max_chars=20_000)
        if not updates and status is None:
            return current
        if status is not None:
            updates["status"] = DesignRunStatus(status).value
        updates["updated_ts"] = _now()
        with self.conn:
            self.conn.execute(
                f"UPDATE design_runs SET {', '.join(f'{key} = ?' for key in updates)} WHERE run_id = ?",
                [*updates.values(), str(run_id)],
            )
        return self.get_design_run(run_id)

    @_locked
    def transition_design_run(self, run_id: str, status: str, *, error: str | None = None) -> dict[str, Any] | None:
        current = self.get_design_run(run_id)
        if current is None:
            return None
        validate_design_run_transition(current["status"], status)
        if status == DesignRunStatus.CANDIDATE_READY.value and (
            not current.get("candidate_sha") or not current.get("candidate_ref")
        ):
            raise ContractError("candidate_ready requires candidate_sha and candidate_ref")
        updates: dict[str, Any] = {"status": DesignRunStatus(status).value, "updated_ts": _now()}
        if error is not None:
            updates["error"] = safe_provider_message(error, max_chars=500)
        with self.conn:
            self.conn.execute(
                "UPDATE design_runs SET status = ?, error = COALESCE(?, error), updated_ts = ? WHERE run_id = ?",
                (updates["status"], updates.get("error"), updates["updated_ts"], str(run_id)),
            )
        return self.get_design_run(run_id)

    @_locked
    def interrupt_running_design_runs(self, error: str = "interrupted by server restart; retry this run explicitly") -> int:
        """Surface in-progress design work instead of replaying side effects."""
        rows = list(self.conn.execute(
            "SELECT run_id, status, conversation_id, source_message_id, chat_job_id "
            "FROM design_runs WHERE status IN ('building', 'candidate_ready', 'validating') "
            "OR (status = 'planning' AND run_id IN ("
            "SELECT e.run_id FROM design_run_events e WHERE e.id = ("
            "SELECT MAX(last.id) FROM design_run_events last WHERE last.run_id = e.run_id"
            ") AND e.stage IN ('claimed', 'analyzing', 'exploring_direction', 'implementing', 'inspecting', 'critiquing', 'retaining_candidate')"
            "))"
        ))
        if not rows:
            return 0
        now = _now()
        safe_error = safe_provider_message(error, max_chars=500)
        with self.conn:
            for row in rows:
                self.conn.execute(
                    "UPDATE design_runs SET status = ?, error = ?, updated_ts = ? WHERE run_id = ?",
                    (DesignRunStatus.INTERRUPTED.value, safe_error, now, row["run_id"]),
                )
                detail = {
                    "conversation_id": row["conversation_id"],
                    "source_message_id": row["source_message_id"],
                    "chat_job_id": row["chat_job_id"],
                }
                detail_encoded, _ = self._design_json(detail, "design interruption detail", max_bytes=20_000)
                self.conn.execute(
                    "INSERT INTO design_run_events (run_id, stage, message, detail_json, created_ts) VALUES (?, ?, ?, ?, ?)",
                    (row["run_id"], DesignRunStatus.INTERRUPTED.value, safe_error, detail_encoded, now),
                )
        return len(rows)

    @_locked
    def add_design_run_event(
        self,
        run_id: str,
        stage: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> int:
        if self.get_design_run(run_id) is None:
            raise KeyError(f"no such design run: {run_id}")
        stage = str(stage or "").strip()
        if not stage or len(stage) > 60 or not re.fullmatch(r"[A-Za-z0-9._-]+", stage):
            raise ContractError("design event stage is invalid")
        detail_encoded, _ = self._design_json(detail or {}, "design event detail", max_bytes=20_000)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO design_run_events (run_id, stage, message, detail_json, created_ts) VALUES (?, ?, ?, ?, ?)",
                (str(run_id), stage, safe_provider_message(message, max_chars=500), detail_encoded, _now()),
            )
        return cur.lastrowid

    @_locked
    def list_design_run_events(self, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = []
        for row in self.conn.execute(
            "SELECT * FROM design_run_events WHERE run_id = ? ORDER BY id ASC LIMIT ?",
            (str(run_id), max(1, min(int(limit), 1000))),
        ):
            result = dict(row)
            result["detail"] = self._decode_design_json(result.pop("detail_json", "{}"))
            rows.append(result)
        return rows

    # ------------------------------------------------------------------
    # Conversational design intake
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_intake_session_id(session_id: Any) -> str:
        result = str(session_id or "").strip()
        if not result or len(result) > 120 or not re.fullmatch(r"[A-Za-z0-9._:-]+", result):
            raise ContractError("intake session ID is invalid")
        return result

    @staticmethod
    def _validate_optional_intake_id(value: Any, name: str) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ContractError(f"{name} is invalid")
        return value

    @staticmethod
    def _validate_intake_token(value: Any, name: str = "idempotency_key") -> str:
        result = str(value or "").strip()
        if not result or len(result) > 160 or not re.fullmatch(r"[A-Za-z0-9._:-]+", result):
            raise ContractError(f"{name} is invalid")
        return result

    @staticmethod
    def _intake_draft_json(draft: DesignIntakeDraft) -> tuple[str, str]:
        if not isinstance(draft, DesignIntakeDraft):
            raise ContractError("intake draft must be a DesignIntakeDraft")
        draft.validate()
        encoded = canonical_json(draft.to_dict())
        if len(encoded.encode("utf-8")) > 300_000:
            raise ContractError("intake draft exceeds 300000 bytes")
        return encoded, draft.content_hash

    @staticmethod
    def _decode_intake_draft(value: Any) -> dict[str, Any]:
        try:
            decoded = json.loads(value or "{}")
        except (json.JSONDecodeError, TypeError):
            return DesignIntakeDraft.empty().to_dict()
        if not isinstance(decoded, dict):
            return DesignIntakeDraft.empty().to_dict()
        try:
            return DesignIntakeDraft.from_dict(decoded).to_dict()
        except ContractError:
            return DesignIntakeDraft.empty().to_dict()

    @staticmethod
    def _decode_intake_session(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["draft"] = Memory._decode_intake_draft(result.pop("draft_json", "{}"))
        result["status"] = str(result.get("status") or IntakeSessionState.COLLECTING.value)
        result["revision"] = int(result.get("revision") or 0)
        result["confirmed_revision"] = (
            int(result["confirmed_revision"]) if result.get("confirmed_revision") is not None else None
        )
        return result

    @_locked
    def create_design_intake_session(
        self,
        session_id: str,
        draft: DesignIntakeDraft | None = None,
        *,
        conversation_id: int | None = None,
    ) -> dict[str, Any]:
        """Create one durable draft and its first immutable revision."""
        session_id = self._validate_intake_session_id(session_id)
        conversation_id = self._validate_optional_intake_id(conversation_id, "conversation_id")
        draft = draft or DesignIntakeDraft.empty()
        encoded, draft_hash = self._intake_draft_json(draft)
        now = _now()
        status = draft.readiness
        with self.conn:
            try:
                self.conn.execute(
                    "INSERT INTO design_intake_sessions "
                    "(session_id, conversation_id, status, revision, draft_json, draft_hash, created_ts, updated_ts) "
                    "VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
                    (session_id, conversation_id, status, encoded, draft_hash, now, now),
                )
                self.conn.execute(
                    "INSERT INTO design_intake_revisions "
                    "(session_id, revision, draft_json, draft_hash, source_kind, created_ts) "
                    "VALUES (?, 1, ?, ?, 'session_created', ?)",
                    (session_id, encoded, draft_hash, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ContractError("intake session already exists") from exc
        return self.get_design_intake_session(session_id) or {}

    @_locked
    def get_design_intake_session(self, session_id: str) -> dict[str, Any] | None:
        session_id = self._validate_intake_session_id(session_id)
        row = self.conn.execute(
            "SELECT * FROM design_intake_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return self._decode_intake_session(dict(row))

    @_locked
    def import_confirmed_design_intake(
        self,
        session_id: str,
        site_intake: dict[str, Any],
        *,
        source_session_id: str,
        source_revision: int,
        source_revision_id: int | None = None,
        source_draft_hash: str = "",
        site_intake_hash: str = "",
        summary: dict[str, Any] | None = None,
        assets: list[IntakeAssetBinding] | tuple[IntakeAssetBinding, ...] = (),
        conversation_id: int | None = None,
    ) -> dict[str, Any]:
        """Import the exact owner-confirmed intake as a destination baseline."""
        session_id = self._validate_intake_session_id(session_id)
        source_session_id = self._validate_intake_session_id(source_session_id)
        if isinstance(source_revision, bool) or not isinstance(source_revision, int) or source_revision < 1:
            raise ContractError("source_revision is invalid")
        source_revision_id = self._validate_optional_intake_id(source_revision_id, "source_revision_id")
        conversation_id = self._validate_optional_intake_id(conversation_id, "conversation_id")
        intake = SiteIntake.from_dict(site_intake)
        computed_intake_hash = intake.content_hash
        site_intake_hash = str(site_intake_hash or computed_intake_hash).strip().lower()
        if site_intake_hash != computed_intake_hash:
            raise ContractError("imported site intake hash does not match the accepted intake")
        draft = DesignIntakeDraft.from_site_intake(intake)
        encoded_draft, draft_hash = self._intake_draft_json(draft)
        summary_value = dict(summary or {})
        summary_value.update({
            "source_session_id": source_session_id,
            "source_revision": source_revision,
            "source_revision_id": source_revision_id,
            "source_draft_hash": str(source_draft_hash or "").strip().lower(),
        })
        summary_encoded, _ = self._design_json(summary_value, "imported intake summary", max_bytes=100_000)
        site_encoded, _ = self._design_json(intake.to_dict(), "imported site_intake", max_bytes=300_000)
        normalized_assets = [
            item if isinstance(item, IntakeAssetBinding) else IntakeAssetBinding.from_dict(item)
            for item in assets
        ]
        if len({item.asset_id for item in normalized_assets}) != len(normalized_assets):
            raise ContractError("imported intake assets must be unique")
        for item in normalized_assets:
            asset = self.get_media_asset(item.asset_id)
            if asset is None or asset.status.value != "ready" or asset.media_kind.value != "image" or asset.archived_ts:
                raise ContractError("imported intake assets must reference ready images")
        existing = self.get_design_intake_session(session_id)
        if existing is not None:
            revisions = self.list_design_intake_revisions(session_id, limit=500)
            matching = next(
                (
                    item for item in revisions
                    if item.get("site_intake_hash") == site_intake_hash
                    and int(item.get("revision") or 0) == source_revision
                ),
                None,
            )
            if matching is None or existing.get("status") != IntakeSessionState.CONFIRMED.value:
                raise ContractError("destination intake session already contains different content")
            return existing
        now = _now()
        source_kind = "provisioning_import_" + re.sub(r"[^A-Za-z0-9_.-]", "_", source_session_id)[:40]
        with self.conn:
            self.conn.execute(
                "INSERT INTO design_intake_sessions "
                "(session_id, conversation_id, status, revision, draft_json, draft_hash, confirmed_revision, confirmed_hash, confirmed_ts, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, conversation_id, IntakeSessionState.CONFIRMED.value, source_revision, encoded_draft, draft_hash, source_revision, draft_hash, now, now, now),
            )
            self.conn.execute(
                "INSERT INTO design_intake_revisions "
                "(session_id, revision, draft_json, draft_hash, source_kind, site_intake_json, site_intake_hash, summary_json, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, source_revision, encoded_draft, draft_hash, source_kind, site_encoded, site_intake_hash, summary_encoded, now),
            )
            for item in normalized_assets:
                self.conn.execute(
                    "INSERT INTO design_intake_assets "
                    "(session_id, asset_id, position, usage, reference_aspects_json, owner_note, created_ts, updated_ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (session_id, item.asset_id, item.position, item.usage, json.dumps(list(item.reference_aspects)), item.owner_note, now, now),
                )
        return self.get_design_intake_session(session_id) or {}

    @_locked
    def find_design_intake_session_for_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        conversation_id = self._validate_optional_intake_id(conversation_id, "conversation_id")
        if conversation_id is None:
            return None
        row = self.conn.execute(
            "SELECT * FROM design_intake_sessions WHERE conversation_id = ? "
            "ORDER BY updated_ts DESC, id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return self._decode_intake_session(dict(row)) if row else None

    @_locked
    def list_design_intake_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM design_intake_sessions ORDER BY updated_ts DESC, id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        )
        return [self._decode_intake_session(dict(row)) for row in rows]

    @_locked
    def save_design_intake_revision(
        self,
        session_id: str,
        draft: DesignIntakeDraft,
        *,
        source_kind: str = "owner_message",
        source_message_id: int | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Append a draft revision and update the session atomically."""
        session_id = self._validate_intake_session_id(session_id)
        source_message_id = self._validate_optional_intake_id(source_message_id, "source_message_id")
        if expected_revision is not None and (
            isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0
        ):
            raise ContractError("expected_revision is invalid")
        source_kind = str(source_kind or "owner_message").strip().lower()
        if not source_kind or len(source_kind) > 60 or not re.fullmatch(r"[a-z][a-z0-9_.-]*", source_kind):
            raise ContractError("intake revision source_kind is invalid")
        encoded, draft_hash = self._intake_draft_json(draft)
        row = self.conn.execute(
            "SELECT revision, status FROM design_intake_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise ContractError("intake session was not found")
        current_revision = int(row["revision"] or 0)
        if expected_revision is not None and expected_revision != current_revision:
            raise ContractError("intake session revision is stale")
        if str(row["status"] or "") == IntakeSessionState.CONFIRMED.value:
            raise ContractError("confirmed intake revisions are immutable")
        revision = current_revision + 1
        now = _now()
        for _attempt in range(2):
            try:
                with self.conn:
                    self.conn.execute(
                        "INSERT INTO design_intake_revisions "
                        "(session_id, revision, draft_json, draft_hash, source_kind, source_message_id, created_ts) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (session_id, revision, encoded, draft_hash, source_kind, source_message_id, now),
                    )
                    self.conn.execute(
                        "UPDATE design_intake_sessions SET status = ?, revision = ?, draft_json = ?, draft_hash = ?, "
                        "latest_message_id = COALESCE(?, latest_message_id), updated_ts = ?, error = '' WHERE session_id = ?",
                        (draft.readiness, revision, encoded, draft_hash, source_message_id, now, session_id),
                    )
                break
            except sqlite3.IntegrityError:
                # A concurrent writer (e.g. another process holding the store)
                # may have bumped the revision between snapshot and insert. Re-read
                # and retry once at the new revision instead of surfacing an opaque
                # UNIQUE constraint error to the owner conversation.
                fresh = self.conn.execute(
                    "SELECT revision FROM design_intake_sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                if fresh is None or _attempt == 1:
                    raise
                revision = int(fresh["revision"]) + 1
                now = _now()
        return self.get_design_intake_session(session_id) or {}

    @_locked
    def update_design_intake_session(self, session_id: str, **fields: Any) -> dict[str, Any] | None:
        session_id = self._validate_intake_session_id(session_id)
        current = self.get_design_intake_session(session_id)
        if current is None:
            return None
        updates: dict[str, Any] = {}
        if "status" in fields:
            status = str(fields["status"] or "").strip().lower()
            allowed = {item.value for item in IntakeSessionState}
            if status not in allowed:
                raise ContractError("intake session status is invalid")
            updates["status"] = status
        for name in ("latest_message_id", "latest_advice_job_id"):
            if name in fields:
                updates[name] = self._validate_optional_intake_id(fields[name], name)
        if "design_run_id" in fields:
            value = str(fields["design_run_id"] or "").strip()
            if value and (len(value) > 240 or not re.fullmatch(r"[A-Za-z0-9._:-]+", value)):
                raise ContractError("design_run_id is invalid")
            updates["design_run_id"] = value or None
        if "build_started_ts" in fields:
            value = str(fields["build_started_ts"] or "").strip()
            if value:
                try:
                    datetime.datetime.fromisoformat(value)
                except ValueError as exc:
                    raise ContractError("build_started_ts is invalid") from exc
            updates["build_started_ts"] = value or None
        for name in ("error", "build_error"):
            if name in fields:
                updates[name] = safe_provider_message(fields[name], max_chars=500)
        if not updates:
            return current
        updates["updated_ts"] = _now()
        with self.conn:
            self.conn.execute(
                f"UPDATE design_intake_sessions SET {', '.join(f'{key} = ?' for key in updates)} WHERE session_id = ?",
                [*updates.values(), session_id],
            )
        return self.get_design_intake_session(session_id)

    @_locked
    def confirm_design_intake(
        self,
        session_id: str,
        *,
        revision: int,
        draft_hash: str,
        site_intake_json: dict[str, Any] | None = None,
        summary_json: dict[str, Any] | None = None,
        confirmation_text: str = "Build this",
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> dict[str, Any]:
        """Freeze the exact revision that the owner approved for building."""
        session_id = self._validate_intake_session_id(session_id)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ContractError("intake revision is invalid")
        draft_hash = str(draft_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", draft_hash):
            raise ContractError("intake draft hash is invalid")
        row = self.conn.execute(
            "SELECT revision, draft_hash, status FROM design_intake_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise ContractError("intake session was not found")
        if int(row["revision"] or 0) != revision or str(row["draft_hash"] or "") != draft_hash:
            raise ContractError("intake confirmation does not match the latest revision")
        if str(row["status"] or "") not in {
            IntakeSessionState.READY_TO_BUILD.value,
            IntakeSessionState.CONFIRMED.value,
        }:
            raise ContractError("intake is not ready to confirm")
        if site_intake_json is not None:
            if not isinstance(site_intake_json, dict):
                raise ContractError("site_intake_json must be an object")
            if not isinstance(summary_json, dict):
                raise ContractError("summary_json must be an object")
            idempotency_key = self._validate_intake_token(idempotency_key, "confirmation idempotency_key")
            request_hash = str(request_hash or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", request_hash):
                raise ContractError("confirmation request_hash is invalid")
            existing = self.get_design_intake_operation(session_id, "confirm", idempotency_key)
            if existing is not None:
                if existing.get("request_hash") != request_hash:
                    raise ContractError("confirmation idempotency_key was already used for a different request")
                response = existing.get("response") if isinstance(existing.get("response"), dict) else {}
                result = self.get_design_intake_session(session_id) or {}
                result.update(response)
                return result
            if str(row["status"] or "") == IntakeSessionState.CONFIRMED.value:
                frozen_revision = int(row["revision"] or 0)
                frozen = self.conn.execute(
                    "SELECT revision, site_intake_hash, confirmation_message_id "
                    "FROM design_intake_revisions WHERE session_id = ? AND source_kind = 'owner_confirmation' "
                    "AND revision = ? ORDER BY id DESC LIMIT 1",
                    (session_id, frozen_revision),
                ).fetchone()
                if frozen is not None:
                    response = {
                        "confirmed_revision": int(frozen["revision"]),
                        "confirmed_revision_id": None,
                        "confirmation_message_id": frozen["confirmation_message_id"],
                        "site_intake_hash": frozen["site_intake_hash"],
                    }
                    frozen_id = self.conn.execute(
                        "SELECT id FROM design_intake_revisions WHERE session_id = ? AND source_kind = 'owner_confirmation' "
                        "AND revision = ? ORDER BY id DESC LIMIT 1",
                        (session_id, int(frozen["revision"])),
                    ).fetchone()
                    if frozen_id is not None:
                        response["confirmed_revision_id"] = frozen_id["id"]
                    result = self.get_design_intake_session(session_id) or {}
                    result.update(response)
                    return result
            site_encoded, site_hash = self._design_json(site_intake_json, "site_intake_json", max_bytes=300_000)
            summary_encoded, _ = self._design_json(summary_json, "summary_json", max_bytes=100_000)
            confirmation_text = safe_provider_message(confirmation_text, max_chars=2_000).strip()
            if not confirmation_text:
                raise ContractError("confirmation text must not be empty")
            now = _now()
            with self.conn:
                message_cur = self.conn.execute(
                    "INSERT INTO chat_messages (conversation_id, ts, role, text, attachments_json) "
                    "SELECT conversation_id, ?, 'user', ?, '[]' FROM design_intake_sessions WHERE session_id = ?",
                    (now, confirmation_text, session_id),
                )
                final_revision = int(row["revision"] or 0) + 1
                cur = self.conn.execute(
                    "INSERT INTO design_intake_revisions "
                    "(session_id, revision, draft_json, draft_hash, source_kind, source_message_id, "
                    "site_intake_json, site_intake_hash, summary_json, confirmation_message_id, created_ts) "
                    "SELECT session_id, ?, draft_json, draft_hash, 'owner_confirmation', ?, ?, ?, ?, ?, ? "
                    "FROM design_intake_sessions WHERE session_id = ?",
                    (final_revision, message_cur.lastrowid, site_encoded, site_hash, summary_encoded,
                     message_cur.lastrowid, now, session_id),
                )
                response = {
                    "confirmed_revision": final_revision,
                    "confirmed_revision_id": cur.lastrowid,
                    "confirmation_message_id": message_cur.lastrowid,
                    "site_intake_hash": site_hash,
                }
                response_encoded = canonical_json(response)
                self.conn.execute(
                    "UPDATE design_intake_sessions SET status = 'confirmed', revision = ?, confirmed_revision = ?, "
                    "confirmed_hash = ?, confirmed_ts = COALESCE(confirmed_ts, ?), latest_message_id = ?, "
                    "updated_ts = ? WHERE session_id = ?",
                    (final_revision, final_revision, draft_hash, now, message_cur.lastrowid, now, session_id),
                )
                self.conn.execute(
                    "INSERT INTO design_intake_operations "
                    "(session_id, operation, idempotency_key, request_hash, response_json, created_ts) "
                    "VALUES (?, 'confirm', ?, ?, ?, ?)",
                    (session_id, idempotency_key, request_hash, response_encoded, now),
                )
            result = self.get_design_intake_session(session_id) or {}
            result.update(response)
            return result
        now = _now()
        with self.conn:
            self.conn.execute(
                "UPDATE design_intake_sessions SET status = 'confirmed', confirmed_revision = ?, "
                "confirmed_hash = ?, confirmed_ts = COALESCE(confirmed_ts, ?), updated_ts = ? WHERE session_id = ?",
                (revision, draft_hash, now, now, session_id),
            )
        return self.get_design_intake_session(session_id) or {}

    @_locked
    def get_design_intake_operation(
        self,
        session_id: str,
        operation: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        session_id = self._validate_intake_session_id(session_id)
        operation = str(operation or "").strip().lower()
        if not operation or len(operation) > 60 or not re.fullmatch(r"[a-z][a-z0-9_.-]*", operation):
            raise ContractError("intake operation is invalid")
        idempotency_key = self._validate_intake_token(idempotency_key)
        row = self.conn.execute(
            "SELECT * FROM design_intake_operations WHERE session_id = ? AND operation = ? AND idempotency_key = ?",
            (session_id, operation, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        try:
            result["response"] = json.loads(result.pop("response_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            result["response"] = {}
        return result

    @_locked
    def reserve_design_intake_build(
        self,
        session_id: str,
        *,
        idempotency_key: str,
        request_hash: str,
        confirmed_revision_id: int,
        confirmed_revision: int,
        reserved_run_id: str,
        force_new: bool = False,
    ) -> dict[str, Any]:
        """Reserve one build before calling the external builder.

        The unique request index closes the race where two HTTP requests both
        observe that the session has no current run and submit two candidates.
        A reservation without a run is returned to the second caller as an
        in-flight operation; it must never submit a second build.
        """
        session_id = self._validate_intake_session_id(session_id)
        idempotency_key = self._validate_intake_token(idempotency_key, "build idempotency_key")
        request_hash = str(request_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", request_hash):
            raise ContractError("build request_hash is invalid")
        if isinstance(confirmed_revision_id, bool) or not isinstance(confirmed_revision_id, int) or confirmed_revision_id < 1:
            raise ContractError("confirmed_revision_id is invalid")
        if isinstance(confirmed_revision, bool) or not isinstance(confirmed_revision, int) or confirmed_revision < 1:
            raise ContractError("confirmed_revision is invalid")
        reserved_run_id = str(reserved_run_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", reserved_run_id):
            raise ContractError("reserved run_id is invalid")
        force_new = bool(force_new)
        response = {
            "confirmed_revision_id": confirmed_revision_id,
            "confirmed_revision": confirmed_revision,
            "run_id": reserved_run_id,
        }
        with self.conn:
            existing = self.conn.execute(
                "SELECT * FROM design_intake_operations WHERE session_id = ? AND operation = 'build' "
                "AND idempotency_key = ?",
                (session_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if str(existing["request_hash"] or "") != request_hash:
                    raise ContractError("build idempotency_key was already used for a different request")
                result = self.get_design_intake_operation(session_id, "build", idempotency_key) or {}
                result["created"] = False
                return result
            if not force_new:
                existing = self.conn.execute(
                    "SELECT * FROM design_intake_operations WHERE session_id = ? AND operation = 'build' "
                    "AND request_hash = ? AND force_new = 0 AND "
                    "(state IN ('reserved', 'submitted') OR response_json LIKE '%\"run_id\"%') "
                    "ORDER BY id DESC LIMIT 1",
                    (session_id, request_hash),
                ).fetchone()
                if existing is not None:
                    result = self.get_design_intake_operation(session_id, "build", existing["idempotency_key"]) or {}
                    result["created"] = False
                    return result
            now = _now()
            cur = self.conn.execute(
                "INSERT INTO design_intake_operations "
                "(session_id, operation, idempotency_key, request_hash, response_json, created_ts, "
                "run_id, confirmed_revision_id, confirmed_revision, state, force_new, error, updated_ts) "
                "VALUES (?, 'build', ?, ?, ?, ?, ?, ?, ?, 'reserved', ?, '', ?)",
                (session_id, idempotency_key, request_hash, canonical_json(response), now,
                 reserved_run_id, confirmed_revision_id, confirmed_revision, int(force_new), now),
            )
        result = self.get_design_intake_operation(session_id, "build", idempotency_key) or {
            "id": cur.lastrowid,
            "session_id": session_id,
            "operation": "build",
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
            "response": response,
            "state": "reserved",
        }
        result["created"] = True
        return result

    @_locked
    def claim_design_intake_build_submission(
        self,
        session_id: str,
        idempotency_key: str,
        request_hash: str,
        *,
        stale_after_seconds: int = 900,
    ) -> dict[str, Any] | None:
        """Reclaim a reservation left behind before external submission."""
        session_id = self._validate_intake_session_id(session_id)
        idempotency_key = self._validate_intake_token(idempotency_key, "build idempotency_key")
        request_hash = str(request_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", request_hash):
            raise ContractError("build request_hash is invalid")
        try:
            stale_after = max(1, min(int(stale_after_seconds), 86_400))
        except (TypeError, ValueError) as exc:
            raise ContractError("stale_after_seconds is invalid") from exc
        row = self.conn.execute(
            "SELECT * FROM design_intake_operations WHERE session_id = ? AND operation = 'build' "
            "AND idempotency_key = ? AND request_hash = ?",
            (session_id, idempotency_key, request_hash),
        ).fetchone()
        if row is None:
            return None
        result = self.get_design_intake_operation(session_id, "build", idempotency_key) or {}
        if str(row["state"] or "") != "reserved":
            result["claimed"] = False
            return result
        updated_ts = str(row["updated_ts"] or row["created_ts"] or "")
        stale = True
        try:
            updated = datetime.datetime.fromisoformat(updated_ts.replace("Z", "+00:00"))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=datetime.timezone.utc)
            stale = (datetime.datetime.now(datetime.timezone.utc) - updated).total_seconds() >= stale_after
        except ValueError:
            pass
        if not stale:
            result["claimed"] = False
            return result
        now = _now()
        with self.conn:
            changed = self.conn.execute(
                "UPDATE design_intake_operations SET updated_ts = ? WHERE session_id = ? AND operation = 'build' "
                "AND idempotency_key = ? AND request_hash = ? AND state = 'reserved' AND updated_ts = ?",
                (now, session_id, idempotency_key, request_hash, row["updated_ts"]),
            ).rowcount
        result = self.get_design_intake_operation(session_id, "build", idempotency_key) or result
        result["claimed"] = changed == 1
        return result

    @_locked
    def complete_design_intake_build(
        self,
        session_id: str,
        idempotency_key: str,
        request_hash: str,
        *,
        run_id: str,
    ) -> dict[str, Any] | None:
        session_id = self._validate_intake_session_id(session_id)
        idempotency_key = self._validate_intake_token(idempotency_key, "build idempotency_key")
        request_hash = str(request_hash or "").strip().lower()
        run_id = str(run_id or "").strip()
        if not run_id:
            raise ContractError("build run_id is required")
        row = self.conn.execute(
            "SELECT response_json FROM design_intake_operations WHERE session_id = ? AND operation = 'build' "
            "AND idempotency_key = ? AND request_hash = ?",
            (session_id, idempotency_key, request_hash),
        ).fetchone()
        if row is None:
            raise ContractError("build reservation was not found")
        try:
            response = json.loads(row["response_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            response = {}
        response["run_id"] = run_id
        now = _now()
        with self.conn:
            self.conn.execute(
                "UPDATE design_intake_operations SET response_json = ?, run_id = ?, state = 'submitted', "
                "error = '', updated_ts = ? WHERE session_id = ? AND operation = 'build' AND idempotency_key = ?",
                (canonical_json(response), run_id, now, session_id, idempotency_key),
            )
        return self.get_design_intake_operation(session_id, "build", idempotency_key)

    @_locked
    def fail_design_intake_build(
        self,
        session_id: str,
        idempotency_key: str,
        request_hash: str,
        error: str,
    ) -> dict[str, Any] | None:
        session_id = self._validate_intake_session_id(session_id)
        idempotency_key = self._validate_intake_token(idempotency_key, "build idempotency_key")
        request_hash = str(request_hash or "").strip().lower()
        now = _now()
        with self.conn:
            self.conn.execute(
                "UPDATE design_intake_operations SET state = 'failed', error = ?, updated_ts = ? "
                "WHERE session_id = ? AND operation = 'build' AND idempotency_key = ? AND request_hash = ?",
                (safe_provider_message(error, max_chars=500), now, session_id, idempotency_key, request_hash),
            )
        return self.get_design_intake_operation(session_id, "build", idempotency_key)

    @_locked
    def record_design_intake_operation(
        self,
        session_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        session_id = self._validate_intake_session_id(session_id)
        operation = str(operation or "").strip().lower()
        if not operation or len(operation) > 60 or not re.fullmatch(r"[a-z][a-z0-9_.-]*", operation):
            raise ContractError("intake operation is invalid")
        idempotency_key = self._validate_intake_token(idempotency_key)
        request_hash = str(request_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", request_hash):
            raise ContractError("intake operation request_hash is invalid")
        if not isinstance(response, dict):
            raise ContractError("intake operation response must be an object")
        encoded = canonical_json(response)
        if len(encoded.encode("utf-8")) > 100_000:
            raise ContractError("intake operation response is too large")
        now = _now()
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO design_intake_operations "
                    "(session_id, operation, idempotency_key, request_hash, response_json, created_ts) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, operation, idempotency_key, request_hash, encoded, now),
                )
        except sqlite3.IntegrityError as exc:
            existing = self.get_design_intake_operation(session_id, operation, idempotency_key)
            if existing is None or existing.get("request_hash") != request_hash:
                raise ContractError("intake operation idempotency_key was already used for a different request") from exc
            return existing
        return self.get_design_intake_operation(session_id, operation, idempotency_key) or {
            "session_id": session_id,
            "operation": operation,
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
            "response": response,
        }

    @_locked
    def list_design_intake_revisions(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        session_id = self._validate_intake_session_id(session_id)
        rows = self.conn.execute(
            "SELECT * FROM design_intake_revisions WHERE session_id = ? ORDER BY revision ASC LIMIT ?",
            (session_id, max(1, min(int(limit), 500))),
        )
        result = []
        for row in rows:
            item = dict(row)
            item["draft"] = self._decode_intake_draft(item.pop("draft_json", "{}"))
            item["site_intake"] = self._decode_design_json(item.pop("site_intake_json", "{}"))
            item["summary"] = self._decode_design_json(item.pop("summary_json", "{}"))
            result.append(item)
        return result

    @_locked
    def replace_design_intake_assets(
        self,
        session_id: str,
        assets: list[IntakeAssetBinding] | tuple[IntakeAssetBinding, ...],
    ) -> list[dict[str, Any]]:
        session_id = self._validate_intake_session_id(session_id)
        session = self.get_design_intake_session(session_id)
        if session is None:
            raise ContractError("intake session was not found")
        if not isinstance(assets, (list, tuple)) or len(assets) > 20:
            raise ContractError("intake assets must contain at most 20 items")
        normalized = [item if isinstance(item, IntakeAssetBinding) else IntakeAssetBinding.from_dict(item) for item in assets]
        if len({item.asset_id for item in normalized}) != len(normalized):
            raise ContractError("an intake asset cannot be selected twice")
        if len({item.position for item in normalized}) != len(normalized):
            raise ContractError("intake asset positions must be unique")
        for item in normalized:
            asset = self.get_media_asset(item.asset_id)
            if asset is None or asset.status.value != "ready" or asset.media_kind.value != "image" or asset.archived_ts:
                raise ContractError("only ready, unarchived images can be bound to intake")
        normalized = sorted(normalized, key=lambda item: item.position)
        current = tuple(
            IntakeAssetBinding.from_dict({
                "asset_id": row["asset_id"],
                "position": row["position"],
                "usage": row["usage"],
                "reference_aspects": row.get("reference_aspects") or [],
                "owner_note": row.get("owner_note") or "",
            })
            for row in self.list_design_intake_assets(session_id)
        )
        draft = DesignIntakeDraft.from_dict(session.get("draft") or {})
        if current == tuple(normalized) and draft.assets == tuple(normalized):
            return self.list_design_intake_assets(session_id)

        updated_draft = replace(draft, assets=tuple(normalized))
        encoded, draft_hash = self._intake_draft_json(updated_draft)
        revision = int(session.get("revision") or 0) + 1
        status = updated_draft.readiness
        reset_build = str(session.get("status") or "") == IntakeSessionState.CONFIRMED.value
        if reset_build:
            status = IntakeSessionState.COLLECTING.value
        now = _now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO design_intake_revisions "
                "(session_id, revision, draft_json, draft_hash, source_kind, created_ts) "
                "VALUES (?, ?, ?, ?, 'asset_update', ?)",
                (session_id, revision, encoded, draft_hash, now),
            )
            self.conn.execute("DELETE FROM design_intake_assets WHERE session_id = ?", (session_id,))
            for item in normalized:
                self.conn.execute(
                    "INSERT INTO design_intake_assets "
                    "(session_id, asset_id, position, usage, reference_aspects_json, owner_note, created_ts, updated_ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (session_id, item.asset_id, item.position, item.usage, json.dumps(list(item.reference_aspects)),
                     item.owner_note, now, now),
                )
            self.conn.execute(
                "UPDATE design_intake_sessions SET status = ?, revision = ?, draft_json = ?, draft_hash = ?, "
                "design_run_id = ?, build_started_ts = ?, build_error = ?, updated_ts = ? WHERE session_id = ?",
                (status, revision, encoded, draft_hash,
                 None if reset_build else session.get("design_run_id"),
                 None if reset_build else session.get("build_started_ts"),
                 "" if reset_build else str(session.get("build_error") or ""), now, session_id),
            )
        return self.list_design_intake_assets(session_id)

    @_locked
    def list_design_intake_assets(self, session_id: str) -> list[dict[str, Any]]:
        session_id = self._validate_intake_session_id(session_id)
        rows = self.conn.execute(
            "SELECT * FROM design_intake_assets WHERE session_id = ? ORDER BY position ASC, id ASC", (session_id,)
        )
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["reference_aspects"] = json.loads(item.pop("reference_aspects_json") or "[]")
            except (json.JSONDecodeError, TypeError):
                item["reference_aspects"] = []
            result.append(item)
        return result

    @_locked
    def record_design_intake_feedback(
        self,
        session_id: str,
        kind: str,
        *,
        notes: str = "",
        run_id: str | None = None,
    ) -> int:
        session_id = self._validate_intake_session_id(session_id)
        if self.get_design_intake_session(session_id) is None:
            raise ContractError("intake session was not found")
        kind = str(kind or "").strip().lower()
        if kind not in {"fits", "small_improvements", "redesign"}:
            raise ContractError("intake feedback kind is invalid")
        if run_id is not None:
            run_id = str(run_id).strip()
            if not run_id or len(run_id) > 120 or not re.fullmatch(r"[A-Za-z0-9._:-]+", run_id):
                raise ContractError("feedback run_id is invalid")
        if not run_id:
            session = self.get_design_intake_session(session_id) or {}
            run_id = str(session.get("design_run_id") or "").strip()
        if not run_id or self.get_design_run(run_id) is None:
            raise ContractError("feedback must reference a design run")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO design_feedback (run_id, session_id, disposition, message, created_ts) VALUES (?, ?, ?, ?, ?)",
                (run_id, session_id, kind, safe_provider_message(notes, max_chars=2_000), _now()),
            )
        return cur.lastrowid

    @_locked
    def list_design_intake_feedback(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        session_id = self._validate_intake_session_id(session_id)
        bounded = max(1, min(int(limit), 200))
        result = []
        for row in self.conn.execute(
            "SELECT id, session_id, run_id, disposition, message, created_ts "
            "FROM design_feedback WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, bounded),
        ):
            item = dict(row)
            item["kind"] = item["disposition"]
            item["notes"] = item["message"]
            result.append(item)
        if len(result) < bounded:
            for row in self.conn.execute(
                "SELECT * FROM design_intake_feedback WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, bounded - len(result)),
            ):
                result.append(dict(row))
        return result[:bounded]

    @_locked
    def save_customer_genesis_revision(
        self,
        genesis: CustomerAdaGenesis,
        *,
        source_kind: str = "genesis_update",
        expected_revision: int | None = None,
        accepted: bool = False,
    ) -> dict[str, Any]:
        """Persist one immutable customer-Ada genesis revision."""
        if not isinstance(genesis, CustomerAdaGenesis):
            raise ContractError("genesis must be a CustomerAdaGenesis")
        source_kind = str(source_kind or "genesis_update").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,59}", source_kind):
            raise ContractError("genesis source_kind is invalid")
        current = self.conn.execute(
            "SELECT revision FROM customer_genesis_revisions ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        current_revision = int(current["revision"]) if current else 0
        if expected_revision is not None and expected_revision != current_revision:
            raise ContractError("genesis revision is stale")
        if genesis.revision != current_revision + 1:
            raise ContractError("genesis revision must increment by one")
        encoded, content_hash = self._design_json(genesis.to_dict(), "genesis_json", max_bytes=200_000)
        now = _now()
        with self.conn:
            if accepted:
                self.conn.execute("UPDATE customer_genesis_revisions SET accepted = 0")
            self.conn.execute(
                "INSERT INTO customer_genesis_revisions (revision, genesis_json, genesis_hash, source_kind, accepted, created_ts) VALUES (?, ?, ?, ?, ?, ?)",
                (genesis.revision, encoded, content_hash, source_kind, int(accepted), now),
            )
        return self.get_customer_genesis_revision(genesis.revision) or {}

    @_locked
    def get_customer_genesis_revision(self, revision: int | None = None) -> dict[str, Any] | None:
        if revision is None:
            row = self.conn.execute(
                "SELECT * FROM customer_genesis_revisions ORDER BY revision DESC, id DESC LIMIT 1"
            ).fetchone()
        else:
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise ContractError("genesis revision is invalid")
            row = self.conn.execute(
                "SELECT * FROM customer_genesis_revisions WHERE revision = ?", (revision,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["genesis"] = CustomerAdaGenesis.from_dict(json.loads(result.pop("genesis_json") or "{}"))
        result["accepted"] = bool(result.get("accepted"))
        return result

    @_locked
    def list_customer_genesis_revisions(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT revision FROM customer_genesis_revisions ORDER BY revision ASC, id ASC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [self.get_customer_genesis_revision(int(row["revision"])) for row in rows if row]

    @_locked
    def accept_customer_genesis_revision(self, revision: int) -> dict[str, Any] | None:
        current = self.get_customer_genesis_revision(revision)
        if current is None:
            raise ContractError("genesis revision was not found")
        with self.conn:
            self.conn.execute("UPDATE customer_genesis_revisions SET accepted = CASE WHEN revision = ? THEN 1 ELSE 0 END", (revision,))
        return self.get_customer_genesis_revision(revision)

    @_locked
    def save_research_source(self, source: ResearchSource) -> dict[str, Any]:
        if not isinstance(source, ResearchSource):
            raise ContractError("research source must be a ResearchSource")
        encoded = canonical_json(source.to_dict())
        source_hash = canonical_hash(source.to_dict())
        now = _now()
        existing = self.conn.execute("SELECT source_hash, source_json, excluded FROM research_sources WHERE source_id = ?", (source.source_id,)).fetchone()
        if existing is not None:
            if existing["source_hash"] != source_hash:
                raise ContractError("research source ID was used for different content")
            result = source.to_dict()
            result["source_hash"] = source_hash
            result["excluded"] = bool(existing["excluded"])
            return result
        with self.conn:
            self.conn.execute(
                "INSERT INTO research_sources (source_id, source_json, source_hash, excluded, created_ts, updated_ts) VALUES (?, ?, ?, 0, ?, ?)",
                (source.source_id, encoded, source_hash, now, now),
            )
        result = source.to_dict()
        result["source_hash"] = source_hash
        result["excluded"] = False
        return result

    @_locked
    def get_research_source(self, source_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM research_sources WHERE source_id = ?", (str(source_id or "").strip(),)).fetchone()
        if row is None:
            return None
        result = ResearchSource.from_dict(json.loads(row["source_json"] or "{}" )).to_dict()
        result.update({"source_hash": row["source_hash"], "excluded": bool(row["excluded"])})
        return result

    @_locked
    def list_research_sources(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT source_id FROM research_sources ORDER BY created_ts ASC, source_id ASC LIMIT ?", (max(1, min(int(limit), 500)),)).fetchall()
        return [self.get_research_source(row["source_id"]) for row in rows if row]

    @_locked
    def exclude_research_source(self, source_id: str, excluded: bool = True) -> dict[str, Any] | None:
        if self.get_research_source(source_id) is None:
            raise ContractError("research source was not found")
        with self.conn:
            self.conn.execute("UPDATE research_sources SET excluded = ?, updated_ts = ? WHERE source_id = ?", (int(bool(excluded)), _now(), str(source_id).strip()))
        return self.get_research_source(source_id)

    @_locked
    def update_research_source(self, source_id: str, **changes: Any) -> dict[str, Any]:
        """Persist owner-approved source disposition without exposing SQL."""
        current = self.get_research_source(source_id)
        if current is None:
            raise ContractError("research source was not found")
        source_data = {
            key: current[key]
            for key in ("source_id", "kind", "url", "feed_url", "title", "discovered_by", "language", "trust_state", "ongoing_subscription", "fetched_at", "content_hash")
        }
        allowed = {"trust_state", "ongoing_subscription", "title", "language", "fetched_at", "content_hash"}
        if set(changes) - allowed:
            raise ContractError("research source update contains unsupported fields")
        source_data.update({key: value for key, value in changes.items() if key in allowed})
        source = ResearchSource.from_dict(source_data)
        encoded = canonical_json(source.to_dict())
        source_hash = canonical_hash(source.to_dict())
        with self.conn:
            self.conn.execute(
                "UPDATE research_sources SET source_json = ?, source_hash = ?, excluded = ?, updated_ts = ? WHERE source_id = ?",
                (encoded, source_hash, int(source.trust_state == "excluded"), _now(), source.source_id),
            )
        result = source.to_dict()
        result.update({"source_hash": source_hash, "excluded": source.trust_state == "excluded"})
        return result

    @_locked
    def save_research_finding(self, finding: ResearchFinding) -> dict[str, Any]:
        if not isinstance(finding, ResearchFinding):
            raise ContractError("research finding must be a ResearchFinding")
        if self.get_research_source(finding.source_id) is None:
            raise ContractError("research finding source was not found")
        encoded = canonical_json(finding.to_dict())
        content_hash = canonical_hash(finding.to_dict())
        existing = self.conn.execute("SELECT finding_hash, finding_json FROM research_findings WHERE finding_id = ?", (finding.finding_id,)).fetchone()
        if existing is not None:
            if existing["finding_hash"] != content_hash:
                raise ContractError("research finding ID was used for different content")
            return finding.to_dict()
        with self.conn:
            self.conn.execute(
                "INSERT INTO research_findings (finding_id, source_id, finding_json, finding_hash, created_ts) VALUES (?, ?, ?, ?, ?)",
                (finding.finding_id, finding.source_id, encoded, content_hash, _now()),
            )
        return finding.to_dict()

    @_locked
    def list_research_findings(self, limit: int = 200) -> list[ResearchFinding]:
        rows = self.conn.execute("SELECT finding_json FROM research_findings ORDER BY created_ts ASC, finding_id ASC LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
        return [ResearchFinding.from_dict(json.loads(row["finding_json"] or "{}")) for row in rows]

    @_locked
    def append_incubation_activity(self, activity: IncubationActivity) -> dict[str, Any]:
        """Append one immutable owner-safe activity record."""
        if not isinstance(activity, IncubationActivity):
            raise ContractError("activity must be an IncubationActivity")
        payload = activity.to_dict()
        encoded = canonical_json(payload)
        activity_hash = canonical_hash(payload)
        existing = self.conn.execute(
            "SELECT * FROM incubation_activity WHERE activity_id = ?", (activity.activity_id,)
        ).fetchone()
        if existing is not None:
            if existing["activity_hash"] != activity_hash:
                raise ContractError("activity ID was used for different content")
            return self._decode_incubation_activity(existing)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO incubation_activity ("
                "activity_id, occurred_at, category, kind, state, summary, provenance, confidence, detail_json, "
                "conversation_id, message_id, chat_job_id, intake_session_id, intake_revision, research_request_id, "
                "source_id, finding_ids_json, genesis_revision, design_run_id, provider_id, activity_hash"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    activity.activity_id,
                    activity.occurred_at,
                    activity.category,
                    activity.kind,
                    activity.state,
                    activity.summary,
                    activity.provenance,
                    activity.confidence,
                    canonical_json(activity.detail),
                    activity.conversation_id,
                    activity.message_id,
                    activity.chat_job_id,
                    activity.intake_session_id,
                    activity.intake_revision,
                    activity.research_request_id,
                    activity.source_id,
                    canonical_json(list(activity.finding_ids)),
                    activity.genesis_revision,
                    activity.design_run_id,
                    activity.provider_id,
                    activity_hash,
                ),
            )
        row = self.conn.execute("SELECT * FROM incubation_activity WHERE id = ?", (cur.lastrowid,)).fetchone()
        if row is None:
            raise ContractError("activity append was not persisted")
        return self._decode_incubation_activity(row)

    @staticmethod
    def _decode_incubation_activity(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        try:
            result["detail"] = json.loads(result.pop("detail_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            result["detail"] = {}
        try:
            finding_ids = json.loads(result.pop("finding_ids_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            finding_ids = []
        result["finding_ids"] = finding_ids if isinstance(finding_ids, list) else []
        result.pop("activity_hash", None)
        result["schema_version"] = 1
        return result

    @staticmethod
    def _activity_cursor(value: Any, name: str) -> int | None:
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            raise ContractError(f"{name} is invalid")
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"{name} is invalid") from exc
        if result < 0 or str(value).strip() != str(result):
            raise ContractError(f"{name} is invalid")
        return result

    @_locked
    def list_incubation_activity(
        self,
        *,
        after_id: int | str | None = None,
        before_id: int | str | None = None,
        limit: int = 100,
        categories: tuple[str, ...] | list[str] = (),
    ) -> dict[str, Any]:
        """Return a bounded activity window with monotonic numeric cursors."""
        after = self._activity_cursor(after_id, "after_id")
        before = self._activity_cursor(before_id, "before_id")
        if after is not None and before is not None:
            raise ContractError("after_id and before_id cannot be combined")
        bounded = max(1, min(int(limit), 500))
        if isinstance(categories, str):
            categories = (categories,)
        normalized_categories = tuple(str(item or "").strip().lower() for item in categories)
        allowed_categories = {item.value for item in IncubationActivityCategory}
        if any(item not in allowed_categories for item in normalized_categories):
            raise ContractError("activity category is invalid")

        clauses: list[str] = []
        params: list[Any] = []
        if after is not None:
            clauses.append("id > ?")
            params.append(after)
        elif before is not None:
            clauses.append("id < ?")
            params.append(before)
        if normalized_categories:
            clauses.append("category IN (" + ",".join("?" for _ in normalized_categories) + ")")
            params.extend(normalized_categories)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        direction = "ASC" if after is not None else "DESC"
        rows = self.conn.execute(
            f"SELECT * FROM incubation_activity{where} ORDER BY id {direction} LIMIT ?",
            [*params, bounded + 1],
        ).fetchall()
        has_more = len(rows) > bounded
        rows = rows[:bounded]
        if after is None:
            rows = list(reversed(rows))
        activities = [self._decode_incubation_activity(row) for row in rows]
        total = self.conn.execute(
            f"SELECT COUNT(*) AS count FROM incubation_activity{where}", params
        ).fetchone()["count"]
        return {
            "activities": activities,
            "next_cursor": str(activities[-1]["id"]) if activities else None,
            "previous_cursor": str(activities[0]["id"]) if activities else None,
            "has_more": has_more,
            "total": int(total),
        }

    @_locked
    def get_incubation_activity(self, activity_id: str | int) -> dict[str, Any] | None:
        value = str(activity_id or "").strip()
        if not value:
            return None
        if value.isdigit():
            row = self.conn.execute("SELECT * FROM incubation_activity WHERE id = ?", (int(value),)).fetchone()
        else:
            row = self.conn.execute("SELECT * FROM incubation_activity WHERE activity_id = ?", (value,)).fetchone()
        return self._decode_incubation_activity(row) if row else None

    @_locked
    def save_research_request(self, request: ResearchRequest) -> dict[str, Any]:
        if not isinstance(request, ResearchRequest):
            raise ContractError("research request must be a ResearchRequest")
        payload = request.to_dict()
        encoded = canonical_json(payload)
        request_hash = canonical_hash(payload)
        existing = self.conn.execute(
            "SELECT request_hash FROM research_requests WHERE request_id = ?", (request.request_id,)
        ).fetchone()
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise ContractError("research request ID was used for different content")
            return self.get_research_request(request.request_id) or {}
        duplicate = self.conn.execute(
            "SELECT request_id FROM research_requests WHERE dedupe_key = ?", (request.dedupe_key,)
        ).fetchone()
        if duplicate is not None:
            return self.get_research_request(duplicate["request_id"]) or {}
        with self.conn:
            self.conn.execute(
                "INSERT INTO research_requests (request_id, dedupe_key, request_json, request_hash, status, created_ts, updated_ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (request.request_id, request.dedupe_key, encoded, request_hash, request.status, request.created_at, request.updated_at),
            )
        return self.get_research_request(request.request_id) or {}

    @_locked
    def get_research_request(self, request_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM research_requests WHERE request_id = ?", (str(request_id or "").strip(),)
        ).fetchone()
        if row is None:
            return None
        request = ResearchRequest.from_dict(json.loads(row["request_json"] or "{}"))
        result = request.to_dict()
        result.update({"request_hash": row["request_hash"]})
        return result

    @_locked
    def get_research_request_by_dedupe_key(self, dedupe_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT request_id FROM research_requests WHERE dedupe_key = ?", (str(dedupe_key or "").strip(),)
        ).fetchone()
        return self.get_research_request(row["request_id"]) if row else None

    @_locked
    def update_research_request(self, request_id: str, **changes: Any) -> dict[str, Any]:
        current = self.get_research_request(request_id)
        if current is None:
            raise ContractError("research request was not found")
        allowed = {
            "status", "trigger", "intake_revision", "owner_language", "subjects", "markets",
            "candidate_communities", "query_terms_by_language", "source_ids", "finding_ids", "insight_ids", "error",
        }
        if set(changes) - allowed:
            raise ContractError("research request update contains unsupported fields")
        current.pop("request_hash", None)
        current.update(changes)
        current["updated_at"] = _now()
        request = ResearchRequest.from_dict(current)
        payload = request.to_dict()
        encoded = canonical_json(payload)
        request_hash = canonical_hash(payload)
        with self.conn:
            self.conn.execute(
                "UPDATE research_requests SET request_json = ?, request_hash = ?, status = ?, updated_ts = ? WHERE request_id = ?",
                (encoded, request_hash, request.status, request.updated_at, request.request_id),
            )
        return self.get_research_request(request.request_id) or {}

    @_locked
    def list_research_requests(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT request_id FROM research_requests ORDER BY updated_ts DESC, request_id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [self.get_research_request(row["request_id"]) for row in rows if row]

    @_locked
    def requeue_running_research_jobs(self) -> int:
        """Make jobs from a previous worker process eligible for retry."""
        rows = self.conn.execute(
            "SELECT job_id, job_json FROM research_jobs WHERE status = 'running'"
        ).fetchall()
        changed = 0
        for row in rows:
            job = ResearchJob.from_dict(json.loads(row["job_json"] or "{}"))
            payload = job.to_dict()
            payload.update({
                "status": "queued",
                "updated_at": _now(),
                "started_at": None,
                "completed_at": None,
                "error": "research job was requeued after a worker restart",
            })
            recovered = ResearchJob.from_dict(payload)
            encoded = canonical_json(recovered.to_dict())
            job_hash = canonical_hash(recovered.to_dict())
            with self.conn:
                self.conn.execute(
                    "UPDATE research_jobs SET job_json = ?, job_hash = ?, status = ?, updated_ts = ? WHERE job_id = ? AND status = 'running'",
                    (encoded, job_hash, recovered.status, recovered.updated_at, recovered.job_id),
                )
            changed += 1
        return changed

    @_locked
    def claim_research_job(self, worker: str = "") -> dict[str, Any] | None:
        """Atomically claim the oldest queued research job for one worker."""
        row = self.conn.execute(
            "SELECT job_id, job_json FROM research_jobs WHERE status = 'queued' ORDER BY created_ts ASC, job_id ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        job = ResearchJob.from_dict(json.loads(row["job_json"] or "{}"))
        payload = job.to_dict()
        payload.update({
            "status": "running",
            "attempt": job.attempt + 1,
            "started_at": _now(),
            "completed_at": None,
            "error": "",
        })
        claimed = ResearchJob.from_dict(payload)
        encoded = canonical_json(claimed.to_dict())
        job_hash = canonical_hash(claimed.to_dict())
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE research_jobs SET job_json = ?, job_hash = ?, status = ?, attempt = ?, updated_ts = ? WHERE job_id = ? AND status = 'queued'",
                (encoded, job_hash, claimed.status, claimed.attempt, claimed.updated_at, claimed.job_id),
            )
        if cursor.rowcount != 1:
            return None
        return self.get_research_job(claimed.job_id)

    @_locked
    def save_research_job(self, job: ResearchJob) -> dict[str, Any]:
        if not isinstance(job, ResearchJob):
            raise ContractError("research job must be a ResearchJob")
        if self.get_research_request(job.request_id) is None:
            raise ContractError("research job request was not found")
        payload = job.to_dict()
        encoded = canonical_json(payload)
        job_hash = canonical_hash(payload)
        existing = self.conn.execute(
            "SELECT job_hash FROM research_jobs WHERE job_id = ?", (job.job_id,)
        ).fetchone()
        if existing is not None:
            if existing["job_hash"] != job_hash:
                raise ContractError("research job ID was used for different content")
            return self.get_research_job(job.job_id) or {}
        with self.conn:
            self.conn.execute(
                "INSERT INTO research_jobs (job_id, request_id, job_json, job_hash, status, attempt, created_ts, updated_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job.job_id, job.request_id, encoded, job_hash, job.status, job.attempt, job.created_at, job.updated_at),
            )
        return self.get_research_job(job.job_id) or {}

    @_locked
    def get_research_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM research_jobs WHERE job_id = ?", (str(job_id or "").strip(),)).fetchone()
        if row is None:
            return None
        job = ResearchJob.from_dict(json.loads(row["job_json"] or "{}"))
        result = job.to_dict()
        result.update({"job_hash": row["job_hash"]})
        return result

    @_locked
    def update_research_job(self, job_id: str, **changes: Any) -> dict[str, Any]:
        current = self.get_research_job(job_id)
        if current is None:
            raise ContractError("research job was not found")
        allowed = {"status", "attempt", "started_at", "completed_at", "error"}
        if set(changes) - allowed:
            raise ContractError("research job update contains unsupported fields")
        current.pop("job_hash", None)
        current.update(changes)
        current["updated_at"] = _now()
        job = ResearchJob.from_dict(current)
        payload = job.to_dict()
        encoded = canonical_json(payload)
        job_hash = canonical_hash(payload)
        with self.conn:
            self.conn.execute(
                "UPDATE research_jobs SET job_json = ?, job_hash = ?, status = ?, attempt = ?, updated_ts = ? WHERE job_id = ?",
                (encoded, job_hash, job.status, job.attempt, job.updated_at, job.job_id),
            )
        return self.get_research_job(job.job_id) or {}

    @_locked
    def list_research_jobs(self, request_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT job_id FROM research_jobs"
        params: list[Any] = []
        if request_id:
            query += " WHERE request_id = ?"
            params.append(str(request_id).strip())
        query += " ORDER BY updated_ts DESC, job_id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        rows = self.conn.execute(query, params).fetchall()
        return [self.get_research_job(row["job_id"]) for row in rows if row]

    @_locked
    def save_incubation_insight(self, insight: IncubationInsight) -> dict[str, Any]:
        if not isinstance(insight, IncubationInsight):
            raise ContractError("insight must be an IncubationInsight")
        payload = insight.to_dict()
        encoded = canonical_json(payload)
        insight_hash = canonical_hash(payload)
        existing = self.conn.execute(
            "SELECT insight_hash FROM incubation_insights WHERE insight_id = ?", (insight.insight_id,)
        ).fetchone()
        if existing is not None:
            if existing["insight_hash"] != insight_hash:
                raise ContractError("insight ID was used for different content")
            return self.get_incubation_insight(insight.insight_id) or {}
        with self.conn:
            self.conn.execute(
                "INSERT INTO incubation_insights (insight_id, insight_json, insight_hash, status, created_ts) VALUES (?, ?, ?, ?, ?)",
                (insight.insight_id, encoded, insight_hash, insight.status, insight.created_at),
            )
        return self.get_incubation_insight(insight.insight_id) or {}

    @_locked
    def get_incubation_insight(self, insight_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM incubation_insights WHERE insight_id = ?", (str(insight_id or "").strip(),)
        ).fetchone()
        if row is None:
            return None
        insight = IncubationInsight.from_dict(json.loads(row["insight_json"] or "{}"))
        result = insight.to_dict()
        result.update({"insight_hash": row["insight_hash"]})
        return result

    @_locked
    def list_incubation_insights(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT insight_id FROM incubation_insights ORDER BY created_ts DESC, insight_id DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        return [self.get_incubation_insight(row["insight_id"]) for row in rows if row]

    @_locked
    def save_incubation_deduction(self, deduction: IncubationDeduction) -> dict[str, Any]:
        if not isinstance(deduction, IncubationDeduction):
            raise ContractError("deduction must be an IncubationDeduction")
        encoded = canonical_json(deduction.to_dict())
        content_hash = deduction.content_hash
        existing = self.conn.execute(
            "SELECT deduction_hash FROM incubation_deductions WHERE deduction_id = ?", (deduction.deduction_id,)
        ).fetchone()
        if existing is not None:
            if existing["deduction_hash"] != content_hash:
                raise ContractError("deduction ID was used for different content")
            return self.get_incubation_deduction(deduction.deduction_id) or {}
        with self.conn:
            self.conn.execute(
                "INSERT INTO incubation_deductions (deduction_id, deduction_json, deduction_hash, status, created_ts) VALUES (?, ?, ?, ?, ?)",
                (deduction.deduction_id, encoded, content_hash, "inferred", deduction.created_at),
            )
        return self.get_incubation_deduction(deduction.deduction_id) or {}

    @_locked
    def get_incubation_deduction(self, deduction_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM incubation_deductions WHERE deduction_id = ?", (str(deduction_id or "").strip(),)
        ).fetchone()
        if row is None:
            return None
        deduction = IncubationDeduction.from_dict(json.loads(row["deduction_json"] or "{}"))
        result = deduction.to_dict()
        result.update({"deduction_hash": row["deduction_hash"]})
        return result

    @_locked
    def list_incubation_deductions(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT deduction_id FROM incubation_deductions ORDER BY created_ts DESC, deduction_id DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        return [self.get_incubation_deduction(row["deduction_id"]) for row in rows if row]

    @_locked
    def save_infusion_run(self, run: InfusionRun) -> dict[str, Any]:
        if not isinstance(run, InfusionRun):
            raise ContractError("infusion run must be an InfusionRun")
        encoded = canonical_json(run.to_dict())
        existing = self.conn.execute("SELECT run_id FROM infusion_runs WHERE run_id = ?", (run.run_id,)).fetchone()
        if existing is not None:
            return self.update_infusion_run(run.run_id, status=run.status, mode=run.mode, trigger=run.trigger, budget_tokens=run.budget_tokens, snapshot_hash=run.snapshot_hash, session_id=run.session_id, error=run.error)
        with self.conn:
            self.conn.execute(
                "INSERT INTO infusion_runs (run_id, trigger, mode, status, budget_tokens, snapshot_hash, session_id, started_ts, finished_ts, error, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run.run_id, run.trigger, run.mode, run.status, run.budget_tokens, run.snapshot_hash, run.session_id,
                 run.started_at, run.finished_at, run.error, run.created_at, run.updated_at),
            )
        return self._infusion_run(run.run_id)

    @_locked
    def _infusion_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM infusion_runs WHERE run_id = ?", (str(run_id or "").strip(),)).fetchone()
        if row is None:
            return None
        run = InfusionRun.from_dict({
            "run_id": row["run_id"], "trigger": row["trigger"], "mode": row["mode"], "status": row["status"],
            "budget_tokens": row["budget_tokens"], "snapshot_hash": row["snapshot_hash"], "session_id": row["session_id"],
            "created_at": row["created_ts"], "updated_at": row["updated_ts"],
            "started_at": row["started_ts"], "finished_at": row["finished_ts"], "error": row["error"],
        })
        return run.to_dict()

    @_locked
    def get_infusion_run(self, run_id: str) -> dict[str, Any] | None:
        return self._infusion_run(run_id)

    @_locked
    def update_infusion_run(self, run_id: str, **changes: Any) -> dict[str, Any] | None:
        current = self._infusion_run(run_id)
        if current is None:
            return None
        allowed = {"trigger", "mode", "status", "budget_tokens", "snapshot_hash", "session_id", "error"}
        unknown = set(changes) - allowed
        if unknown:
            raise ContractError("infusion run update contains unsupported fields")
        normalized = {key: value for key, value in changes.items() if key in allowed}
        if "status" in normalized:
            status = str(normalized["status"] or "").strip().lower()
            if status not in {item.value for item in InfusionRunStatus}:
                raise ContractError("infusion run status is invalid")
            normalized["status"] = status
        if "error" in normalized:
            normalized["error"] = safe_provider_message(normalized["error"], max_chars=500)
        extra_sql = ""
        fields: list[Any] = []
        if normalized.get("status") == InfusionRunStatus.RUNNING.value:
            extra_sql = ", started_ts = ?, claimed_by = ?"
            fields = [*fields, _now(), ""]
        if normalized.get("status") in {InfusionRunStatus.COMPLETED.value, InfusionRunStatus.FAILED.value, InfusionRunStatus.SKIPPED.value}:
            extra_sql = ", finished_ts = ?, claimed_by = NULL"
            fields = [*fields, _now()]
        fields = [*fields, _now(), run_id]
        with self.conn:
            self.conn.execute(
                f"UPDATE infusion_runs SET {', '.join(f'{key} = ?' for key in normalized)}, updated_ts = ?{extra_sql} WHERE run_id = ?",
                [*normalized.values(), *fields],
            )
        return self._infusion_run(run_id)

    @_locked
    def list_infusion_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT run_id FROM infusion_runs ORDER BY created_ts DESC, run_id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [self._infusion_run(row["run_id"]) for row in rows if row]

    @_locked
    def claim_pending_infusion_run(self, worker: str = "") -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT run_id FROM infusion_runs WHERE status = ? ORDER BY created_ts ASC, run_id ASC LIMIT 1",
            (InfusionRunStatus.PENDING.value,),
        ).fetchone()
        if row is None:
            return None
        with self.conn:
            self.conn.execute(
                "UPDATE infusion_runs SET status = ?, claimed_by = ?, started_ts = ?, updated_ts = ? WHERE run_id = ? AND status = ?",
                (InfusionRunStatus.RUNNING.value, str(worker or ""), _now(), _now(), row["run_id"], InfusionRunStatus.PENDING.value),
            )
        return self._infusion_run(row["run_id"])

    @_locked
    def requeue_abandoned_infusion_runs(self) -> int:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE infusion_runs SET status = ?, claimed_by = NULL, error = ?, updated_ts = ? WHERE status = ?",
                (InfusionRunStatus.PENDING.value, "interrupted by server restart; queued for retry", _now(), InfusionRunStatus.RUNNING.value),
            )
        return cur.rowcount or 0

    @_locked
    def save_provisioning_bundle(self, bundle: ProvisioningBundle) -> dict[str, Any]:
        if not isinstance(bundle, ProvisioningBundle):
            raise ContractError("bundle must be a ProvisioningBundle")
        encoded = canonical_json(bundle.to_dict())
        content_hash = bundle.computed_hash
        existing = self.conn.execute("SELECT bundle_hash, bundle_json FROM provisioning_bundles WHERE bundle_id = ?", (bundle.bundle_id,)).fetchone()
        if existing is not None:
            if existing["bundle_hash"] != content_hash:
                raise ContractError("bundle ID was used for different content")
            return self.get_provisioning_bundle(bundle.bundle_id) or {}
        with self.conn:
            self.conn.execute(
                "INSERT INTO provisioning_bundles (bundle_id, bundle_hash, bundle_json, created_ts) VALUES (?, ?, ?, ?)",
                (bundle.bundle_id, content_hash, encoded, _now()),
            )
        return self.get_provisioning_bundle(bundle.bundle_id) or {}

    @_locked
    def get_provisioning_bundle(self, bundle_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT bundle_json, bundle_hash, created_ts FROM provisioning_bundles WHERE bundle_id = ?", (str(bundle_id or "").strip(),)).fetchone()
        if row is None:
            return None
        bundle = ProvisioningBundle.from_dict(json.loads(row["bundle_json"] or "{}"))
        return {"bundle": bundle, "bundle_hash": row["bundle_hash"], "created_ts": row["created_ts"]}

    @_locked
    def save_customer_context(
        self,
        context: CustomerContextSnapshot,
        *,
        accepted: bool = False,
    ) -> dict[str, Any]:
        """Persist one immutable, content-addressed customer context revision."""
        if not isinstance(context, CustomerContextSnapshot):
            raise ContractError("customer context must be a CustomerContextSnapshot")
        encoded = canonical_json(context.to_dict())
        context_hash = context.computed_hash
        existing = self.conn.execute(
            "SELECT context_hash, context_json, accepted FROM customer_context_revisions "
            "WHERE context_id = ? AND revision = ?",
            (context.context_id, context.revision),
        ).fetchone()
        if existing is not None:
            if existing["context_hash"] != context_hash or existing["context_json"] != encoded:
                raise ContractError("customer context revision was used for different content")
            if accepted and not bool(existing["accepted"]):
                with self.conn:
                    self.conn.execute(
                        "UPDATE customer_context_revisions SET accepted = 1 WHERE context_id = ? AND revision = ?",
                        (context.context_id, context.revision),
                    )
            return self.get_customer_context(context.context_id, context.revision) or {}
        if accepted:
            with self.conn:
                self.conn.execute("UPDATE customer_context_revisions SET accepted = 0 WHERE context_id = ?", (context.context_id,))
        with self.conn:
            self.conn.execute(
                "INSERT INTO customer_context_revisions "
                "(context_id, revision, context_hash, context_json, source_incubation_id, source_design_run_id, accepted, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    context.context_id,
                    context.revision,
                    context_hash,
                    encoded,
                    context.source_incubation_id,
                    context.source_design_run_id,
                    int(bool(accepted)),
                    context.created_at,
                ),
            )
        return self.get_customer_context(context.context_id, context.revision) or {}

    @_locked
    def get_customer_context(self, context_id: str, revision: int | None = None) -> dict[str, Any] | None:
        context_id = str(context_id or "").strip()
        if not context_id:
            raise ContractError("customer context ID is required")
        if revision is None:
            row = self.conn.execute(
                "SELECT * FROM customer_context_revisions WHERE context_id = ? ORDER BY revision DESC, id DESC LIMIT 1",
                (context_id,),
            ).fetchone()
        else:
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise ContractError("customer context revision is invalid")
            row = self.conn.execute(
                "SELECT * FROM customer_context_revisions WHERE context_id = ? AND revision = ?",
                (context_id, revision),
            ).fetchone()
        if row is None:
            return None
        context = CustomerContextSnapshot.from_dict(json.loads(row["context_json"] or "{}"))
        return {
            "context": context,
            "context_hash": row["context_hash"],
            "accepted": bool(row["accepted"]),
            "created_ts": row["created_ts"],
        }

    @_locked
    def list_customer_contexts(self, limit: int = 100, *, accepted_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT context_id, revision FROM customer_context_revisions"
        params: list[Any] = []
        if accepted_only:
            query += " WHERE accepted = 1"
        query += " ORDER BY created_ts DESC, id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        rows = self.conn.execute(query, params).fetchall()
        return [self.get_customer_context(row["context_id"], int(row["revision"])) for row in rows if row]

    @_locked
    def save_acceptance_manifest(self, manifest: AcceptanceManifest) -> dict[str, Any]:
        """Persist an owner approval only after its exact context is present."""
        if not isinstance(manifest, AcceptanceManifest):
            raise ContractError("acceptance manifest must be an AcceptanceManifest")
        context = self.get_customer_context(manifest.context_id, manifest.context_revision)
        if context is None or context.get("context_hash") != manifest.context_hash:
            raise ContractError("acceptance manifest references an unknown customer context")
        encoded = canonical_json(manifest.to_dict())
        manifest_hash = manifest.computed_hash
        existing = self.conn.execute(
            "SELECT manifest_hash, manifest_json FROM acceptance_manifests WHERE manifest_id = ?",
            (manifest.manifest_id,),
        ).fetchone()
        if existing is not None:
            if existing["manifest_hash"] != manifest_hash or existing["manifest_json"] != encoded:
                raise ContractError("acceptance manifest ID was used for different content")
            return self.get_acceptance_manifest(manifest.manifest_id) or {}
        with self.conn:
            self.conn.execute(
                "INSERT INTO acceptance_manifests "
                "(manifest_id, incubation_id, context_id, context_hash, manifest_hash, manifest_json, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    manifest.manifest_id,
                    manifest.incubation_id,
                    manifest.context_id,
                    manifest.context_hash,
                    manifest_hash,
                    encoded,
                    manifest.created_at,
                ),
            )
        return self.get_acceptance_manifest(manifest.manifest_id) or {}

    @_locked
    def get_acceptance_manifest(self, manifest_id: str) -> dict[str, Any] | None:
        manifest_id = str(manifest_id or "").strip()
        if not manifest_id:
            raise ContractError("acceptance manifest ID is required")
        row = self.conn.execute(
            "SELECT * FROM acceptance_manifests WHERE manifest_id = ?", (manifest_id,)
        ).fetchone()
        if row is None:
            return None
        manifest = AcceptanceManifest.from_dict(json.loads(row["manifest_json"] or "{}"))
        return {
            "manifest": manifest,
            "manifest_hash": row["manifest_hash"],
            "created_ts": row["created_ts"],
        }

    @_locked
    def save_provisioning_import(
        self,
        import_id: str,
        bundle_id: str,
        bundle_hash: str,
        stage: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a resumable destination import stage without exposing SQL."""
        import_id = str(import_id or "").strip()
        bundle_id = str(bundle_id or "").strip()
        bundle_hash = str(bundle_hash or "").strip().lower()
        stage = str(stage or "").strip().lower()
        if not import_id or not bundle_id or not re.fullmatch(r"[0-9a-f]{64}", bundle_hash) or not re.fullmatch(r"[a-z][a-z0-9_.-]{1,59}", stage):
            raise ContractError("provisioning import identity is invalid")
        detail_encoded, _ = self._design_json(detail or {}, "provisioning import detail", max_bytes=50_000)
        current = self.conn.execute(
            "SELECT * FROM provisioning_imports WHERE import_id = ? OR bundle_id = ?",
            (import_id, bundle_id),
        ).fetchone()
        now = _now()
        if current is not None:
            if current["bundle_id"] != bundle_id or current["bundle_hash"] != bundle_hash:
                raise ContractError("provisioning import identity was used for different content")
            with self.conn:
                self.conn.execute(
                    "UPDATE provisioning_imports SET stage = ?, detail_json = ?, updated_ts = ? WHERE import_id = ?",
                    (stage, detail_encoded, now, current["import_id"]),
                )
            import_id = current["import_id"]
        else:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO provisioning_imports (import_id, bundle_id, bundle_hash, stage, detail_json, created_ts, updated_ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (import_id, bundle_id, bundle_hash, stage, detail_encoded, now, now),
                )
        row = self.conn.execute("SELECT * FROM provisioning_imports WHERE import_id = ?", (import_id,)).fetchone()
        result = dict(row) if row else {}
        result["detail"] = self._decode_design_json(result.pop("detail_json", "{}")) if result else {}
        return result

    @_locked
    def get_provisioning_import(self, import_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM provisioning_imports WHERE import_id = ?", (str(import_id or "").strip(),)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["detail"] = self._decode_design_json(result.pop("detail_json", "{}"))
        return result

    @_locked
    def save_website_handoff_receipt(
        self,
        receipt_id: str,
        manifest_id: str,
        candidate_sha: str,
        source_path: str,
        destination_path: str,
        *,
        verified: bool,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        receipt_id = str(receipt_id or "").strip()
        manifest_id = str(manifest_id or "").strip()
        candidate_sha = str(candidate_sha or "").strip().lower()
        source_path = str(source_path or "").strip()
        destination_path = str(destination_path or "").strip()
        if not receipt_id or not manifest_id or not re.fullmatch(r"[0-9a-f]{40}", candidate_sha) or not source_path or not destination_path:
            raise ContractError("website handoff receipt is invalid")
        detail_encoded, _ = self._design_json(detail or {}, "website handoff detail", max_bytes=50_000)
        existing = self.conn.execute(
            "SELECT * FROM website_handoff_receipts WHERE receipt_id = ?", (receipt_id,)
        ).fetchone()
        if existing is not None:
            if existing["candidate_sha"] != candidate_sha or existing["manifest_id"] != manifest_id:
                raise ContractError("website handoff receipt ID was used for different content")
            return dict(existing)
        with self.conn:
            self.conn.execute(
                "INSERT INTO website_handoff_receipts "
                "(receipt_id, manifest_id, candidate_sha, source_path, destination_path, verified, detail_json, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (receipt_id, manifest_id, candidate_sha, source_path, destination_path, int(bool(verified)), detail_encoded, _now()),
            )
        row = self.conn.execute("SELECT * FROM website_handoff_receipts WHERE receipt_id = ?", (receipt_id,)).fetchone()
        return dict(row) if row else {}

    @_locked
    def save_provisioning_id_map(
        self,
        import_id: str,
        entity_type: str,
        source_id: str,
        destination_id: str,
    ) -> dict[str, str]:
        values = tuple(str(item or "").strip() for item in (import_id, entity_type, source_id, destination_id))
        if not all(values) or any(len(item) > 240 for item in values):
            raise ContractError("provisioning ID mapping is invalid")
        with self.conn:
            self.conn.execute(
                "INSERT INTO provisioning_id_maps (import_id, entity_type, source_id, destination_id) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(import_id, entity_type, source_id) DO UPDATE SET destination_id = excluded.destination_id",
                values,
            )
        return {
            "import_id": values[0],
            "entity_type": values[1],
            "source_id": values[2],
            "destination_id": values[3],
        }

    @_locked
    def list_provisioning_id_maps(self, import_id: str, entity_type: str | None = None) -> list[dict[str, str]]:
        query = "SELECT import_id, entity_type, source_id, destination_id FROM provisioning_id_maps WHERE import_id = ?"
        params: list[Any] = [str(import_id or "").strip()]
        if entity_type:
            query += " AND entity_type = ?"
            params.append(str(entity_type).strip())
        query += " ORDER BY entity_type ASC, source_id ASC"
        return [dict(row) for row in self.conn.execute(query, params)]

    @_locked
    def recent_decisions(self, limit: int = 6) -> list[dict[str, Any]]:
        """Adjudicated drafts — declined or approved — newest first.

        The editor surfaces these decisions as context. They inform the model
        without permanently preventing the owner from revisiting earlier work.
        """
        rows = [
            dict(r)
            for r in self.conn.execute(
                "SELECT id, kind, status, title, meta, updated_ts FROM drafts "
                "WHERE status IN ('declined', 'approved') ORDER BY updated_ts DESC, id DESC LIMIT ?",
                (limit,),
            )
        ]
        for row in rows:
            try:
                row["meta"] = json.loads(row["meta"])
            except (json.JSONDecodeError, TypeError):
                row["meta"] = {}
        return rows

    @staticmethod
    def _decode_json_fields(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
        for field_name in fields:
            try:
                row[field_name] = json.loads(row.get(field_name) or ("[]" if field_name.endswith("_json") and field_name == "evidence_json" else "{}"))
            except (json.JSONDecodeError, TypeError):
                row[field_name] = {}
        return row

    @_locked
    def get_seo_site_report(self, report_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM seo_site_reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        try:
            result["evidence_json"] = json.loads(result.get("evidence_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            result["evidence_json"] = {}
        return result

    @_locked
    def get_seo_site_report_for_period(self, period: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM seo_site_reports WHERE period = ?", (period,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        try:
            result["evidence_json"] = json.loads(result.get("evidence_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            result["evidence_json"] = {}
        return result

    @_locked
    def list_seo_site_reports(self, limit: int = 12) -> list[dict[str, Any]]:
        rows = [
            dict(row)
            for row in self.conn.execute(
                "SELECT * FROM seo_site_reports ORDER BY period DESC, id DESC LIMIT ?",
                (max(1, min(int(limit), 50)),),
            )
        ]
        for row in rows:
            try:
                row["evidence_json"] = json.loads(row.get("evidence_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                row["evidence_json"] = {}
        return rows

    @_locked
    def create_seo_site_report(self, period: str, evidence_hash: str = "", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        now = _now()
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO seo_site_reports "
                "(period, evidence_hash, evidence_json, created_ts, updated_ts) VALUES (?, ?, ?, ?, ?)",
                (period, evidence_hash, json.dumps(evidence or {}), now, now),
            )
        result = self.get_seo_site_report_for_period(period)
        if result is None:
            raise RuntimeError("SEO site report was not persisted")
        return result

    @_locked
    def update_seo_site_report(self, report_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {"status", "evidence_hash", "evidence_json", "summary", "artifact_id", "completed_ts", "error"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if "evidence_json" in updates and not isinstance(updates["evidence_json"], str):
            updates["evidence_json"] = json.dumps(updates["evidence_json"])
        if updates:
            updates["updated_ts"] = _now()
            assignments = ", ".join(f"{key} = ?" for key in updates)
            with self.conn:
                self.conn.execute(
                    f"UPDATE seo_site_reports SET {assignments} WHERE id = ?",
                    [*updates.values(), report_id],
                )
        return self.get_seo_site_report(report_id)

    @staticmethod
    def _decode_article_idea(row: dict[str, Any]) -> dict[str, Any]:
        for field_name in ("idea_json", "research_note_json", "research_result_json"):
            try:
                default = "[]" if field_name == "research_result_json" else "{}"
                row[field_name] = json.loads(row.get(field_name) or default)
            except (json.JSONDecodeError, TypeError):
                row[field_name] = [] if field_name == "research_result_json" else {}
        return row

    @_locked
    def get_article_idea(self, idea_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM article_ideas WHERE id = ?", (idea_id,)).fetchone()
        return self._decode_article_idea(dict(row)) if row else None

    @_locked
    def get_article_idea_by_cycle(self, cycle_key: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM article_ideas WHERE cycle_key = ?", (cycle_key,)).fetchone()
        return self._decode_article_idea(dict(row)) if row else None

    @_locked
    def record_rejected_article_idea(
        self,
        *,
        cycle_key: str,
        raw: str,
        parsed: dict[str, Any],
        reason: str,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO rejected_article_ideas (cycle_key, raw, parsed_json, reason, created_ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    (cycle_key or "")[:240],
                    (raw or "")[:6000],
                    json.dumps(parsed or {}, ensure_ascii=False)[:12000],
                    (reason or "")[:500],
                    _now(),
                ),
            )
        return cur.lastrowid

    @_locked
    def list_rejected_article_ideas(self, limit: int = 50) -> list[dict[str, Any]]:
        safe = max(1, min(int(limit), 200))
        rows = self.conn.execute(
            "SELECT id, cycle_key, raw, parsed_json, reason, created_ts "
            "FROM rejected_article_ideas ORDER BY id DESC LIMIT ?",
            (safe,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            try:
                record["parsed_json"] = json.loads(record["parsed_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                record["parsed_json"] = {}
            out.append(record)
        return out

    @_locked
    def get_article_idea_for_draft(self, draft_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM article_ideas WHERE draft_id = ? ORDER BY id DESC LIMIT 1", (draft_id,)
        ).fetchone()
        return self._decode_article_idea(dict(row)) if row else None

    @_locked
    def create_article_idea(
        self,
        cycle_key: str,
        idea_hash: str,
        idea: dict[str, Any],
    ) -> dict[str, Any]:
        now = _now()
        with self.conn:
            try:
                self.conn.execute(
                    "INSERT INTO article_ideas (cycle_key, idea_hash, idea_json, created_ts, updated_ts) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (cycle_key, idea_hash, json.dumps(idea), now, now),
                )
            except sqlite3.IntegrityError:
                pass
        row = self.conn.execute(
            "SELECT * FROM article_ideas WHERE cycle_key = ? OR idea_hash = ? ORDER BY id DESC LIMIT 1",
            (cycle_key, idea_hash),
        ).fetchone()
        if row is None:
            raise RuntimeError("article idea was not persisted")
        result = self._decode_article_idea(dict(row))
        if result["cycle_key"] != cycle_key or result["idea_hash"] != idea_hash:
            raise ContractError("article idea hash or cycle key is already used")
        return result

    @_locked
    def update_article_idea(self, idea_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "status", "research_run_id", "serp_run_id", "research_result_hash", "provider_task_id",
            "research_cost_micros", "research_note_json", "research_result_json", "draft_id", "researched_ts",
            "drafted_ts", "error",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if "research_note_json" in updates and not isinstance(updates["research_note_json"], str):
            updates["research_note_json"] = json.dumps(updates["research_note_json"])
        if "research_result_json" in updates and not isinstance(updates["research_result_json"], str):
            updates["research_result_json"] = json.dumps(updates["research_result_json"])
        if updates:
            updates["updated_ts"] = _now()
            assignments = ", ".join(f"{key} = ?" for key in updates)
            with self.conn:
                self.conn.execute(
                    f"UPDATE article_ideas SET {assignments} WHERE id = ?",
                    [*updates.values(), idea_id],
                )
        return self.get_article_idea(idea_id)

    @_locked
    def list_article_ideas(
        self,
        status: str | None = None,
        limit: int = 50,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if since:
            clauses.append("created_ts >= ?")
            params.append(since)
        if until:
            clauses.append("created_ts < ?")
            params.append(until)
        query = "SELECT * FROM article_ideas"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 200)))
        return [self._decode_article_idea(dict(row)) for row in self.conn.execute(query, params)]

    @_locked
    def article_research_context(self, limit: int = 12) -> list[dict[str, Any]]:
        rows = self.list_article_ideas(limit=limit)
        return [
            {
                "idea_id": row["id"],
                "working_title": (row.get("idea_json") or {}).get("working_title", ""),
                "audience_need": (row.get("idea_json") or {}).get("audience_need", ""),
                "research_seed": (row.get("idea_json") or {}).get("research_seed", ""),
                "status": row["status"],
                "research_note": row.get("research_note_json") or {},
                "research_run_id": row.get("research_run_id"),
                "provider_task_id": row.get("provider_task_id"),
                "research_cost_micros": row.get("research_cost_micros"),
                "created_ts": row.get("created_ts"),
                "researched_ts": row.get("researched_ts"),
                "draft_id": row.get("draft_id"),
            }
            for row in rows
        ]

    @_locked
    def get_seo_research_request(self, period: str, package_version: str = "standard-v1") -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM seo_research_requests WHERE period = ? AND package_version = ?",
            (period, package_version),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        try:
            result["brief"] = json.loads(result.get("brief") or "{}")
        except (json.JSONDecodeError, TypeError):
            result["brief"] = {}
        return result

    @_locked
    def create_seo_research_request(
        self,
        period: str,
        package_version: str,
        idempotency_key: str,
        brief: dict[str, Any],
    ) -> dict[str, Any]:
        now = _now()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO seo_research_requests "
                "(period, package_version, idempotency_key, brief, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (period, package_version, idempotency_key, json.dumps(brief), now, now),
            )
        result = self.conn.execute(
            "SELECT * FROM seo_research_requests WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        if result is None:
            raise RuntimeError("SEO research request was not persisted")
        out = dict(result)
        out["brief"] = brief
        return out

    @_locked
    def update_seo_research_request(self, request_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {"report_id", "status", "error", "requested_ts", "completed_ts"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if updates:
            updates["updated_ts"] = _now()
            assignments = ", ".join(f"{key} = ?" for key in updates)
            with self.conn:
                self.conn.execute(
                    f"UPDATE seo_research_requests SET {assignments} WHERE id = ?",
                    [*updates.values(), request_id],
                )
        row = self.conn.execute("SELECT * FROM seo_research_requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        try:
            out["brief"] = json.loads(out.get("brief") or "{}")
        except (json.JSONDecodeError, TypeError):
            out["brief"] = {}
        return out

    @_locked
    def upsert_seo_seed(
        self,
        seed: str,
        language: str,
        market: str,
        *,
        cluster: str = "",
        objective: str = "",
        priority: str = "normal",
    ) -> dict[str, Any]:
        now = _now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO seo_seed_registry "
                "(seed, language, market, cluster, objective, priority, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(seed, language, market) DO UPDATE SET "
                "cluster = excluded.cluster, objective = excluded.objective, "
                "priority = excluded.priority, updated_ts = excluded.updated_ts",
                (seed, language, market, cluster, objective, priority, now, now),
            )
        row = self.conn.execute(
            "SELECT * FROM seo_seed_registry WHERE seed = ? AND language = ? AND market = ?",
            (seed, language, market),
        ).fetchone()
        if row is None:
            raise RuntimeError("SEO seed was not persisted")
        return dict(row)

    @_locked
    def mark_seo_seed_researched(
        self,
        seed_id: int,
        report_id: str,
        researched_ts: str | None = None,
        freshness: str = "current",
    ) -> bool:
        stamp = researched_ts or _now()
        with self.conn:
            cur = self.conn.execute(
                "UPDATE seo_seed_registry SET "
                "first_researched_ts = COALESCE(first_researched_ts, ?), "
                "last_researched_ts = ?, research_count = research_count + 1, "
                "latest_report_id = ?, freshness = ?, updated_ts = ? WHERE id = ?",
                (stamp, stamp, report_id, freshness, stamp, seed_id),
            )
        return cur.rowcount > 0

    @_locked
    def list_seo_seeds(
        self,
        language: str | None = None,
        market: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if language:
            clauses.append("language = ?")
            params.append(language)
        if market:
            clauses.append("market = ?")
            params.append(market)
        query = "SELECT * FROM seo_seed_registry"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY research_count ASC, priority ASC, id ASC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        return [dict(row) for row in self.conn.execute(query, params)]

    @_locked
    def create_seo_seed_selection(
        self,
        request_id: int,
        seed_id: int,
        ordinal: int,
        slot_type: str,
        rationale: str,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO seo_seed_selections "
                "(request_id, seed_id, ordinal, slot_type, rationale) VALUES (?, ?, ?, ?, ?)",
                (request_id, seed_id, ordinal, slot_type, rationale[:1000]),
            )
        return cur.lastrowid

    @_locked
    def list_seo_seed_selections(self, request_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT selection.*, seed.seed, seed.language, seed.market "
            "FROM seo_seed_selections AS selection "
            "JOIN seo_seed_registry AS seed ON seed.id = selection.seed_id "
            "WHERE selection.request_id = ? ORDER BY selection.ordinal ASC",
            (request_id,),
        )
        return [dict(row) for row in rows]

    @_locked
    def get_strategy_cycle(self, report_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM strategy_cycles WHERE report_id = ?", (report_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        try:
            result["report_json"] = json.loads(result.get("report_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            result["report_json"] = {}
        return result

    @_locked
    def create_strategy_cycle(
        self,
        report_id: str,
        period: str,
        report_hash: str,
        report: dict[str, Any],
        *,
        summary: str = "",
        report_draft_id: int | None = None,
        report_artifact_id: int | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO strategy_cycles "
                "(report_id, period, report_hash, summary, report_json, report_draft_id, report_artifact_id, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (report_id, period, report_hash, summary[:2000], json.dumps(report), report_draft_id, report_artifact_id, now, now),
            )
        row = self.conn.execute("SELECT * FROM strategy_cycles WHERE id = ?", (cur.lastrowid,)).fetchone()
        if row is None:
            raise RuntimeError("strategy cycle was not persisted")
        result = dict(row)
        result["report_json"] = report
        return result

    @_locked
    def update_strategy_cycle(self, cycle_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {"status", "summary", "report_draft_id", "report_artifact_id"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if updates:
            updates["updated_ts"] = _now()
            assignments = ", ".join(f"{key} = ?" for key in updates)
            with self.conn:
                self.conn.execute(
                    f"UPDATE strategy_cycles SET {assignments} WHERE id = ?",
                    [*updates.values(), cycle_id],
                )
        row = self.conn.execute("SELECT * FROM strategy_cycles WHERE id = ?", (cycle_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        try:
            result["report_json"] = json.loads(result.get("report_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            result["report_json"] = {}
        return result

    @_locked
    def create_strategy_initiative(
        self,
        cycle_id: int,
        *,
        kind: str,
        title: str,
        summary: str,
        hypothesis: str = "",
        rationale: str = "",
        evidence: list[Any] | None = None,
        expected: dict[str, Any] | None = None,
        language: str | None = None,
        market: str | None = None,
        priority: str = "normal",
        state: str = "proposed",
        review_30_ts: str | None = None,
        review_90_ts: str | None = None,
        review_180_ts: str | None = None,
        owner_action_id: int | None = None,
        artifact_id: int | None = None,
        approval_id: int | None = None,
        draft_id: int | None = None,
        parent_initiative_id: int | None = None,
    ) -> int:
        now = _now()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO strategy_initiatives "
                "(cycle_id, kind, title, summary, hypothesis, rationale, evidence_json, expected_json, "
                "language, market, priority, state, review_30_ts, review_90_ts, review_180_ts, "
                "owner_action_id, artifact_id, approval_id, draft_id, parent_initiative_id, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cycle_id, kind, title[:300], summary[:2000], hypothesis[:2000], rationale[:2000],
                    json.dumps(evidence or []), json.dumps(expected or {}), language, market, priority, state,
                    review_30_ts, review_90_ts, review_180_ts, owner_action_id, artifact_id, approval_id, draft_id,
                    parent_initiative_id, now, now,
                ),
            )
        return cur.lastrowid

    @_locked
    def update_strategy_initiative(self, initiative_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "state", "owner_action_id", "artifact_id", "approval_id", "draft_id", "receipt_id",
            "parent_initiative_id", "review_30_ts", "review_90_ts", "review_180_ts",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if updates:
            updates["updated_ts"] = _now()
            assignments = ", ".join(f"{key} = ?" for key in updates)
            with self.conn:
                self.conn.execute(
                    f"UPDATE strategy_initiatives SET {assignments} WHERE id = ?",
                    [*updates.values(), initiative_id],
                )
        row = self.conn.execute("SELECT * FROM strategy_initiatives WHERE id = ?", (initiative_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for field_name in ("evidence_json", "expected_json"):
            try:
                result[field_name.removesuffix("_json")] = json.loads(result[field_name])
            except (json.JSONDecodeError, TypeError):
                result[field_name.removesuffix("_json")] = [] if field_name == "evidence_json" else {}
        return result

    @_locked
    def list_strategy_initiatives(self, cycle_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM strategy_initiatives"
        params: list[Any] = []
        if cycle_id is not None:
            query += " WHERE cycle_id = ?"
            params.append(cycle_id)
        query += " ORDER BY id ASC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        rows = [dict(row) for row in self.conn.execute(query, params)]
        for row in rows:
            for field_name in ("evidence_json", "expected_json"):
                try:
                    row[field_name.removesuffix("_json")] = json.loads(row[field_name])
                except (json.JSONDecodeError, TypeError):
                    row[field_name.removesuffix("_json")] = [] if field_name == "evidence_json" else {}
        return rows

    @_locked
    def record_strategy_decision_for_draft(
        self,
        draft_id: int,
        decision: str,
        *,
        owner_feedback: str = "",
        baseline: dict[str, Any] | None = None,
    ) -> int:
        rows = [
            dict(row)
            for row in self.conn.execute(
                "SELECT * FROM strategy_initiatives WHERE draft_id = ?", (draft_id,)
            )
        ]
        now = _now()
        now_dt = datetime.datetime.fromisoformat(now)
        changed = 0
        for row in rows:
            self.conn.execute(
                "INSERT INTO strategy_decisions (initiative_id, decision, reason, owner_feedback, created_ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (row["id"], decision, "owner draft decision", owner_feedback[:2000], now),
            )
            try:
                expected = json.loads(row.get("expected_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                expected = {}
            if baseline is not None and decision == "approved":
                expected["implementation_baseline"] = baseline
                expected["implemented_ts"] = now
            updates = {
                "state": "approved" if decision == "approved" else "declined",
                "expected_json": json.dumps(expected),
                "updated_ts": now,
            }
            if decision == "approved":
                updates.update({
                    "review_30_ts": (now_dt + datetime.timedelta(days=30)).isoformat(timespec="seconds"),
                    "review_90_ts": (now_dt + datetime.timedelta(days=90)).isoformat(timespec="seconds"),
                    "review_180_ts": (now_dt + datetime.timedelta(days=180)).isoformat(timespec="seconds"),
                })
            assignments = ", ".join(f"{key} = ?" for key in updates)
            with self.conn:
                self.conn.execute(
                    f"UPDATE strategy_initiatives SET {assignments} WHERE id = ?",
                    [*updates.values(), row["id"]],
                )
            changed += 1
        return changed

    @_locked
    def record_strategy_decision(
        self,
        initiative_id: int,
        decision: str,
        reason: str = "",
        owner_feedback: str = "",
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO strategy_decisions (initiative_id, decision, reason, owner_feedback, created_ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (initiative_id, decision, reason[:2000], owner_feedback[:2000], _now()),
            )
        return cur.lastrowid

    @_locked
    def record_strategy_outcome(
        self,
        initiative_id: int,
        horizon_days: int,
        baseline: dict[str, Any],
        observed: dict[str, Any],
        assessment: str,
        confidence: str = "low",
        notes: str = "",
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO strategy_outcomes "
                "(initiative_id, horizon_days, baseline_json, observed_json, assessment, confidence, notes, measured_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(initiative_id, horizon_days) DO UPDATE SET "
                "baseline_json = excluded.baseline_json, observed_json = excluded.observed_json, "
                "assessment = excluded.assessment, confidence = excluded.confidence, notes = excluded.notes, "
                "measured_ts = excluded.measured_ts",
                (initiative_id, horizon_days, json.dumps(baseline), json.dumps(observed), assessment, confidence, notes[:2000], _now()),
            )
        row = self.conn.execute(
            "SELECT id FROM strategy_outcomes WHERE initiative_id = ? AND horizon_days = ?",
            (initiative_id, horizon_days),
        ).fetchone()
        return int(row["id"] if row else cur.lastrowid)

    @_locked
    def get_strategy_outcome(self, initiative_id: int, horizon_days: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM strategy_outcomes WHERE initiative_id = ? AND horizon_days = ?",
            (initiative_id, horizon_days),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        for field_name in ("baseline_json", "observed_json"):
            try:
                result[field_name.removesuffix("_json")] = json.loads(result[field_name])
            except (json.JSONDecodeError, TypeError):
                result[field_name.removesuffix("_json")] = {}
        return result

    @_locked
    def snapshot_metrics(self, source: str, data: dict[str, Any]) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO metrics_snapshots (ts, source, data) VALUES (?, ?, ?)",
                (_now(), source, json.dumps(data)),
            )
        return cur.lastrowid

    @_locked
    def latest_snapshot(self, source: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM metrics_snapshots WHERE source = ? ORDER BY id DESC LIMIT 1",
            (source,),
        ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["data"] = json.loads(out["data"])
        return out

    @_locked
    def log_llm_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO llm_costs (ts, model, prompt_tokens, completion_tokens, cost_usd) "
                "VALUES (?, ?, ?, ?, ?)",
                (_now(), model, prompt_tokens, completion_tokens, cost_usd),
            )

    @_locked
    def compact_candidates(
        self,
        before_ts: str,
        prefixes: tuple[str, ...] = ("reddit", "rss"),
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Raw feed observations old enough to compress into an archive."""
        query = (
            "SELECT * FROM observations WHERE ts < ? AND ("
            + " OR ".join("source LIKE ?" for _ in prefixes)
            + ") ORDER BY id ASC LIMIT ?"
        )
        params = [before_ts, *[f"{p}%" for p in prefixes], limit]
        return [dict(r) for r in self.conn.execute(query, params)]

    @_locked
    def delete_observations(self, ids: list[int]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.conn:
            cur = self.conn.execute(f"DELETE FROM observations WHERE id IN ({placeholders})", ids)
        return cur.rowcount

    @_locked
    def create_media_asset(self, asset: MediaAsset) -> int:
        """Persist a newly uploaded asset after its original is stored."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO media_assets "
                "(created_ts, updated_ts, status, media_kind, source_kind, original_name, content_type, "
                "original_size, original_sha256, storage_id, original_key, normalized_key, thumbnail_key, "
                "page_keys_json, width, height, page_count, description, tags_json, ocr_text, proposed_knowledge, "
                "analysis_json, provider_id, model, analysis_version, analysis_status, analysis_attempts, analysis_error, analysis_updated_ts, attempts, last_error, archived_ts, protected_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    asset.created_ts or _now(), asset.updated_ts or _now(), asset.status.value, asset.media_kind.value,
                    asset.source_kind, asset.original_name, asset.content_type, asset.original_size,
                    asset.original_sha256, asset.storage_id, asset.original_key, asset.normalized_key,
                    asset.thumbnail_key, json.dumps(asset.page_keys), asset.width, asset.height, asset.page_count,
                    asset.description, json.dumps(asset.tags), asset.ocr_text, asset.proposed_knowledge,
                    json.dumps(asset.analysis), asset.provider_id, asset.model, asset.analysis_version,
                    asset.analysis_status.value, asset.analysis_attempts, asset.analysis_error,
                    asset.analysis_updated_ts or _now(), asset.attempts, asset.last_error,
                    asset.archived_ts, asset.protected_ts,
                ),
            )
        return int(cur.lastrowid)

    @_locked
    def get_media_asset(self, asset_id: int) -> MediaAsset | None:
        row = self.conn.execute("SELECT * FROM media_assets WHERE id = ?", (asset_id,)).fetchone()
        return MediaAsset.from_row(dict(row)) if row else None

    @_locked
    def find_media_asset_by_hash(self, sha256: str) -> MediaAsset | None:
        row = self.conn.execute("SELECT * FROM media_assets WHERE original_sha256 = ?", (sha256,)).fetchone()
        return MediaAsset.from_row(dict(row)) if row else None

    @_locked
    def list_media_assets(self, status: str | None = None, media_kind: str | None = None,
                          include_archived: bool = False, limit: int = 50, offset: int = 0) -> list[MediaAsset]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if media_kind:
            clauses.append("media_kind = ?")
            params.append(media_kind)
        if not include_archived:
            clauses.append("archived_ts IS NULL")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(1, min(limit, 100)), max(0, offset)])
        rows = self.conn.execute(
            f"SELECT * FROM media_assets{where} ORDER BY id DESC LIMIT ? OFFSET ?", params
        )
        return [MediaAsset.from_row(dict(row)) for row in rows]

    @_locked
    def claim_media_asset(self, worker: str) -> MediaAsset | None:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT * FROM media_assets WHERE status = 'queued' "
                "OR (status = 'ready' AND analysis_status = 'pending') "
                "ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                self.conn.rollback()
                return None
            now = _now()
            self.conn.execute(
                "UPDATE media_assets SET status = 'processing', attempts = attempts + 1, updated_ts = ?, last_error = ? "
                "WHERE id = ? AND (status = 'queued' OR (status = 'ready' AND analysis_status = 'pending')) ",
                (now, f"claimed by {worker}"[:200], row["id"]),
            )
            self.conn.commit()
            updated = dict(row)
            updated["status"] = "processing"
            updated["attempts"] = int(row["attempts"]) + 1
            updated["updated_ts"] = now
            updated["last_error"] = f"claimed by {worker}"[:200]
            return MediaAsset.from_row(updated)
        except Exception:
            self.conn.rollback()
            raise

    @_locked
    def update_media_asset(self, asset_id: int, **fields: Any) -> MediaAsset | None:
        allowed = {
            "status", "normalized_key", "thumbnail_key", "page_keys_json", "width", "height", "page_count",
            "description", "tags_json", "ocr_text", "proposed_knowledge", "analysis_json", "provider_id",
            "model", "analysis_version", "analysis_status", "analysis_attempts", "analysis_error",
            "analysis_updated_ts", "last_error", "archived_ts", "protected_ts",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return self.get_media_asset(asset_id)
        updates["updated_ts"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self.conn:
            self.conn.execute(
                f"UPDATE media_assets SET {assignments} WHERE id = ?",
                [*updates.values(), asset_id],
            )
        return self.get_media_asset(asset_id)

    @_locked
    def fail_media_asset(self, asset_id: int, error: str, *, retryable: bool = False) -> MediaAsset | None:
        status = "queued" if retryable else "failed"
        with self.conn:
            self.conn.execute(
                "UPDATE media_assets SET status = ?, last_error = ?, updated_ts = ? WHERE id = ?",
                (status, error[:500], _now(), asset_id),
            )
        return self.get_media_asset(asset_id)

    @_locked
    def fail_media_analysis(self, asset_id: int, error: str, *, retryable: bool = False) -> MediaAsset | None:
        """Record semantic failure without hiding usable normalized derivatives."""
        status = "pending" if retryable else "failed"
        with self.conn:
            self.conn.execute(
                "UPDATE media_assets SET analysis_status = ?, analysis_error = ?, "
                "analysis_updated_ts = ?, updated_ts = ? WHERE id = ?",
                (status, error[:500], _now(), _now(), asset_id),
            )
        return self.get_media_asset(asset_id)

    @_locked
    def retry_media_asset(self, asset_id: int) -> MediaAsset | None:
        with self.conn:
            self.conn.execute(
                "UPDATE media_assets SET status = CASE WHEN status = 'failed' THEN 'queued' ELSE status END, "
                "analysis_status = CASE WHEN status = 'ready' AND analysis_status = 'failed' THEN 'pending' ELSE analysis_status END, "
                "analysis_error = CASE WHEN status = 'ready' AND analysis_status = 'failed' THEN '' ELSE analysis_error END, "
                "last_error = '', updated_ts = ? WHERE id = ? AND (status = 'failed' OR "
                "(status = 'ready' AND analysis_status = 'failed'))",
                (_now(), asset_id),
            )
        return self.get_media_asset(asset_id)

    @_locked
    def delete_media_asset(self, asset_id: int) -> bool:
        with self.conn:
            cur = self.conn.execute("DELETE FROM media_assets WHERE id = ?", (asset_id,))
        return cur.rowcount == 1

    @_locked
    def media_asset_has_pending_reference(self, asset_id: int) -> bool:
        needle = f'"{asset_id}"'
        rows = self.conn.execute(
            "SELECT meta FROM drafts WHERE status = 'pending' UNION ALL "
            "SELECT a.preview_data FROM artifacts a JOIN approval_requests r ON r.artifact_id = a.id "
            "WHERE r.status = 'pending'"
        )
        return any(needle in str(row[0] or "") or f"[{asset_id}]" in str(row[0] or "") for row in rows)

    @_locked
    def create_business_knowledge(self, asset_id: int, body: str) -> dict[str, Any]:
        now = _now()
        row = self.conn.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 FROM business_knowledge WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
        revision = int(row[0])
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO business_knowledge (asset_id, revision, body, status, created_ts, updated_ts) "
                "VALUES (?, ?, ?, 'pending', ?, ?)",
                (asset_id, revision, body[:50_000], now, now),
            )
        return self.get_business_knowledge(cur.lastrowid)

    @_locked
    def get_business_knowledge(self, knowledge_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM business_knowledge WHERE id = ?", (knowledge_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        return result

    @_locked
    def list_business_knowledge(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM business_knowledge"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY updated_ts DESC, id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        return [dict(row) for row in self.conn.execute(query, params)]

    @_locked
    def update_business_knowledge(self, knowledge_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {"body", "status", "artifact_id", "approval_id", "decided_ts"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return self.get_business_knowledge(knowledge_id)
        updates["updated_ts"] = _now()
        with self.conn:
            self.conn.execute(
                f"UPDATE business_knowledge SET {', '.join(f'{k} = ?' for k in updates)} WHERE id = ?",
                [*updates.values(), knowledge_id],
            )
        return self.get_business_knowledge(knowledge_id)

    @_locked
    def search_business_knowledge(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        terms = [term.lower() for term in re.findall(r"[\w'-]+", query) if len(term) > 1]
        rows = self.list_business_knowledge(status="approved", limit=500)
        scored = []
        for row in rows:
            body = str(row.get("body") or "")
            score = sum(body.lower().count(term) for term in terms)
            if score:
                scored.append((score, row))
        return [row for _, row in sorted(scored, key=lambda item: (-item[0], item[1]["id"]))[:limit]]

    @_locked
    def create_conversation(self, title: str = "New conversation", *, timestamp: str | None = None) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO conversations (created_ts, title) VALUES (?, ?)",
                (str(timestamp or _now()), title[:120]),
            )
        return cur.lastrowid

    @_locked
    def list_conversations(self, limit: int = 50, include_archived: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM conversations"
        params: list[Any] = []
        clauses = ["deleted_ts IS NULL"]
        if not include_archived:
            clauses.append("archived_ts IS NULL")
        query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(query, params)]

    @_locked
    def get_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return dict(row) if row else None

    @_locked
    def archive_conversation(self, conversation_id: int) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE conversations SET archived_ts = ? WHERE id = ? AND deleted_ts IS NULL AND archived_ts IS NULL",
                (_now(), conversation_id),
            )
        return cur.rowcount == 1

    @_locked
    def restore_conversation(self, conversation_id: int) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE conversations SET archived_ts = NULL WHERE id = ? AND deleted_ts IS NULL AND archived_ts IS NOT NULL",
                (conversation_id,),
            )
        return cur.rowcount == 1

    @_locked
    def delete_conversation_content(self, conversation_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, deleted_ts FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row is None:
            return None
        if row["deleted_ts"]:
            return {
                "conversation_id": conversation_id,
                "deleted_ts": row["deleted_ts"],
                "already_deleted": True,
                "job_ids": [],
            }
        active = [
            r["id"]
            for r in self.conn.execute(
                "SELECT id FROM chat_jobs WHERE conversation_id = ? AND status IN ('queued', 'running')",
                (conversation_id,),
            )
        ]
        if active:
            return {"conversation_id": conversation_id, "blocked_job_ids": active}
        deleted_ts = _now()
        with self.conn:
            self.conn.execute(
                "UPDATE chat_jobs SET message = '', message_id = NULL, steps = '[]', result = NULL, error = NULL, "
                "claimed_by = NULL, heartbeat_ts = NULL, updated_ts = ? WHERE conversation_id = ?",
                (deleted_ts, conversation_id),
            )
            self.conn.execute("DELETE FROM chat_messages WHERE conversation_id = ?", (conversation_id,))
            self.conn.execute(
                "UPDATE conversations SET title = 'Deleted conversation', archived_ts = ?, deleted_ts = ? WHERE id = ?",
                (deleted_ts, deleted_ts, conversation_id),
            )
        return {
            "conversation_id": conversation_id,
            "deleted_ts": deleted_ts,
            "already_deleted": False,
            "job_ids": [],
        }

    @_locked
    def archive_conversations(self, keep_id: int | None = None) -> int:
        """Hide old conversations without deleting their durable chat jobs."""
        clauses = [
            "archived_ts IS NULL",
            "id NOT IN (SELECT conversation_id FROM chat_jobs WHERE status IN ('queued', 'running'))",
        ]
        where_params: list[Any] = []
        if keep_id is not None:
            clauses.append("id != ?")
            where_params.append(keep_id)
        with self.conn:
            cur = self.conn.execute(
                f"UPDATE conversations SET archived_ts = ? WHERE {' AND '.join(clauses)}",
                [_now(), *where_params],
            )
        return cur.rowcount

    @_locked
    def add_message(
        self,
        conversation_id: int,
        role: str,
        text: str,
        attachments: list[dict[str, int]] | None = None,
        *,
        timestamp: str | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO chat_messages (conversation_id, ts, role, text, attachments_json) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, str(timestamp or _now()), role, text, json.dumps(attachments or [])),
            )
        return cur.lastrowid

    @_locked
    def get_messages(self, conversation_id: int, limit: int = 200) -> list[dict[str, Any]]:
        rows = [
            dict(r)
            for r in self.conn.execute(
                "SELECT ts, role, text, attachments_json FROM chat_messages WHERE conversation_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (conversation_id, limit),
            )
        ]
        for row in rows:
            try:
                row["attachments"] = json.loads(row.pop("attachments_json") or "[]")
                if not isinstance(row["attachments"], list):
                    row["attachments"] = []
            except (json.JSONDecodeError, TypeError):
                row["attachments"] = []
        return list(reversed(rows))

    @_locked
    def get_messages_before(self, conversation_id: int, message_id: int, limit: int = 8) -> list[dict[str, Any]]:
        rows = [
            dict(r)
            for r in self.conn.execute(
                "SELECT ts, role, text, attachments_json FROM chat_messages WHERE conversation_id = ? AND id < ? "
                "ORDER BY id DESC LIMIT ?",
                (conversation_id, message_id, limit),
            )
        ]
        for row in rows:
            try:
                row["attachments"] = json.loads(row.pop("attachments_json") or "[]")
                if not isinstance(row["attachments"], list):
                    row["attachments"] = []
            except (json.JSONDecodeError, TypeError):
                row["attachments"] = []
        return list(reversed(rows))

    @_locked
    def enqueue_chat_job(
        self,
        conversation_id: int,
        message: str,
        attachments: list[dict[str, int]] | None = None,
        *,
        operation_kind: str = "owner_chat",
        payload: dict[str, Any] | None = None,
        intake_session_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> int:
        """Persist the user message and its job together.

        ``operation_kind`` and ``payload`` let durable domain workflows share
        the existing worker without smuggling state into the owner message.
        ``idempotency_key`` is optional for legacy callers and durable for
        workflows that need retry-safe submission.
        """
        operation_kind = str(operation_kind or "owner_chat").strip().lower()
        if not operation_kind or len(operation_kind) > 60 or not re.fullmatch(r"[a-z][a-z0-9_.-]*", operation_kind):
            raise ContractError("chat job operation_kind is invalid")
        payload = payload or {}
        if not isinstance(payload, dict):
            raise ContractError("chat job payload must be an object")
        payload_encoded = canonical_json(payload)
        if len(payload_encoded.encode("utf-8")) > 100_000:
            raise ContractError("chat job payload exceeds 100000 bytes")
        if intake_session_id is not None:
            intake_session_id = str(intake_session_id).strip()
            if not intake_session_id or len(intake_session_id) > 120 or not re.fullmatch(r"[A-Za-z0-9._:-]+", intake_session_id):
                raise ContractError("intake_session_id is invalid")
        if idempotency_key is not None:
            idempotency_key = str(idempotency_key).strip()
            if not idempotency_key or len(idempotency_key) > 160 or not re.fullmatch(r"[A-Za-z0-9._:-]+", idempotency_key):
                raise ContractError("idempotency_key is invalid")
        now = _now()
        with self.conn:
            if idempotency_key is not None:
                existing = self.conn.execute(
                    "SELECT jobs.id, jobs.message, messages.attachments_json FROM chat_jobs AS jobs "
                    "LEFT JOIN chat_messages AS messages ON messages.id = jobs.message_id "
                    "WHERE jobs.operation_kind = ? AND jobs.intake_session_id IS ? AND jobs.idempotency_key = ?",
                    (operation_kind, intake_session_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    existing_attachments = existing["attachments_json"] or "[]"
                    if existing["message"] != message or existing_attachments != json.dumps(attachments or []):
                        raise ContractError("idempotency_key was already used for a different message")
                    return int(existing["id"])
            message_cur = self.conn.execute(
                "INSERT INTO chat_messages (conversation_id, ts, role, text, attachments_json) VALUES (?, ?, 'user', ?, ?)",
                (conversation_id, now, message, json.dumps(attachments or [])),
            )
            cur = self.conn.execute(
                "INSERT INTO chat_jobs "
                "(conversation_id, message, message_id, status, operation_kind, payload_json, intake_session_id, idempotency_key, created_ts, updated_ts) "
                "VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)",
                (conversation_id, message, message_cur.lastrowid, operation_kind, payload_encoded,
                 intake_session_id, idempotency_key, now, now),
            )
        return cur.lastrowid

    @_locked
    def enqueue_design_intake_advice_job(
        self,
        conversation_id: int,
        message: str,
        *,
        session_id: str,
        attachments: list[dict[str, int]] | None = None,
        idempotency_key: str | None = None,
    ) -> int:
        """Queue one durable, message-bound Ada intake advice turn."""
        return self.enqueue_chat_job(
            conversation_id,
            message,
            attachments,
            operation_kind="design_intake_advice",
            payload={"session_id": str(session_id)},
            intake_session_id=str(session_id),
            idempotency_key=idempotency_key,
        )

    @_locked
    def claim_chat_job(self, worker: str) -> dict[str, Any] | None:
        """Claim the oldest queued job using a database-level write lock."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            running = self.conn.execute(
                "SELECT 1 FROM chat_jobs WHERE status = 'running' LIMIT 1"
            ).fetchone()
            if running:
                self.conn.rollback()
                return None
            row = self.conn.execute(
                "SELECT * FROM chat_jobs WHERE status = 'queued' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                self.conn.rollback()
                return None
            updated = self.conn.execute(
                "UPDATE chat_jobs SET status = 'running', claimed_by = ?, updated_ts = ? "
                "WHERE id = ? AND status = 'queued'",
                (worker, _now(), row["id"]),
            ).rowcount
            if updated != 1:
                self.conn.rollback()
                return None
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        out = dict(row)
        out["status"] = "running"
        out["claimed_by"] = worker
        return self._decode_chat_job(out)

    @_locked
    def append_chat_job_step(self, job_id: int, worker: str, step: str) -> None:
        row = self.conn.execute(
            "SELECT steps FROM chat_jobs WHERE id = ? AND claimed_by = ?",
            (job_id, worker),
        ).fetchone()
        if row is None:
            return
        steps = json.loads(row["steps"] or "[]")
        steps.append({"ts": _now(), "text": step})
        with self.conn:
            self.conn.execute(
                "UPDATE chat_jobs SET steps = ?, updated_ts = ? "
                "WHERE id = ? AND claimed_by = ?",
                (json.dumps(steps[-200:]), _now(), job_id, worker),
            )

    @_locked
    def complete_chat_job(self, job_id: int, worker: str, result: dict[str, Any]) -> bool:
        row = self.conn.execute(
            "SELECT conversation_id FROM chat_jobs "
            "WHERE id = ? AND status = 'running' AND claimed_by = ?",
            (job_id, worker),
        ).fetchone()
        if row is None:
            return False
        with self.conn:
            updated = self.conn.execute(
                "UPDATE chat_jobs SET status = 'done', result = ?, updated_ts = ?, "
                "claimed_by = NULL, heartbeat_ts = NULL WHERE id = ? AND claimed_by = ?",
                (json.dumps(result), _now(), job_id, worker),
            ).rowcount
            if updated == 1:
                self.conn.execute(
                    "INSERT INTO chat_messages (conversation_id, ts, role, text) VALUES (?, ?, 'assistant', ?)",
                    (row["conversation_id"], _now(), result.get("reply") or ""),
                )
        return updated == 1

    @_locked
    def fail_chat_job(self, job_id: int, worker: str, error: str) -> bool:
        with self.conn:
            updated = self.conn.execute(
                "UPDATE chat_jobs SET status = 'error', error = ?, updated_ts = ?, "
                "claimed_by = NULL, heartbeat_ts = NULL WHERE id = ? AND claimed_by = ?",
                (error[:500], _now(), job_id, worker),
            ).rowcount
        return updated == 1

    @_locked
    def interrupt_running_chat_jobs(self, error: str = "interrupted by server restart; retry this job") -> int:
        """Make abandoned work visible instead of replaying it automatically."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE chat_jobs SET status = 'error', error = ?, updated_ts = ?, "
                "claimed_by = NULL, heartbeat_ts = NULL WHERE status = 'running'",
                (error[:500], _now()),
            )
        return cur.rowcount

    @_locked
    def retry_chat_job(self, job_id: int) -> bool:
        """Explicitly requeue a failed or incomplete job."""
        row = self.conn.execute(
            "SELECT status, result FROM chat_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return False
        retryable = row["status"] == "error"
        if row["status"] == "done":
            try:
                result = json.loads(row["result"] or "{}")
            except (json.JSONDecodeError, TypeError):
                result = {}
            retryable = not result.get("changed") and not result.get("merge_draft_id")
        if not retryable:
            return False
        with self.conn:
            cur = self.conn.execute(
                "UPDATE chat_jobs SET status = 'queued', steps = '[]', result = NULL, error = NULL, "
                "claimed_by = NULL, heartbeat_ts = NULL, updated_ts = ? "
                "WHERE id = ? AND status IN ('error', 'done')",
                (_now(), job_id),
            )
        return cur.rowcount == 1

    @staticmethod
    def _decode_chat_job(row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["steps"] = json.loads(out.get("steps") or "[]")
        try:
            out["payload"] = json.loads(out.pop("payload_json") or "{}")
            if not isinstance(out["payload"], dict):
                out["payload"] = {}
        except (json.JSONDecodeError, TypeError):
            out["payload"] = {}
        if out.get("result"):
            try:
                out["result"] = json.loads(out["result"])
            except (json.JSONDecodeError, TypeError):
                out["result"] = None
        return out

    @_locked
    def get_chat_job(self, job_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM chat_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._decode_chat_job(dict(row))

    @_locked
    def list_active_chat_jobs(self, conversation_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = "SELECT * FROM chat_jobs WHERE status IN ('queued', 'running')"
        params: list[Any] = []
        if conversation_id is not None:
            query += " AND conversation_id = ?"
            params.append(conversation_id)
        query += " ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, id ASC LIMIT ?"
        params.append(limit)
        return [self._decode_chat_job(dict(r)) for r in self.conn.execute(query, params)]

    @_locked
    def list_chat_jobs(self, conversation_id: int, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM chat_jobs WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        )
        return [self._decode_chat_job(dict(r)) for r in rows]

    @_locked
    def fail_stale_chat_jobs(
        self,
        max_seconds: float = 240,
        *,
        cut: float | None = None,
    ) -> list[int]:
        """Mark queued/running jobs older than ``max_seconds`` as failed with
        ``reason=stale`` so a worker crash or a wedged provider cannot strand a
        conversation forever. ``cut`` (seconds since epoch) overrides the age
        window for tests."""
        import datetime as _datetime

        if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not 0 < max_seconds <= 86_400:
            raise ContractError("max_seconds is invalid")
        if cut is None:
            cut = datetime.datetime.now(datetime.timezone.utc).timestamp() - float(max_seconds)
        stale_ids: list[int] = []
        with self.conn:
            rows = self.conn.execute(
                "SELECT * FROM chat_jobs WHERE status IN ('queued', 'running')"
            ).fetchall()
            for row in rows:
                job = self._decode_chat_job(dict(row))
                stamp = job.get("updated_ts") or job.get("created_ts") or ""
                try:
                    age = _datetime.datetime.fromisoformat(stamp).replace(tzinfo=_datetime.timezone.utc).timestamp()
                except (TypeError, ValueError):
                    continue
                if age >= cut:
                    continue
                self.conn.execute(
                    "UPDATE chat_jobs SET status = 'error', error = ?, updated_ts = ?, "
                    "claimed_by = NULL, heartbeat_ts = NULL WHERE id = ?",
                    (f"chat job was not completed within {int(max_seconds)} seconds (reason=stale)", _now(), row["id"]),
                )
                stale_ids.append(int(row["id"]))
        return stale_ids

    @_locked
    def log_publish(
        self,
        summary: str,
        path: str,
        commit_sha: str,
        draft_id: int | None = None,
        parent_sha: str = "",
        actor: str = "ada",
        version_type: str = "edit",
        commit_message: str = "",
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO publishes "
                "(ts, summary, path, commit_sha, draft_id, parent_sha, actor, version_type, commit_message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now(), summary[:160], path, commit_sha, draft_id, parent_sha[:100],
                    actor[:30], version_type[:30], commit_message[:8000],
                ),
            )
        return cur.lastrowid

    @_locked
    def mark_publish_reverted(self, commit_sha: str | None = None, draft_id: int | None = None) -> int:
        """Tag publish rows as reverted so the UI stops offering a Revert button."""
        with self.conn:
            if commit_sha:
                cur = self.conn.execute(
                    "UPDATE publishes SET reverted_ts = ? WHERE commit_sha = ? AND reverted_ts IS NULL",
                    (_now(), commit_sha),
                )
                return cur.rowcount
            if draft_id is not None:
                cur = self.conn.execute(
                    "UPDATE publishes SET reverted_ts = ? WHERE draft_id = ? AND reverted_ts IS NULL",
                    (_now(), draft_id),
                )
                return cur.rowcount
            return 0

    @_locked
    def list_publishes(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM publishes ORDER BY id DESC LIMIT ?", (limit,)
            )
        ]

    @_locked
    def llm_spend(self, since_hours: float = 24.0) -> dict[str, Any]:
        cutoff = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=since_hours)
        ).isoformat(timespec="seconds")
        row = self.conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens),0) AS pt, COALESCE(SUM(completion_tokens),0) AS ct, "
            "COALESCE(SUM(cost_usd),0) AS cost, "
            "COALESCE(SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END),0) AS unpriced_calls, "
            "COALESCE(SUM(CASE WHEN cost_usd IS NULL THEN prompt_tokens ELSE 0 END),0) AS unpriced_prompt_tokens, "
            "COALESCE(SUM(CASE WHEN cost_usd IS NULL THEN completion_tokens ELSE 0 END),0) AS unpriced_completion_tokens, "
            "COALESCE(SUM(CASE WHEN cost_usd IS NULL AND prompt_tokens <= 0 AND completion_tokens <= 0 THEN 1 ELSE 0 END),0) AS unpriced_unmeasurable_calls "
            "FROM llm_costs WHERE ts >= ?",
            (cutoff,),
        ).fetchone()
        return {
            "prompt_tokens": row["pt"],
            "completion_tokens": row["ct"],
            "cost_usd": round(row["cost"], 6),
            "unpriced_calls": row["unpriced_calls"],
            "unpriced_prompt_tokens": row["unpriced_prompt_tokens"],
            "unpriced_completion_tokens": row["unpriced_completion_tokens"],
            "unpriced_unmeasurable_calls": row["unpriced_unmeasurable_calls"],
        }
