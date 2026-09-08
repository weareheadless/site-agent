"""Small, typed art-direction hypothesis policy.

The hypotheses are intentionally inexpensive. They make the creative choice
inspectable before a builder receives a request, while keeping customer facts
separate from visual decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.design_contracts import ArtDirection, DesignBrief, SiteIntake


def _location(intake: SiteIntake) -> str:
    business = intake.business
    for key in ("location", "service_area", "place"):
        value = business.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)) and value:
            return ", ".join(str(item).strip() for item in value if str(item).strip())
    return "the customer's stated context"


@dataclass(frozen=True)
class DirectionSelection:
    selected: ArtDirection
    rejected: tuple[ArtDirection, ...]
    rationale: str

    def to_dict(self) -> dict:
        return {
            "selected": self.selected.to_dict(),
            "rejected": [direction.to_dict() for direction in self.rejected],
            "rationale": self.rationale,
        }


def hypotheses(intake: SiteIntake, brief: DesignBrief) -> tuple[ArtDirection, ...]:
    """Generate three distinct directions grounded in the supplied offer."""
    name = str(intake.business.get("name") or "the business").strip()
    offer = str(intake.business.get("offer_summary") or "the offer").strip()
    audience = brief.audience_intent
    place = _location(intake)
    relevance = f"{name} needs to explain {offer} to {audience}."
    options = (
        ArtDirection(
            schema_version=1,
            name="tideline-editorial",
            thesis=f"An editorial, place-aware system that gives {place} and the offer room to be understood.",
            business_relevance=relevance,
            composition_strategy="Strong first-viewport thesis followed by a deliberate editorial sequence, not a card grid.",
            typography_strategy="A characterful display face for point of view paired with a restrained reading face for proof and detail.",
            color_and_material_strategy="Use a restrained field, one precise accent, and tactile separators that clarify sections without decoration overload.",
            image_strategy="Treat supplied imagery as evidence and atmosphere; use intentional crops with a clear focal subject.",
            motion_strategy="Use slow, meaningful reveals between editorial chapters; no motion should delay the primary action.",
            signature_gesture=f"A single tide-line rule changes position at the transition from {offer} to the next step.",
            mobile_translation="Collapse the editorial sequence into short, high-contrast chapters while preserving the first-viewport action.",
            reduced_motion_translation="Keep the tide-line and chapter order static with no required transitions.",
            conversion_strategy=f"Make {brief.primary_conversion} a visible decision point after the offer is understood.",
            template_risk="Medium: the editorial language must remain specific to the supplied offer and place.",
            implementation_risks=("Requires disciplined type scale and image cropping.",),
        ),
        ArtDirection(
            schema_version=1,
            name="working-material",
            thesis=f"A material-led system that makes the work behind {name} visible without manufacturing proof.",
            business_relevance=relevance,
            composition_strategy="Layered surfaces and process-led sections create a clear path from problem to qualified action.",
            typography_strategy="Practical, highly legible text with a compact display treatment for labels and process stages.",
            color_and_material_strategy="Build hierarchy with surface contrast, borders, and one grounded accent rather than a large color palette.",
            image_strategy="Use close details, tools, spaces, or supplied visual references only when their provenance and role are clear.",
            motion_strategy="Use restrained state changes to show sequence or progress, never ambient looping movement.",
            signature_gesture="A recurring registration mark anchors one process transition and appears nowhere else by default.",
            mobile_translation="Turn layers into a single readable stack; preserve process order and keep decorative surfaces optional.",
            reduced_motion_translation="Replace state changes with visible labels, borders, and ordered content.",
            conversion_strategy=f"Answer the audience's practical hesitation before presenting {brief.primary_conversion}.",
            template_risk="Low to medium: material cues must come from the business rather than a generic craft aesthetic.",
            implementation_risks=("Needs careful contrast testing across layered surfaces.",),
        ),
        ArtDirection(
            schema_version=1,
            name="quiet-kinetic",
            thesis=f"A calm, responsive rhythm that lets visitors feel the difference in {offer} without spectacle.",
            business_relevance=relevance,
            composition_strategy="Alternating dense and open bands establish pace, with the primary action repeated only at meaningful decisions.",
            typography_strategy="Generous measure and a clear typographic rhythm; display treatment is reserved for the main promise.",
            color_and_material_strategy="Use tonal depth and a focused accent to make hierarchy visible without relying on gradients or novelty.",
            image_strategy="Give each supplied image one compositional job and provide a deliberate crop fallback for narrow screens.",
            motion_strategy="Use small directional movement to reinforce sequence and orientation, with no autoplay dependency.",
            signature_gesture="One subject-specific visual pulse marks the handoff from understanding to action, then resolves into stillness.",
            mobile_translation="Keep the alternating rhythm through spacing and order rather than side-by-side layouts or tiny type.",
            reduced_motion_translation="Retain the pulse as a static accent and preserve all meaning in content and structure.",
            conversion_strategy=f"Let the calm rhythm reduce uncertainty, then make {brief.primary_conversion} unmistakable.",
            template_risk="Medium: the calm direction must not become empty minimalism or generic luxury styling.",
            implementation_risks=("Requires restraint so motion and whitespace do not reduce useful content density.",),
        ),
    )
    return tuple(ArtDirection.from_dict(direction.to_dict()) for direction in options)


def select_direction(intake: SiteIntake, brief: DesignBrief) -> DirectionSelection:
    """Choose one direction using explicit preferences when supplied."""
    options = hypotheses(intake, brief)
    preferences = intake.brand.get("visual_preferences")
    preference_text = " ".join(str(item).lower() for item in (preferences or [])) if isinstance(preferences, (list, tuple)) else str(preferences or "").lower()
    selected_index = 0
    if any(word in preference_text for word in ("material", "process", "tactile")):
        selected_index = 1
    elif any(word in preference_text for word in ("calm", "kinetic", "rhythm", "motion")):
        selected_index = 2
    selected = replace(options[selected_index], selected=True)
    rejected = tuple(
        replace(direction, rejection_reason="Not selected for this run; retained as an explicit alternative.")
        for index, direction in enumerate(options)
        if index != selected_index
    )
    rationale = (
        f"Selected {selected.name} because it best connects the supplied offer and audience intent "
        "while preserving a distinct mobile and reduced-motion translation."
    )
    return DirectionSelection(selected=selected, rejected=rejected, rationale=rationale)


__all__ = ["DirectionSelection", "hypotheses", "select_direction"]
