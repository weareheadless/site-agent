import pytest

from site_agent.application.business_knowledge import BusinessKnowledgeError, BusinessKnowledgeService
from site_agent.brain.editor import _tools_spec
from site_agent.core.media_worker import MediaWorker


@pytest.mark.parametrize("method,args", [
    ("propose", (object(), "fact")), ("confirm", (1,)), ("decline", (1,)), ("search", ("fact",)),
])
def test_legacy_business_knowledge_service_is_fenced(method, args):
    service = BusinessKnowledgeService(object())
    with pytest.raises(BusinessKnowledgeError, match="retired"):
        getattr(service, method)(*args)


def test_editor_does_not_expose_legacy_knowledge_search_tool():
    names = {tool["function"]["name"] for tool in _tools_spec({"config": {}})}
    assert "search_business_knowledge" not in names


def test_media_worker_does_not_wire_local_knowledge_producer():
    worker = MediaWorker({"memory": object(), "media_store": object(), "media_service": object(),
                          "business_knowledge_service": object()})
    assert not hasattr(worker, "knowledge")
