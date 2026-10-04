import pytest

from site_agent.core.jobs import _editorial_enabled
from site_agent.core.memory import Memory


def test_editorial_defaults_to_instance_setting(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    context = {"config": {"editorial": {"enabled": False}}, "memory": memory}
    assert _editorial_enabled(context) is False
    context["config"]["editorial"]["enabled"] = True
    assert _editorial_enabled(context) is True
    memory.close()


def test_memory_override_controls_editorial_schedule(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    context = {"config": {"editorial": {"enabled": False}}, "memory": memory}
    context["memory"].kv_set("editorial_enabled", True)
    assert _editorial_enabled(context) is True
    memory.close()
