"""Deterministic intake assessment and design-brief compilation.

This policy only rearranges validated customer facts. It must not manufacture
claims, testimonials, locations, or conversion destinations.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..core.design_contracts import DesignBrief, IntakeAssessment, SiteIntake


def _texts(value) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def assess_intake(intake: SiteIntake) -> IntakeAssessment:
    """Return explicit gaps without filling them with invented business facts."""
    if not isinstance(intake, SiteIntake):
        raise TypeError("intake must be a validated SiteIntake")
    constraints = intake.constraints if isinstance(intake.constraints, Mapping) else {}
    blocking = _texts(constraints.get("blocking_questions"))[:1]
    contradictions = _texts(constraints.get("contradictions"))
    unknowns = list(intake.unknowns)
    if intake.conversion.get("not_available") is True:
        unknowns.append("A contact destination has not been supplied.")
    warnings: list[str] = []
    if intake.conversion.get("not_available") is True:
        warnings.append("Do not invent a contact destination or booking URL.")
    if not intake.business.get("verified_trust_evidence"):
        warnings.append("No verified trust evidence was supplied; do not add testimonials or certifications.")
    return IntakeAssessment(
        complete_enough=not blocking and not contradictions,
        blocking_questions=blocking,
        non_blocking_unknowns=tuple(dict.fromkeys(unknowns)),
        contradictions=contradictions,
        safe_defaults_applied=(
            "Use only supplied facts for trust and proof.",
            "Keep unavailable conversion destinations visibly unresolved.",
        ),
        warnings=tuple(warnings),
    )


def compile_brief(intake: SiteIntake, assessment: IntakeAssessment | None = None) -> DesignBrief:
    """Compile a typed brief from intake facts and an optional assessment."""
    if not isinstance(intake, SiteIntake):
        raise TypeError("intake must be a validated SiteIntake")
    assessment = assessment or assess_intake(intake)
    if not assessment.complete_enough:
        raise ValueError("intake is not complete enough for a design brief")

    business = intake.business
    audience = intake.audience
    conversion = intake.conversion
    services = _texts(business.get("primary_services"))
    pages = _texts((intake.site or {}).get("required_pages"))
    assets = tuple(str(item.get("id")).strip() for item in intake.assets if item.get("id"))
    offer = str(business.get("offer_summary") or "the stated offer").strip()
    audience_intent = str(audience.get("primary") or "Understand whether this offer is right for them.").strip()
    action = str(conversion.get("primary_action") or "Take the primary action.").strip()
    constraints = list(_texts(intake.brand.get("prohibited_claims")))
    constraints.extend(_texts((intake.constraints or {}).get("prohibited_claims")))
    constraints.extend(assessment.warnings)

    brief = DesignBrief(
        schema_version=1,
        intake_hash=intake.content_hash,
        business_objective=f"Present {offer} clearly and guide qualified visitors toward: {action}",
        audience_intent=audience_intent,
        primary_conversion=action,
        information_hierarchy=(
            f"Clarify the offer: {offer}",
            f"Show the relevant services: {', '.join(services)}",
            "Give visitors enough verified context to trust the next step.",
            f"Make the primary action clear: {action}",
        ),
        trust_strategy="Use only verified facts and provenance supplied in the intake; leave missing proof unresolved.",
        content_requirements=(
            offer,
            *services,
            *[f"Provide the required page: {page}" for page in pages],
        ),
        visual_objectives=(
            str(intake.brand.get("voice") or "Clear and specific").strip(),
            "Make the business, audience, and primary action legible in the first viewport.",
            "Avoid interchangeable industry-template composition.",
        ),
        constraints=tuple(dict.fromkeys(constraints)),
        required_pages=pages,
        supplied_assets=assets,
        success_hypotheses=(
            "A visitor can identify the offer and intended audience without guessing.",
            "The primary action is visible before decorative detail competes with it.",
        ),
        unresolved_unknowns=assessment.non_blocking_unknowns,
    )
    DesignBrief.from_dict(brief.to_dict())
    return brief


__all__ = ["assess_intake", "compile_brief"]
