from site_agent.core.jobs import _journal_enabled


def test_journal_defaults_to_instance_setting():
    class Memory:
        def kv_get(self, key, default=None):
            return default

    context = {"config": {"blog": {"journal_enabled": False}}, "memory": Memory()}
    assert _journal_enabled(context) is False
    context["config"]["blog"]["journal_enabled"] = True
    assert _journal_enabled(context) is True


def test_memory_override_can_enable_journal():
    class Memory:
        def kv_get(self, key, default=None):
            return True

    context = {"config": {"blog": {"journal_enabled": False}}, "memory": Memory()}
    assert _journal_enabled(context) is True
