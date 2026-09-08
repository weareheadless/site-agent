from site_agent.application.renderers import render_artifact
from site_agent.core.contracts import Artifact, ArtifactKind


def _artifact(renderer, preview_data, kind=ArtifactKind.SITE_CHANGE):
    return Artifact(
        kind=kind,
        title="Prepared work",
        summary="A concise owner summary.",
        renderer=renderer,
        capability_id="test.prepare",
        provider_id="test",
        content_hash="sha256:test",
        preview_data=preview_data,
    )


def test_site_change_renderer_hides_operations_and_raw_paths():
    preview = render_artifact(_artifact("site_change", {
        "body": "The homepage will have a clearer invitation.",
        "files": ["index.html", "styles.css"],
        "ops": [{"path": "secret/internal/path", "value": "do not show"}],
    }))
    result = preview.to_dict()
    assert result["sections"] == [{"label": "What changes", "body": "The homepage will have a clearer invitation."}]
    assert "secret/internal/path" not in str(result)


def test_site_change_renderer_accepts_explicit_owner_areas():
    preview = render_artifact(_artifact("site_change", {"areas": ["Homepage", "Navigation"]}))
    assert preview.sections[1].to_dict() == {"label": "Areas involved", "body": "Homepage, Navigation"}


def test_business_information_renderer_normalizes_fields():
    preview = render_artifact(_artifact("business-information", {
        "course_name": "Breathwork",
        "seats": 6,
        "provider_id": "hidden-provider",
    }))
    assert preview.sections[0].body == "Course name: Breathwork\nSeats: 6"


def test_business_information_renderer_shows_before_and_after_values():
    preview = render_artifact(_artifact("business_information", {
        "before": {"course_name": "Old course", "provider_id": "hidden"},
        "after": {"course_name": "New course"},
    }))
    assert [section.to_dict() for section in preview.sections] == [
        {"label": "Before", "body": "Course name: Old course"},
        {"label": "After", "body": "Course name: New course"},
    ]


def test_social_post_has_a_reserved_typed_renderer():
    preview = render_artifact(_artifact("social_post", {"text": "A calm update."}))
    assert preview.renderer == "social_post"
    assert preview.sections[0].body == "A calm update."


def test_seo_report_renderer_keeps_the_report_as_a_read_only_artifact():
    preview = render_artifact(_artifact(
        "seo_report",
        {"body": "# Monthly SEO report\n\nEvidence and recommendations."},
        ArtifactKind.SEO_REPORT,
    ))
    assert preview.renderer == "seo_report"
    assert preview.sections[0].body.startswith("# Monthly SEO report")
