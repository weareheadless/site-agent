"""Persist the first-site plan from the confirmed brief and verified candidate."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from ..core.contracts import Artifact, ArtifactKind
from ..core.design_contracts import DesignPhase, SiteIntake, canonical_hash


REPORT_RENDERER = "helloada-onboarding-report-v1"


def persist_initial_onboarding_report(memory, run: Mapping[str, Any]) -> dict[str, Any] | None:
    """Save one immutable, evidence-bound report for a reviewable first site.

    This phase is intentionally assembled from persisted owner facts and host
    validation evidence; it does not call a model, repeat research, or claim
    traffic/search findings before launch.
    """
    if (
        str(run.get("operation_kind") or "initial_build") != "initial_build"
        or str(run.get("mode") or "") != "production_candidate"
        or str(run.get("status") or "") != "ready_for_review"
    ):
        return None

    from .designs import owner_review_requirements_met

    if not owner_review_requirements_met(run):
        return None

    candidate_sha = str(run.get("candidate_sha") or "").strip().lower()
    intake_hash = str(run.get("intake_hash") or "").strip().lower()
    if len(candidate_sha) != 40 or len(intake_hash) != 64:
        raise ValueError("the first-site report requires exact candidate and brief identities")

    intake = SiteIntake.from_dict(run.get("intake_json") or {})
    quality = run.get("quality_report_json") if isinstance(run.get("quality_report_json"), Mapping) else {}
    quality_hash = canonical_hash(dict(quality))
    context_hash = str(run.get("context_snapshot_hash") or "").strip().lower()
    variant_key = "-".join((candidate_sha[:12], intake_hash[:12], quality_hash[:12], context_hash[:12] or "no-context"))
    claim = memory.claim_design_phase(
        str(run["run_id"]),
        DesignPhase.ONBOARDING_REPORT.value,
        variant_key=variant_key,
        base_sha=candidate_sha,
        context_snapshot_hash=str(run.get("context_snapshot_hash") or ""),
        input_hashes=(candidate_sha, intake_hash, quality_hash, *((context_hash,) if context_hash else ())),
        max_attempts=2,
        provider_id="site-agent",
        model=REPORT_RENDERER,
    )
    if not claim.get("claimed"):
        return claim

    try:
        request = run.get("planning_json") if isinstance(run.get("planning_json"), Mapping) else {}
        build_request = request.get("build_request") if isinstance(request.get("build_request"), Mapping) else {}
        # This operation is specifically the first homepage build; source file
        # paths such as app/page.tsx are not customer-facing routes.
        route = "/"
        required_pages = [str(page) for page in intake.site.get("required_pages", []) if str(page) not in {"/", "home", "index.html"}]
        gates = quality.get("gates") if isinstance(quality.get("gates"), Mapping) else {}
        snapshot = run.get("context_snapshot") if isinstance(run.get("context_snapshot"), Mapping) else {}
        research = []
        for item in snapshot.get("research", ()):
            if not isinstance(item, Mapping):
                continue
            summary = str(item.get("text") or "").strip()
            if not summary:
                continue
            metadata = item.get("meta") if isinstance(item.get("meta"), Mapping) else {}
            raw_url = str(metadata.get("url") or metadata.get("source_url") or "").strip()
            try:
                parsed_url = urlsplit(raw_url)
            except ValueError:
                continue
            if raw_url and (parsed_url.scheme != "https" or not parsed_url.netloc):
                continue
            url = raw_url
            research.append({
                "summary": summary[:500],
                "source": str(item.get("source") or "research")[:80],
                "title": str(metadata.get("title") or (parsed_url.hostname if raw_url else "") or "Research note")[:180],
                "url": url,
            })
            if len(research) == 5:
                break
        audience = str(intake.audience.get("primary") or "").strip()
        offer = str(intake.business.get("offer_summary") or "").strip()
        primary_action = str(intake.conversion.get("primary_action") or "").strip()
        voice = str(intake.brand.get("voice") or "").strip()
        focus = " ".join(part for part in (
            f'The homepage makes “{primary_action[:140]}” the clear next step for {audience[:180]}.' if primary_action and audience else "",
            f'It introduces {offer[:300]} in a {voice[:120]} voice.' if offer and voice else "",
        )).strip()[:800]
        report = {
            "schema_version": 1,
            "brief_revision": run.get("intake_revision_id"),
            "brief_hash": intake_hash,
            "candidate_sha": candidate_sha,
            "quality_evidence_hash": quality_hash,
            "context_snapshot_hash": str(run.get("context_snapshot_hash") or ""),
            "title": "Your first website and what comes next",
            "summary": focus or "A practical plan based on your confirmed brief and Ada’s verified first-page candidate.",
            "business": {
                "name": intake.business.get("name", ""),
                "offer": intake.business.get("offer_summary", ""),
                "audience": intake.audience.get("primary", ""),
                "primary_action": intake.conversion.get("primary_action", ""),
                "brand_voice": intake.brand.get("voice", ""),
            },
            "evidence": {
                "research": research,
                "research_available": bool(research),
                "unknowns": list(intake.unknowns[:8]),
            },
            "first_page": {
                "route": route,
                "status": "verified_for_owner_review",
                "passed_checks": sorted(str(key) for key, value in gates.items() if value == "passed"),
            },
            "planned_pages": required_pages,
            "next_steps": [
                {"key": "launch_after_review", "evidence": "verified_candidate", "requires_owner": True},
                {"key": "complete_site_pages", "evidence": "confirmed_brief", "pages": required_pages, "requires_owner": True},
                {"key": "establish_growth_baseline", "evidence": "after_launch", "requires_owner": True},
                {"key": "plan_content_from_real_search_data", "evidence": "after_search_data", "requires_owner": True},
            ],
            "limits": {
                "live_metrics_available": False,
                "explanation": "live_data_starts_after_launch",
            },
        }
        digest = canonical_hash(report)
        artifact = memory.create_artifact(Artifact(
            kind=ArtifactKind.DESIGN_PHASE,
            title=report["title"],
            summary=report["summary"],
            renderer=REPORT_RENDERER,
            capability_id="website.initial_onboarding_report",
            provider_id="site-agent",
            content_hash=digest,
            preview_data=report,
        ))
        return memory.complete_design_phase(
            int(claim["id"]),
            report,
            output_hash=digest,
            artifact_id=int(artifact.artifact_id),
        )
    except Exception as exc:
        memory.fail_design_phase(
            int(claim["id"]),
            error_code="onboarding_report_failed",
            error_detail=str(exc)[:500],
        )
        raise
