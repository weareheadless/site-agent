from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable


class AdapterError(Exception):
    pass


class SiteAdapter(ABC):
    """A publish target. Reads site content, commits changes, reports status.

    Contract (Phase 4 will build the editor on top of this):
      get_content()  -> parsed content document (dict)
      commit_file()  -> persist one file to the target, returns info dict
      status()       -> deployment/health info dict for the admin UI
      validate()     -> raise AdapterError if config is unusable
    """

    name = "base"

    def __init__(self, config: dict[str, Any] | None = None):
        self.root = config or {}
        self.site = self.root.get("site") or {}

    @abstractmethod
    def get_content(self) -> dict[str, Any]:
        ...

    @abstractmethod
    def commit_file(self, path: str, data: bytes, message: str) -> dict[str, Any]:
        ...

    def delete_file(self, path: str, message: str, branch: str | None = None) -> dict[str, Any]:
        raise AdapterError(f"{self.name}: deleting files is not supported")

    def status(self) -> dict[str, Any]:
        return {"adapter": self.name}

    def validate(self) -> None:
        return None


@runtime_checkable
class PreviewAdapter(Protocol):
    """Optional adapter capability for branch-backed Design previews."""

    def ensure_branch(self, name: str) -> dict[str, Any]:
        ...


@runtime_checkable
class MergeAdapter(Protocol):
    """Optional adapter capability for merging an approved preview."""

    def merge_preview(self, config: dict[str, Any], message: str) -> dict[str, Any]:
        ...


ADAPTERS: dict[str, type[SiteAdapter]] = {}


def register(cls: type[SiteAdapter]) -> type[SiteAdapter]:
    ADAPTERS[cls.name] = cls
    return cls


def get_adapter(name: str, config: dict[str, Any]) -> SiteAdapter:
    cls = ADAPTERS.get(name)
    if cls is None:
        raise AdapterError(f"unknown adapter '{name}' (known: {sorted(ADAPTERS)})")
    return cls(config)
