from types import SimpleNamespace

import pytest

from site_agent.application.workspace import BridgeError, ChatService
from site_agent.core.memory import Memory
from site_agent.core.payload_receipts import payload_revision_manifest

REVISION = "sha256:" + "a" * 64


def _effect(**overrides):
    effect = {
        "kind": "collection",
        "operation": "update",
        "target": "pages",
        "document_id": "2",
        "revision": REVISION,
        "locale": "en",
        "fields": ["summary"],
        "summary": "About page copy",
        "base_version_id": "11",
    }
    effect.update(overrides)
    return effect


class RecordingGateway:
    def __init__(self, fail_on: str | None = None, status_on: tuple[str, int] | None = None):
        self.calls = []
        self.fail_on = fail_on
        self.status_on = status_on

    def restore_revision(self, target, document_id, version_id, *, locale=None, expected_hash=None):
        from site_agent.hands.payload_gateway import PayloadGatewayError

        self.calls.append(("collection", target, document_id, version_id, locale, expected_hash))
        if self.status_on and self.status_on[0] == document_id:
            raise PayloadGatewayError("conflict", status_code=self.status_on[1])
        if self.fail_on == document_id:
            raise RuntimeError("gateway refused")
        return {"id": document_id}

    def restore_global_revision(self, target, version_id, *, locale=None, expected_hash=None):
        self.calls.append(("global", target, None, version_id, locale, expected_hash))
        return {"siteName": "OceanicVibes"}


def _service(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    return ChatService(memory, object()), memory


def test_the_manifest_binds_the_exact_base_version_into_its_hash():
    manifest, digest = payload_revision_manifest([_effect()])
    assert manifest[0]["base_version_id"] == "11"
    _, other = payload_revision_manifest([_effect(base_version_id="12")])
    assert digest != other
    _, without = payload_revision_manifest([_effect(base_version_id="")])
    assert digest != without


def test_a_receipt_written_before_base_versions_keeps_its_canonical_form():
    # A stored draft receipt must still normalize to itself, or every review
    # approved before this field existed would fail its own hash check.
    legacy = {key: value for key, value in _effect().items() if key != "base_version_id"}
    manifest, _ = payload_revision_manifest([legacy])
    assert manifest == [legacy]
    assert "base_version_id" not in manifest[0]


def test_the_manifest_rejects_an_unsafe_base_version_identity():
    with pytest.raises(ValueError, match="invalid base version"):
        payload_revision_manifest([_effect(base_version_id="../../etc/passwd")])


def test_discarding_a_design_draft_restores_its_exact_content_versions(tmp_path):
    service, memory = _service(tmp_path)
    try:
        gateway = RecordingGateway()
        tenant = SimpleNamespace(context={"payload_gateway": gateway})
        draft = {
            "meta": {
                "payload_effects": [
                    _effect(),
                    _effect(kind="global", target="navigation", document_id="navigation", base_version_id="7"),
                ],
            },
        }
        result = service._restore_draft_content(draft, tenant)
        assert [call[0] for call in gateway.calls] == ["collection", "global"]
        assert gateway.calls[0][3] == "11"
        assert gateway.calls[0][5] == REVISION
        assert gateway.calls[1][1] == "navigation"
        assert gateway.calls[1][3] == "7"
        assert len(result["restored"]) == 2
        assert result["unsupported"] == []
        assert result["superseded"] == []
    finally:
        memory.close()


def test_a_revision_without_a_recorded_base_version_is_reported_not_guessed(tmp_path):
    service, memory = _service(tmp_path)
    try:
        gateway = RecordingGateway()
        tenant = SimpleNamespace(context={"payload_gateway": gateway})
        result = service._restore_draft_content(
            {"meta": {"payload_effects": [_effect(base_version_id="")]}},
            tenant,
        )
        assert gateway.calls == []
        assert result["restored"] == []
        assert result["unsupported"] == [
            {"target": "pages", "document_id": "2", "reason": "no-recorded-base-version"},
        ]
    finally:
        memory.close()


def test_content_changed_after_the_draft_is_left_alone_not_overwritten(tmp_path):
    service, memory = _service(tmp_path)
    try:
        gateway = RecordingGateway(status_on=("2", 409))
        tenant = SimpleNamespace(context={"payload_gateway": gateway})
        result = service._restore_draft_content({"meta": {"payload_effects": [_effect()]}}, tenant)
        assert result["restored"] == []
        assert result["superseded"] == [
            {"target": "pages", "document_id": "2", "version_id": "11", "reason": "changed-after-draft"},
        ]
    finally:
        memory.close()


def test_a_vanished_version_is_reported_and_the_rest_survives(tmp_path):
    service, memory = _service(tmp_path)
    try:
        gateway = RecordingGateway(status_on=("2", 404))
        tenant = SimpleNamespace(context={"payload_gateway": gateway})
        result = service._restore_draft_content({"meta": {"payload_effects": [_effect()]}}, tenant)
        assert result["superseded"][0]["reason"] == "version-not-found"
    finally:
        memory.close()


def test_a_failed_content_restore_aborts_the_discard(tmp_path):
    service, memory = _service(tmp_path)
    try:
        tenant = SimpleNamespace(context={"payload_gateway": RecordingGateway(fail_on="2")})
        with pytest.raises(BridgeError, match="could not be restored exactly"):
            service._restore_draft_content({"meta": {"payload_effects": [_effect()]}}, tenant)
    finally:
        memory.close()
