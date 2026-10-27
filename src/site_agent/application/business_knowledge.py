"""Retired local business-knowledge API; retained as an explicit fence."""


class BusinessKnowledgeError(ValueError):
    pass


class BusinessKnowledgeService:
    """Compatibility boundary that refuses all access to the legacy table."""

    def __init__(self, memory=None, approvals=None, actions=None):
        self.memory = memory
        self.approvals = approvals
        self.actions = actions

    @staticmethod
    def _retired(*_args, **_kwargs):
        raise BusinessKnowledgeError("local business knowledge is retired; use the CrawlSEO authority")

    propose = _retired
    confirm = _retired
    decline = _retired
    search = _retired


__all__ = ["BusinessKnowledgeError", "BusinessKnowledgeService"]
