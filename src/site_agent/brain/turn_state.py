"""Per-turn agent state that survives a restart.

The chat tool loop keeps a handful of keys on its working context: the
validated change plan, the dispatch evidence that freezes that plan, the
Payload receipts, and the documents it already read. Those lived only in a
Python dict inside one request, so a restart mid-turn lost the plan and a
retry could start a second build.

This mapping keeps the same keys, but writes the durable ones through to the
chat job as they change. Everything else (config, memory, the Payload client)
stays a plain context value and is never persisted.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

# Keys the tool loop mutates during a turn. Only these are persisted; the rest
# of the context is the tenant runtime and must never be written to the job.
# The document read cache is deliberately excluded: it is keyed by tuples and
# losing it only costs one more read.
PERSISTED = frozenset({
    "_website_change_plan",
    "_website_change_plan_dispatched",
    "_website_change_source_build_dispatched",
    "_completed_payload_effects",
    "_payload_read_globals",
    "_resolved_payload_locale",
    "_last_action_succeeded",
    "_last_changed",
    "_last_merge_draft_id",
    "_last_preview",
    "_last_change",
    "_source_build_completed",
})


def _key(job_id: Any) -> str:
    return f"chat_turn:{job_id}"


class TurnState(dict):
    """A context mapping whose durable keys are stored against the chat job."""

    def __init__(self, memory: Any, job_id: Any, base: Mapping[str, Any] | None = None) -> None:
        super().__init__(dict(base or {}))
        self._memory = memory
        self._job_id = job_id
        saved = self._load()
        for name, value in saved.items():
            if name in PERSISTED:
                dict.__setitem__(self, name, value)

    # -- persistence -----------------------------------------------------
    def _load(self) -> dict[str, Any]:
        if self._memory is None or self._job_id in (None, ""):
            return {}
        stored = self._memory.kv_get(_key(self._job_id), {})
        return dict(stored) if isinstance(stored, Mapping) else {}

    def _flush(self) -> None:
        if self._memory is None or self._job_id in (None, ""):
            return
        self._memory.kv_set(
            _key(self._job_id),
            {name: dict.__getitem__(self, name) for name in PERSISTED if dict.__contains__(self, name)},
        )

    # -- mapping behaviour ----------------------------------------------
    def __setitem__(self, key: str, value: Any) -> None:
        existed = dict.__contains__(self, key)
        previous = dict.get(self, key)
        dict.__setitem__(self, key, value)
        if key in PERSISTED and (not existed or previous != value):
            self._flush()

    def __delitem__(self, key: str) -> None:
        dict.__delitem__(self, key)
        if key in PERSISTED:
            self._flush()

    def pop(self, key: str, *args: Any) -> Any:
        existed = dict.__contains__(self, key)
        value = dict.pop(self, key, *args)
        if existed and key in PERSISTED:
            self._flush()
        return value

    def setdefault(self, key: str, default: Any = None) -> Any:
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        self[key] = default
        return dict.__getitem__(self, key)

    def update(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        changed = False
        for source in (*args, kwargs):
            items = source.items() if isinstance(source, Mapping) else source
            for key, value in items:
                existed = dict.__contains__(self, key)
                previous = dict.get(self, key)
                dict.__setitem__(self, key, value)
                changed = changed or (key in PERSISTED and (not existed or previous != value))
        if changed:
            self._flush()

    def clear(self) -> None:
        persisted = [name for name in PERSISTED if dict.__contains__(self, name)]
        dict.clear(self)
        if persisted:
            self._flush()


def clear_turn(memory: Any, job_id: Any) -> None:
    """Drop a finished turn's durable state."""
    if memory is None or job_id in (None, ""):
        return
    memory.kv_set(_key(job_id), {})
