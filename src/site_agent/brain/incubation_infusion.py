"""Durable background "infusion": turning new information into knowledge.

Every pass reads a bounded snapshot of the incubation's current knowledge
(working brief, genesis, findings, insights, deductions), produces new typed
deductions plus follow-up research, and persists everything so the next pass
and the conversation start from more. A pass is either an opencode session
(engine, with pipeworx) or one native DeepSeek call (fallback).

Invariants:
- The conversation never blocks on infusion: one model call per chat turn and
  an infusion pass never runs synchronously inside a chat request.
- Output is typed, source-linked, never presented as owner facts.
- Passes are durable (claim/run/fail), throttled, and budget-capped.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from ..core.contracts import ContractError, utc_now
from ..core.design_contracts import canonical_hash
from ..core.incubation_contracts import (
    ActivityProvenance,
    DeductionKind,
    EvidenceOrigin,
    GenesisEvidence,
    IncubationActivityCategory,
    IncubationDeduction,
    IncubationInsight,
    IncubationActivityState,
    InfusionMode,
    InfusionRun,
    InfusionRunStatus,
    ResearchTrigger,
)
from ..core.llm import extract_json


class IncubationInfusionError(RuntimeError):
    """An infusion pass could not be completed safely."""


_DEDUCTION_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_KINDS = {item.value for item in DeductionKind}


def snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    return canonical_hash(snapshot)


def build_infusion_snapshot(
    *,
    draft: Mapping[str, Any],
    genesis: Mapping[str, Any] | None,
    deductions: Sequence[Mapping[str, Any]],
    findings: Sequence[Mapping[str, Any]],
    insights: Sequence[Mapping[str, Any]],
    sources: Sequence[Mapping[str, Any]],
    assets: Sequence[Mapping[str, Any]],
    owner_language: str = "en",
) -> dict[str, Any]:
    """A bounded, canonical knowledge snapshot for one pass."""
    if genesis is not None and not isinstance(genesis, Mapping):
        to_dict = getattr(genesis, "to_dict", None)
        genesis = to_dict() if callable(to_dict) and isinstance(to_dict(), Mapping) else None
    fields = _draft_fields(draft)
    return {
        "schema_version": 1,
        "owner_language": str(owner_language or "en").strip().lower() or "en",
        "draft_fields": fields,
        "unresolved_core_paths": [str(item) for item in list(draft.get("unresolved_core_paths") or [])[:12]],
        "genesis": {
            "business_world": dict((genesis.get("business_world") or {})) if genesis else {},
            "creative_identity": dict((genesis.get("creative_identity") or {})) if genesis else {},
        },
        "deductions": [
            {
                "kind": item.get("kind"),
                "summary": str(item.get("summary") or "")[:280],
                "supports_paths": [str(p) for p in list(item.get("supports_paths") or [])[:6]],
            }
            for item in list(deductions)[:20]
        ],
        "findings": [
            {
                "finding_id": item.get("finding_id"),
                "summary": str(item.get("summary") or "")[:260],
                "confidence": item.get("confidence"),
            }
            for item in list(findings)[:24]
        ],
        "insights": [
            {
                "insight_id": item.get("insight_id"),
                "kind": item.get("kind"),
                "summary": str(item.get("summary") or "")[:260],
                "supports_paths": [str(p) for p in list(item.get("supports_paths") or [])[:6]],
            }
            for item in list(insights)[:16]
        ],
        "sources": [
            {
                "source_id": item.get("source_id"),
                "title": str(item.get("title") or "")[:200],
                "trust_state": item.get("trust_state"),
            }
            for item in list(sources)[:16]
        ],
        "asset_analyses": [
            {
                "asset_id": item.get("asset_id"),
                "name": str(item.get("name") or "")[:80],
                "description": str((item.get("analysis") or {}).get("description") or item.get("description") or "")[:300],
                "tags": [str(tag)[:60] for tag in list((item.get("analysis") or {}).get("tags") or [])[:8]],
                "dominant_colors": [str(c)[:40] for c in list((item.get("analysis") or {}).get("dominant_colors") or [])[:6]],
                "usage": item.get("usage") or "undecided",
            }
            for item in list(assets)[:12]
            if isinstance(item, Mapping)
        ],
        "deduction_count": len(deductions),
        "finding_count": len(findings),
    }


def _draft_fields(draft: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten the intake draft to bounded leaf values."""
    values = draft.get("fields") or {}
    result: dict[str, Any] = {}
    queue = [("", values)]  # type: ignore[list-item]
    while queue:
        prefix, node = queue.pop()  # type: ignore[misc]
        if isinstance(node, dict):
            for key, child in node.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(child, dict) and child:
                    queue.append((path, child))
                elif isinstance(child, (list, tuple)) and child:
                    result[path] = [str(item)[:120] for item in list(child)[:12]]
                elif child is not None and child != "":
                    result[path] = str(child)[:240]
        elif isinstance(node, (list, tuple)):
            result[prefix] = [str(item)[:120] for item in list(node)[:12]]
    return dict(list(result.items())[:40])


