"""Typed page strategy construction for the design builder."""

from __future__ import annotations

from collections.abc import Mapping

from ..core.design_contracts import (
    ArtDirection,
    DesignBrief,
    DesignContextSnapshot,
    IncubatedCreativeContext,
    PageBuildRequest,
    SiteIntake,
)


def initial_homepage_request(
    intake: SiteIntake,
    brief: DesignBrief,
    direction: ArtDirection,
    *,
    run_id: str,
    base_sha: str,
    context_snapshot: DesignContextSnapshot | None = None,
    creative_prompt: str = "",
) -> PageBuildRequest:
    """Turn intake into a complete initial homepage request.

    Direction hypotheses remain useful planning evidence, but an initial
    homepage is a creativity test.  The builder receives the validated intake
    and its deterministic brief, not a host-selected visual direction.
    """
    if not isinstance(intake, SiteIntake) or not isinstance(brief, DesignBrief) or not isinstance(direction, ArtDirection):
        raise TypeError("initial homepage strategy requires validated design contracts")
    return _homepage_request(
        intake,
        brief,
        run_id=run_id,
        base_sha=base_sha,
        context_snapshot=context_snapshot,
        creative_prompt=creative_prompt,
    )


def native_homepage_request(
    intake: SiteIntake,
    brief: DesignBrief,
    *,
    run_id: str,
    base_sha: str,
    context_snapshot: DesignContextSnapshot | None = None,
    creative_prompt: str = "",
) -> PageBuildRequest:
    """Build a factual request without selecting a visual direction.

    The compatibility ``initial_homepage_request`` helper still accepts an
    art-direction argument for older persisted workflows.  New native builds
    use this helper so OpenCode owns the visual hypothesis and implementation.
    """
    if not isinstance(intake, SiteIntake) or not isinstance(brief, DesignBrief):
        raise TypeError("native homepage request requires validated design contracts")
    return _homepage_request(
        intake,
        brief,
        run_id=run_id,
        base_sha=base_sha,
        context_snapshot=context_snapshot,
        creative_prompt=creative_prompt,
    )


def _homepage_request(
    intake: SiteIntake,
    brief: DesignBrief,
    *,
    run_id: str,
    base_sha: str,
    context_snapshot: DesignContextSnapshot | None,
    creative_prompt: str,
) -> PageBuildRequest:
    page_path = str((intake.site.get("required_pages") or ("index.html",))[0])
    request_data = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "initial_homepage",
        "base_sha": base_sha,
        "page_path": page_path,
        "purpose": brief.business_objective,
        "site_intake_hash": intake.content_hash,
        "acceptance_criteria": [
            *brief.success_hypotheses,
            *brief.content_requirements,
            "Use only supplied business facts and preserve unresolved unknowns.",
            "Develop and implement a subject-specific visual direction from the intake rather than copying an existing site or predetermined scaffold.",
            "Provide intentional desktop, tablet, mobile, and reduced-motion behavior.",
        ],
        "required_files": [page_path],
        "prohibited_files": ["content/articles/**", ".github/**", ".env*"],
        "supplied_media_paths": [],
        "supplied_media_asset_ids": [
            int(item["id"])
            for item in intake.assets
            if isinstance(item, Mapping)
            and str(item.get("usage") or "website").strip().lower() != "inspiration_only"
            and str(item.get("id") or "").isdigit()
        ],
        "content": {
            "site_intake": intake.to_dict(),
            "design_brief": brief.to_dict(),
            "creative_prompt": str(creative_prompt or "").strip(),
        },
    }
    if context_snapshot is not None:
        request_data["context_snapshot"] = context_snapshot.to_dict()
        request_data["context_snapshot_hash"] = context_snapshot.content_hash
        raw_incubated_context = context_snapshot.extra.get("incubated_creative_context")
        if raw_incubated_context is not None:
            request_data["incubated_creative_context"] = IncubatedCreativeContext.from_dict(raw_incubated_context).to_dict()
    request = PageBuildRequest.from_dict(request_data)
    return request


__all__ = ["initial_homepage_request", "native_homepage_request"]
