from site_agent.application.customer_genesis import CustomerGenesisService
from site_agent.core.design_contracts import SiteIntake
from site_agent.core.design_intake_contracts import DesignIntakeDraft, IntakeFieldProvenance
from site_agent.core.incubation_contracts import EvidenceOrigin
from site_agent.core.memory import Memory


def _intake():
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {"name": "Working business", "offer_summary": "A clear service", "primary_services": ["A clear service"]},
        "audience": {"primary": "People evaluating the service"},
        "conversion": {"primary_action": "Get in touch", "not_available": True},
        "brand": {"voice": "Clear and warm"},
        "site": {"required_pages": ["index.html"]},
    })


def test_genesis_revision_keeps_owner_evidence_and_is_immutable(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    try:
        conversation_id = memory.create_conversation("intake")
        draft = DesignIntakeDraft.from_site_intake(_intake())
        memory.create_design_intake_session("intake-" + "a" * 32, draft, conversation_id=conversation_id)
        session = memory.get_design_intake_session("intake-" + "a" * 32)
        service = CustomerGenesisService(memory)

        proposal = service.propose_from_session(session)
        assert proposal.revision == 1
        assert proposal.business_world["purpose"] == "A clear service"
        saved = service.save(proposal, source_kind="owner_confirmation")
        assert saved["genesis"].revision == 1
        assert saved["source_kind"] == "owner_confirmation"
        assert len(memory.list_customer_genesis_revisions()) == 1
    finally:
        memory.close()


def test_genesis_incorporates_qwen_asset_analysis_into_developing_tastes(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    try:
        conversation_id = memory.create_conversation("intake")
        draft = DesignIntakeDraft.from_site_intake(_intake())
        memory.create_design_intake_session("intake-" + "b" * 32, draft, conversation_id=conversation_id)
        session = memory.get_design_intake_session("intake-" + "b" * 32)
        session["assets"] = [
            {
                "id": 7,
                "name": "logo.webp",
                "description": "A warm, hand-drawn logotype on cream paper",
                "tags": ["editorial", "handmade"],
                "dominant_colors": ["#a0522d", "#f5f0e1"],
                "analysis": {
                    "description": "A warm, hand-drawn logotype on cream paper",
                    "tags": ["editorial", "handmade"],
                    "dominant_colors": ["#a0522d", "#f5f0e1"],
                    "ocr_text": "Mathilde Tapissier",
                },
            }
        ]
        service = CustomerGenesisService(memory)

        proposal = service.propose_from_session(session)

        tastes = " ".join(proposal.creative_identity["developing_tastes"])
        assert "hand-drawn logotype" in tastes
        assert "palette" in tastes
        assert "#a0522d" in tastes
        origins = {item.origin for item in proposal.evidence}
        assert EvidenceOrigin.ASSET_ANALYSIS.value in origins
        assert any(item.source_id == "asset:7" for item in proposal.evidence)
    finally:
        memory.close()


def test_genesis_preserves_bootstrap_observation_provenance(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    try:
        draft = DesignIntakeDraft.empty()
        for path, value in (
            ("business.offer_summary", "Observed but not owner-confirmed"),
            ("audience.primary", "Observed audience"),
            ("brand.voice", "Observed voice"),
        ):
            draft = draft.with_value(
                path,
                value,
                IntakeFieldProvenance(path=path, origin="assumed", note="migration snapshot"),
            )
        proposal = CustomerGenesisService(memory).propose_from_session({
            "session_id": "intake-" + "c" * 32,
            "draft": draft.to_dict(),
        })

        assert {item.origin for item in proposal.evidence} == {EvidenceOrigin.HOST_OBSERVATION.value}
        assert all(item.confidence == 0.2 for item in proposal.evidence)
    finally:
        memory.close()