def parse_infusion_contract(text: Any) -> dict[str, Any] | None:
    """Validate model/agent output against the infusion JSON contract.

    Returns a normalized object or None when nothing JSON-shaped parses.
    Raises IncubationInfusionError when the parsed object violates the
    contract shape."""
    value = extract_json(text)
    if not isinstance(value, dict):
        return None
    deductions_raw = value.get("deductions") or []
    if not isinstance(deductions_raw, list):
        raise IncubationInfusionError("infusion deductions must be a list")
    normalized: list[dict[str, Any]] = []
    for item in list(deductions_raw)[:30]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in _KINDS:
            continue
        summary = str(item.get("summary") or "").strip()[:2_000]
        if not summary:
            continue
        confidence = item.get("confidence", 0.4)
        if isinstance(confidence, bool):
            confidence = 0.4
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.4
        basis = str(item.get("basis") or "snapshot").strip()[:120]
        if basis not in {"snapshot", "source", "hypothesis"} and not basis.startswith("source:"):
            basis = "hypothesis"
        supports = [str(p)[:120] for p in list(item.get("supports_paths") or [])[:10]]
        sources_list = [str(s)[:120] for s in list(item.get("source_refs") or [])[:10]]
        uris = [str(u)[:240] for u in list(item.get("citation_uris") or [])[:12] if str(u).startswith("pipeworx://")]
        normalized.append({
            "kind": kind,
            "summary": summary,
            "confidence": confidence,
            "basis": basis,
            "supports_paths": supports,
            "source_refs": sources_list,
            "citation_uris": uris,
        })
    followup_raw = value.get("followup_research") or []
    followup: list[dict[str, Any]] = []
    if isinstance(followup_raw, list):
        for item in list(followup_raw)[:10]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "").strip().lower()
            if kind not in {"feed", "community", "pipeworx"}:
                continue
            query = str(item.get("query") or item.get("url") or "").strip()[:2_000]
            reason = str(item.get("reason") or "").strip()[:400]
            if not query:
                continue
            followup.append({"type": kind, "query": query, "reason": reason})
    genesis_notes = value.get("genesis_notes") or {}
    if not isinstance(genesis_notes, dict):
        genesis_notes = {}
    horizon = [str(q).strip()[:400] for q in list(value.get("horizon_questions") or [])[:6] if str(q).strip()]
    return {
        "deductions": normalized,
        "followup_research": followup,
        "genesis_notes": genesis_notes,
        "horizon_questions": horizon,
    }


