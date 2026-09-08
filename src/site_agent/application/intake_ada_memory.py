"""Application boundary for Intake Ada's permanent, sanitized memory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..core.incubation_contracts import CreativeEpisode, NoveltyContext
from ..core.intake_ada_store import IntakeAdaStore


class IntakeAdaMemoryError(ValueError):
    """A permanent-memory operation failed its sanitization contract."""


class IntakeAdaMemoryService:
    def __init__(self, store: IntakeAdaStore) -> None:
        self.store = store

    def record_episode(self, episode: CreativeEpisode) -> CreativeEpisode:
        try:
            return self.store.save_episode(episode)
        except Exception as exc:  # noqa: BLE001 - keep store details out of adapters
            raise IntakeAdaMemoryError(str(exc)[:500]) from exc

    def recall(
        self,
        query: str,
        *,
        fingerprint: Mapping[str, Sequence[str]] | None = None,
        limit: int = 8,
    ) -> list[dict]:
        try:
            return self.store.search_episodes(query, fingerprint=fingerprint, limit=limit)
        except Exception as exc:  # noqa: BLE001 - typed application boundary
            raise IntakeAdaMemoryError(str(exc)[:500]) from exc

    def reflection(self, episode_id: str, reflection: Mapping) -> str:
        try:
            return self.store.save_reflection(episode_id, reflection)
        except Exception as exc:  # noqa: BLE001 - typed application boundary
            raise IntakeAdaMemoryError(str(exc)[:500]) from exc


__all__ = ["IntakeAdaMemoryError", "IntakeAdaMemoryService"]