_INFUSION_SYSTEM = """You are Ada's incubation engine. The host gives you a bounded
snapshot of one customer incubation's current knowledge (working brief, genesis,
findings, insights, existing deductions, reference-image analyses).

The snapshot is about ONE thing only: the OWNER'S BUSINESS. The host's
engineering vocabulary (infusion, incubation, genesis, deduction, snapshot,
run ids, engine or tool names) describes this engine, never the business; if the
snapshot carries no real business facts, return exactly:
{"deductions":[],"followup_research":[],"genesis_notes":{},"horizon_questions":[]}.

1. DEDUCE genuinely new, defensible knowledge about the owner's business,
   audience, market, or craft that the brief does not already say. Each
   deduction must be supported by the snapshot or an explicit hypothesis
   (basis: snapshot|source|hypothesis); never present a deduction as an owner
   fact. At most 5 deductions per pass.
2. FOLLOW-UP: propose the next research that would resolve the biggest
   remaining unknown about the owner's business (type: feed|community|pipeworx;
   query must be a URL, a community name, or a direct pipeworx question in the
   owner's language). If pipeworx, phrase it as a natural question ready for
   ask_pipeworx.

Return exactly one JSON object (no prose, no code fence):
{"deductions":[{"kind":"market_context|audience_fact|audience_hypothesis|creative_leaning|competitor_note|positioning_note|risk|opportunity","summary":"...","confidence":0.0,"basis":"snapshot|source|hypothesis","supports_paths":["audience.primary"],"source_refs":["source_..."]}],
 "followup_research":[{"type":"feed|community|pipeworx","query":"...","reason":"..."}],
 "genesis_notes":{"business_world":{"values":["..."]},"creative_identity":{"principles":["..."]}},
 "horizon_questions":["..."]}"""


_SYSTEM_VOCABULARY = {
    "infusion", "incubation", "genesis", "deduction", "snapshot",
    "snapshot.json", "horizon", "pipeworx", "opencode", "worktree", "ada",
}


def _text_tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9]{3,}", str(text or ""))}


def _owner_terms(memory: Any) -> set[str]:
    """Every word the owner actually put into the working brief.

    The structural guard: nothing outside the owner's own language may become
    a research subject or a persisted deduction. If the owner's business IS an
    infusion clinic, "infusion" is in their vocabulary and stays legitimate.
    """
    try:
        rows = memory.list_design_intake_sessions(limit=1)
        session = memory.get_design_intake_session(rows[0]["session_id"]) if rows else None
        draft = (session or {}).get("draft") or {}
        encoded = json.dumps(draft.get("fields") or {}, ensure_ascii=True, default=str)
        return _text_tokens(encoded)
    except Exception:  # noqa: BLE001 — the guard degrades to "no owner vocabulary"
        return set()


def _system_term_leak(text: str, owner_terms: set[str]) -> bool:
    tokens = _text_tokens(text)
    return any(token in _SYSTEM_VOCABULARY and token not in owner_terms for token in tokens)


def _dedupe_hash(payload: Mapping[str, Any]) -> str:
    return canonical_hash({
        "kind": payload.get("kind"),
        "summary": str(payload.get("summary") or "").strip().casefold(),
        "supports_paths": sorted(payload.get("supports_paths") or []),
    })


class IncubationInfusionService:
    """Persist infusion runs and deductions inside one incubation scope."""

    def __init__(
        self,
        memory,
        *,
        config: Mapping[str, Any],
        llm: Any = None,
        activity_service: Any = None,
        research_service: Any = None,
        genesis_service: Any = None,
        opencode_runner: Callable[..., Mapping[str, Any]] | None = None,
        runner_context: Mapping[str, Any] | None = None,
        now: Callable[[], str] = utc_now,
    ) -> None:
        from ..config import InfusionSettings

        self.memory = memory
        self.config = dict(config)
        self.settings = InfusionSettings.from_config(self.config)
        self.llm = llm
        self.activity_service = activity_service
        self.research_service = research_service
        self.genesis_service = genesis_service
        self.opencode_runner = opencode_runner
        self.runner_context = dict(runner_context or {})
        self.now = now

    # -- projection / briefing -------------------------------------------------
    def projection(self) -> dict[str, Any]:
        return {
            "deductions": self.memory.list_incubation_deductions(limit=200),
            "runs": self.memory.list_infusion_runs(limit=50),
        }

    def advice_briefing(self, limit: int = 6) -> list[str]:
        deductions = self.memory.list_incubation_deductions(limit=50)
        lines: list[str] = []
        for item in deductions[:limit]:
            if not isinstance(item, Mapping):
                continue
            summary = str(item.get("summary") or "").strip()
            if summary:
                lines.append(summary[:280])
        return lines

    def build_context_snapshot(self) -> dict[str, Any] | None:
        """Infer the canonical snapshot from durable memory alone. Returns None
        when there is no usable knowledge yet (e.g. no draft fields)."""
        session = None
        rows = self.memory.list_design_intake_sessions(limit=1)
        if rows:
            session = self.memory.get_design_intake_session(rows[0]["session_id"])
        draft = (session or {}).get("draft") or {}
        genesis_row = self.memory.get_customer_genesis_revision()
        genesis = (genesis_row or {}).get("genesis")
        if not _draft_fields(draft) and genesis is None:
            return None
        return build_infusion_snapshot(
            draft=session or {},
            genesis=genesis.to_dict() if genesis is not None else None,
            deductions=self.memory.list_incubation_deductions(limit=50),
            findings=[item.to_dict() for item in self.memory.list_research_findings(limit=50)],
            insights=self.memory.list_incubation_insights(limit=50),
            sources=self.memory.list_research_sources(limit=50),
            assets=self.memory.list_design_intake_assets(str(session["session_id"])) if session else [],
            owner_language=str(draft.get("fields", {}).get("site", {}).get("language") or "en"),
        )

    # -- enqueue ---------------------------------------------------------------
    def can_run(self, now_ts: str | None = None) -> tuple[bool, str]:
        if not self.settings.enabled:
            return False, "infusion disabled"
        runs = self.memory.list_infusion_runs(limit=500)
        recent = [item for item in runs if item.get("status") in {
            InfusionRunStatus.RUNNING.value, InfusionRunStatus.PENDING.value,
        }]
        if recent:
            return False, "infusion pass already in flight"
        from datetime import datetime, timezone

        def _ts(value: Any):
            try:
                return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                return None

        now_dt = _ts(now_ts or self.now()) or datetime.now(timezone.utc)
        day_key = now_dt.strftime("%Y-%m-%d")
        today = [item for item in runs if _ts(item.get("created_at")) and _ts(item.get("created_at")).strftime("%Y-%m-%d") == day_key]
        if len(today) >= self.settings.max_passes_per_day:
            return False, "daily infusion budget reached"
        return True, ""

    def _cooled_down(self) -> bool:
        runs = self.memory.list_infusion_runs(limit=50)
        from datetime import datetime, timezone

        latest = None
        for item in runs:
            if item.get("status") not in {InfusionRunStatus.COMPLETED.value, InfusionRunStatus.FAILED.value}:
                continue
            try:
                stamp = datetime.fromisoformat(str(item.get("finished_at") or item.get("updated_at") or "")).replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            if latest is None or stamp > latest:
                latest = stamp
        if latest is None:
            return True
        elapsed = (datetime.now(timezone.utc) - latest).total_seconds()
        return elapsed >= self.settings.cooldown_seconds

    def enqueue(
        self,
        *,
        trigger: str,
        session_id: str,
        snapshot: Mapping[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any] | None:
        """Create one durable pending infusion pass, respecting throttle/budget.
        Returns the run dict or None when throttled or there is nothing to do."""
        if force:
            can_run, _ = self.can_run()
        else:
            can_run, _ = self.can_run()
        if not can_run:
            return None
        if not self._cooled_down():
            self._activity(trigger, skip=True)
            return None
        if snapshot is None:
            snapshot = self.build_context_snapshot()
        if not snapshot:
            return None
        mode = self._decide_mode()
        run_id = "infusion_" + uuid.uuid4().hex
        now = self.now()
        target_session = str(session_id or "").strip() or f"intake-{'0' * 32}"
        run = InfusionRun.from_dict({
            "run_id": run_id,
            "trigger": str(trigger or "idle").strip()[:40],
            "mode": mode,
            "status": InfusionRunStatus.PENDING.value,
            "budget_tokens": self.settings.max_tokens_per_pass,
            "snapshot_hash": snapshot_hash(snapshot),
            "session_id": target_session,
            "created_at": now,
            "updated_at": now,
        })
        self.memory.save_infusion_run(run)
        self.memory.kv_set(f"infusion_snapshot_{run_id}", snapshot)
        self._activity(trigger, pending=True, run_id=run_id, mode=mode)
        return self.memory.get_infusion_run(run_id)

    def _decide_mode(self) -> str:
        if self.settings.mode == "opencode":
            return InfusionMode.OPENCODE.value
        if self.settings.mode == "native":
            return InfusionMode.NATIVE.value
        recent_runs = self.memory.list_infusion_runs(limit=20)
        from datetime import datetime, timezone

        last_opencode = None
        for item in recent_runs:
            if item.get("mode") != InfusionMode.OPENCODE.value:
                continue
            try:
                stamp = datetime.fromisoformat(str(item.get("created_at") or "")).replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            if last_opencode is None or stamp > last_opencode:
                last_opencode = stamp
        if last_opencode is None:
            return InfusionMode.OPENCODE.value
        elapsed = (datetime.now(timezone.utc) - last_opencode).total_seconds()
        return InfusionMode.OPENCODE.value if elapsed >= self.settings.opencode_pass_interval_seconds else InfusionMode.NATIVE.value

    def _activity(self, trigger: str, *, pending: bool = False, skip: bool = False, **detail: Any) -> None:
        if self.activity_service is None:
            return
        try:
            self.activity_service.record(
                category=IncubationActivityCategory.RESEARCH.value,
                kind="infusion_pass",
                state=IncubationActivityState.STARTED.value if pending else IncubationActivityState.NEEDS_ATTENTION.value if skip else IncubationActivityState.COMPLETED.value,
                summary=(
                    "Queued a background knowledge pass."
                    if pending else
                    "A background knowledge pass was skipped by its cooldown."
                    if skip else
                    "Completed a background knowledge pass."
                ),
                provenance=ActivityProvenance.MODEL_INFERENCE.value,
                detail={**detail, "trigger": str(trigger or ""), "status": "pending" if pending else "skipped" if skip else "completed"},
            )
        except Exception:  # noqa: BLE001 — activity is diagnostic
            pass

    # -- execution ---------------------------------------------------------------
    def process_one(self, worker: str) -> tuple[bool, str | None]:
        run = self.memory.claim_pending_infusion_run(worker)
        if run is None:
            return False, None
        run_id = run["run_id"]
        snapshot = self.memory.kv_get(f"infusion_snapshot_{run_id}") or {}
        if not isinstance(snapshot, dict) or not snapshot:
            self.memory.update_infusion_run(run_id, status=InfusionRunStatus.FAILED.value, error="snapshot missing after restart")
            return True, "snapshot missing after restart"
        try:
            contract = self._execute(run, snapshot)
            self._persist(run, contract)
            if contract.get("_raw"):
                try:
                    self.memory.kv_set(f"infusion_raw_{run_id}", {"raw": contract["_raw"], "mode": run.get("mode")})
                except Exception:  # noqa: BLE001 — diagnostics are best effort
                    pass
            self.memory.update_infusion_run(run_id, status=InfusionRunStatus.COMPLETED.value, error="")
            self._activity(
                str(run.get("trigger") or "idle"),
                completed=True,
                run_id=run_id,
                mode=run.get("mode"),
                deduction_count=len(contract["deductions"]),
            )
            return True, None
        except (IncubationInfusionError, ContractError) as exc:
            self.memory.update_infusion_run(run_id, status=InfusionRunStatus.FAILED.value, error=str(exc)[:400])
            return True, str(exc)[:400]
        except Exception as exc:  # noqa: BLE001 — persist any failure and keep the worker alive
            self.memory.update_infusion_run(run_id, status=InfusionRunStatus.FAILED.value, error=str(exc)[:400])
            return True, str(exc)[:400]

    def _execute(self, run: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
        if run.get("mode") == InfusionMode.OPENCODE.value:
            return self._execute_opencode(run, snapshot)
        contract = self._execute_native(snapshot)
        if contract is None:
            raise IncubationInfusionError("native infuson pass returned no parseable contract")
        return contract

    def _execute_native(self, snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
        if self.llm is None or not callable(getattr(self.llm, "chat", None)):
            raise IncubationInfusionError("infusion llm is not configured")
        system = _INFUSION_SYSTEM + "\n\nSnapshot:\n" + (__import__("json").dumps(snapshot, ensure_ascii=False))
        needs = [
            {"role": "system", "content": system},
            {"role": "user", "content": "Produce the infusion JSON contract for this pass."},
        ]
        base_url = str(getattr(self.llm, "base_url", "") or "").strip()
        # enable_thinking is an entrim-only knob (sent as chat_template_kwargs);
        # OpenAI-compatible providers reject unknown body keys, so never send it
        # to OpenRouter or similar gateways.
        enable_thinking = False if "entrim" in base_url else None
        raw = ""
        last_error = ""
        for _attempt in range(2):
            try:
                kwargs: dict[str, Any] = {
                    "json_mode": True,
                    "temperature": 0.2,
                    "max_tokens": int(self.settings.max_tokens_per_pass),
                    "timeout_seconds": 90,
                    "max_retries": 1,
                }
                if enable_thinking is not None:
                    kwargs["enable_thinking"] = enable_thinking
                raw = self.llm.chat(needs, **kwargs)
                if str(raw or "").strip():
                    break
                last_error = "empty completion"
            except Exception as exc:  # noqa: BLE001 — one retry for the durable pass
                last_error = str(exc)[:400]
                if _attempt == 1:
                    raise IncubationInfusionError(f"infusion native pass failed: {last_error}") from exc
        if not str(raw or "").strip():
            raise IncubationInfusionError(f"infusion native pass returned an empty completion{('; ' + last_error) if last_error else ''}")
        return parse_infusion_contract(raw)

    def _execute_opencode(self, run: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
        if self.opencode_runner is None:
            raise IncubationInfusionError("opencode engine is unavailable")
        if self.runner_context is None:
            raise IncubationInfusionError("opencode runner context is unavailable")
        opencode_error = ""
        partial_raw = ""
        try:
            result = self.opencode_runner(
                {**self.runner_context, "config": self.config},
                snapshot,
                run.get("session_id") or "",
            )
        except Exception as exc:  # noqa: BLE001
            opencode_error = str(exc)[:400]
            partial = getattr(exc, "result", None)
            if isinstance(partial, Mapping):
                parts = partial.get("raw_tail") or partial.get("reply") or ""
                if isinstance(parts, list):
                    partial_raw = "\n".join(str(line) for line in parts[-60:])
                elif isinstance(parts, str):
                    partial_raw = parts
            if opencode_error:
                try:
                    self.memory.record_action("infusion_opencode_error", f"{run.get('run_id')}: {opencode_error[:240]}")
                except Exception:  # noqa: BLE001
                    pass
        if not opencode_error and not isinstance(result, Mapping):
            opencode_error = "opencode pass returned nothing"
        raw = partial_raw
        if not opencode_error and isinstance(result, Mapping):
            raw = str(result.get("reply") if isinstance(result, Mapping) else "") or ""
            raw_tail = result.get("raw_tail") or []
            if isinstance(raw_tail, list) and raw_tail and not str(raw).strip():
                raw = "\n".join(str(line) for line in raw_tail[-60:])
            run_id = str(run.get("run_id") or "")
            if run_id:
                try:
                    self.memory.kv_set(f"infusion_raw_{run_id}", {"raw": raw[:6000], "stage": "opencode", "tool_calls": len(result.get("tool_calls") or []), "used_pipeworx": bool(result.get("used_pipeworx"))})
                except Exception:  # noqa: BLE001
                    pass
        contract = parse_infusion_contract(raw)
        if contract is not None:
            contract["_raw"] = str(raw)[:6000]
            if opencode_error:
                contract["_opencode_error"] = opencode_error
            if not opencode_error and isinstance(result, Mapping):
                for item in contract["deductions"]:
                    item["discovered_by"] = "pipeworx" if result.get("used_pipeworx") else "opencode"
            return contract
        if self.settings.mode == "auto" and not opencode_error:
            native = self._execute_native(snapshot)
            if native is not None:
                return native
        if self.settings.mode == "auto" and opencode_error:
            try:
                native = self._execute_native(snapshot)
                if native is not None:
                    return native
            except Exception:  # noqa: BLE001 — the opencode error is the better diagnostic
                pass
        detail = opencode_error or (f"no parseable contract in reply: {str(raw)[:200]}" if raw else "empty opencode reply")
        raise IncubationInfusionError(f"opencode pass failed: {detail}")

    def _persist(self, run: Mapping[str, Any], contract: Mapping[str, Any]) -> list[str]:
        from ..core.incubation_contracts import IncubationDeduction

        run_id = str(run.get("run_id") or "")
        session_id = str(run.get("session_id") or "")
        created_at = self.now()
        saved_ids: list[str] = []
        existing_hashes = {
            str(item.get("deduction_hash") or "") for item in self.memory.list_incubation_deductions(limit=500)
        }
        step = 1
        owner_terms = _owner_terms(self.memory)
        for payload in list(contract.get("deductions") or []):
            payload = dict(payload)
            summary_text = str(payload.get("summary") or "")
            if _system_term_leak(summary_text, owner_terms):
                # A deduction about the engine itself (or about a term the owner
                # never used) is scaffolding noise, never business knowledge.
                continue
            dedupe = _dedupe_hash(payload)
            if dedupe in existing_hashes:
                continue
            deduction_id = "deduction_" + dedupe[:32]
            deduction = IncubationDeduction.from_dict({
                "deduction_id": deduction_id,
                "kind": payload.get("kind"),
                "summary": payload.get("summary"),
                "confidence": payload.get("confidence", 0.4),
                "basis": payload.get("basis", "hypothesis"),
                "source_refs": payload.get("source_refs") or [],
                "supports_paths": payload.get("supports_paths") or [],
                "horizon_questions": contract.get("horizon_questions") or [],
                "discovered_by": payload.get("discovered_by") or "native",
                "citation_uris": payload.get("citation_uris") or [],
                "run_id": run_id,
                "created_at": created_at,
                "step": step,
            })
            self.memory.save_incubation_deduction(deduction)
            saved_ids.append(deduction_id)
            existing_hashes.add(dedupe)
            step += 1
        followup = list(contract.get("followup_research") or [])
        if followup:
            self._enqueue_followup_research(run, followup)
        genesis_notes = contract.get("genesis_notes") or {}
        if genesis_notes and self.genesis_service is not None:
            self._apply_genesis_notes(run, genesis_notes, session_id)
        return saved_ids

    def _enqueue_followup_research(self, run: Mapping[str, Any], followup: Sequence[Mapping[str, Any]]) -> None:
        if self.research_service is None:
            return
        owner_terms = _owner_terms(self.memory)
        if not owner_terms:
            # No owner vocabulary yet means no business to research: never let
            # a model turn empty context into research subjects.
            return
        session_rows = self.memory.list_design_intake_sessions(limit=1)
        session_revision = 0
        if session_rows:
            session = self.memory.get_design_intake_session(session_rows[0]["session_id"])
            try:
                session_revision = int((session or {}).get("revision") or 0)
            except (TypeError, ValueError):
                session_revision = 0
        for item in list(followup)[:4]:
            kind = str(item.get("type") or "").strip().lower()
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            if _system_term_leak(f"{query} {item.get('reason') or ''}", owner_terms):
                # A proposal about the engine itself (or a term the owner never
                # used) is scaffolding noise, never a research subject.
                continue
            body: dict[str, Any] = {"trigger": ResearchTrigger.INFUSION.value, "fetch": True}
            if session_revision > 0:
                body["intake_revision"] = session_revision
            if kind == "feed":
                body["feed_urls"] = [query]
                body["subjects"] = [str(item.get("reason") or query)[:200]]
            elif kind == "community":
                body["candidate_communities"] = [{"name": query, "status": "candidate"}]
                body["subjects"] = [str(item.get("reason") or query)[:200]]
            else:
                body["query"] = query
            try:
                self.research_service.request(body, enqueue=True)
            except Exception:  # noqa: BLE001 — follow-up research is best effort
                pass

    def _apply_genesis_notes(self, run: Mapping[str, Any], notes: Mapping[str, Any], session_id: str) -> None:
        try:
            current = self.genesis_service.current().to_dict() if self.genesis_service is not None else {}
            from ..core.incubation_contracts import CustomerAdaGenesis

            current = CustomerAdaGenesis.from_dict(current) if current else CustomerAdaGenesis.empty()
            business_world = dict(current.business_world)
            creative_identity = dict(current.creative_identity)
            for key in ("values", "tensions", "customer_promises"):
                if notes.get("business_world", {}).get(key):
                    business_world[key] = _merge(business_world.get(key), notes["business_world"][key])
            for key in ("principles", "developing_tastes", "patterns_to_avoid"):
                if notes.get("creative_identity", {}).get(key):
                    creative_identity[key] = _merge(creative_identity.get(key), notes["creative_identity"][key])
            updated = CustomerAdaGenesis(
                revision=current.revision + 1,
                business_world=business_world,
                relationship=dict(current.relationship),
                creative_identity=creative_identity,
                research_identity=dict(current.research_identity),
                evidence=list(current.evidence) + [
                    GenesisEvidence(
                        origin=EvidenceOrigin.ADA_REFLECTION.value,
                        basis="background infusion pass",
                        detail={"run_id": run.get("run_id") or ""},
                        reference_id=str(session_id or ""),
                    )
                ],
            )
            self.memory.save_customer_genesis_revision(updated, source_kind="infusion", expected_revision=current.revision)
        except Exception:  # noqa: BLE001 — genesis notes are best effort
            pass

    def close(self) -> None:
        pass


def _merge(previous: Any, new: Any) -> list[str]:
    if not isinstance(previous, list):
        previous = [str(previous)] if previous else []
    if isinstance(new, str):
        new = [new]
    if not isinstance(new, list):
        return list(previous)
    seen = {str(item).strip().casefold() for item in previous}
    merged = list(previous)
    for item in new:
        key = str(item).strip().casefold()
        if key and key not in seen:
            seen.add(key)
            merged.append(str(item).strip()[:200])
    return merged[:50]


class IncubationInfusionExecutor:
    """Run pending infusion passes without blocking conversational HTTP calls."""

    def __init__(
        self,
        service: IncubationInfusionService,
        *,
        interval: float = 3.0,
        on_finished: Callable[[str, str | None], None] | None = None,
    ) -> None:
        self.service = service
        self.interval = max(0.5, float(interval))
        self.on_finished = on_finished
        self.worker = f"infusion-{time.time_ns()}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_idle_check = 0.0

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.memory_requeue()
        self._thread = threading.Thread(target=self._loop, name="infusion-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def memory_requeue(self) -> None:
        try:
            self.service.memory.requeue_abandoned_infusion_runs()
        except Exception:  # noqa: BLE001
            pass

    def process_one(self) -> bool:
        finished, error = self.service.process_one(self.worker)
        if finished:
            if self.on_finished is not None:
                try:
                    run = [item for item in self.service.memory.list_infusion_runs(limit=1)]
                    self.on_finished(run[0]["run_id"] if run else "", error)
                except Exception:  # noqa: BLE001
                    pass
            return True
        return False

    def _idle_signal(self) -> None:
        now = time.monotonic()
        if now - self._last_idle_check < self.service.settings.idle_seconds:
            return
        self._last_idle_check = now
        try:
            latest = self.service.memory.list_infusion_runs(limit=1)
            snapshot = self.service.build_context_snapshot()
            if snapshot is None:
                return
            current_hash = snapshot_hash(snapshot)
            recent_hashes = {str(item.get("snapshot_hash") or "") for item in self.service.memory.list_infusion_runs(limit=10)}
            if current_hash in recent_hashes:
                return
            session_rows = self.service.memory.list_design_intake_sessions(limit=1)
            session_id = session_rows[0]["session_id"] if session_rows else ""
            self.service.enqueue(trigger="idle", session_id=session_id, snapshot=snapshot)
        except Exception:  # noqa: BLE001 — idle signalling is best effort
            pass

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.process_one():
                    self._idle_signal()
                    self._stop.wait(self.interval)
            except Exception:
                self._stop.wait(self.interval)


__all__ = [
    "IncubationInfusionError",
    "IncubationInfusionExecutor",
    "IncubationInfusionService",
    "build_infusion_snapshot",
    "parse_infusion_contract",
    "snapshot_hash",
]