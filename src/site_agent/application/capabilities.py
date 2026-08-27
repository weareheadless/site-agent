"""Explicit registry for the small set of capabilities a runtime exposes."""

from __future__ import annotations

from collections.abc import Iterable

from ..core.contracts import Capability, CapabilityAvailability, EffectClass


class CapabilityRegistryError(ValueError):
    pass


class CapabilityRegistry:
    """A composition-time registry, not a dynamic plugin or tool loader."""

    def __init__(self, capabilities: Iterable[Capability] = ()) -> None:
        self._capabilities: dict[str, Capability] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: Capability) -> Capability:
        existing = self._capabilities.get(capability.capability_id)
        if existing is not None:
            raise CapabilityRegistryError(f"capability already registered: {capability.capability_id}")
        self._capabilities[capability.capability_id] = capability
        return capability

    def get(self, capability_id: str) -> Capability | None:
        return self._capabilities.get(capability_id)

    def require(self, capability_id: str) -> Capability:
        capability = self.get(capability_id)
        if capability is None:
            raise CapabilityRegistryError(f"unknown capability: {capability_id}")
        return capability

    def validate(
        self,
        capability_id: str,
        *,
        provider_id: str | None = None,
        effect_class: EffectClass | str | None = None,
    ) -> Capability:
        capability = self.require(capability_id)
        if provider_id is not None and capability.provider_id != provider_id:
            raise CapabilityRegistryError(f"capability {capability_id} belongs to another provider")
        if effect_class is not None:
            try:
                requested_effect = EffectClass(effect_class)
            except (TypeError, ValueError) as exc:
                raise CapabilityRegistryError("unknown effect class") from exc
            if capability.effect_class != requested_effect:
                raise CapabilityRegistryError(f"capability {capability_id} has a different effect class")
        return capability

    def available(self, capability_id: str) -> bool:
        return self.require(capability_id).availability != CapabilityAvailability.UNAVAILABLE

    def values(self) -> tuple[Capability, ...]:
        return tuple(self._capabilities[key] for key in sorted(self._capabilities))


def default_capabilities() -> tuple[Capability, ...]:
    """Capabilities known by the built-in runtime composition."""
    return (
        Capability(
            capability_id="content.suggestion",
            provider_id="site-agent",
            effect_class=EffectClass.PROPOSAL,
            availability=CapabilityAvailability.AVAILABLE,
        ),
        Capability(
            capability_id="content.article.prepare",
            provider_id="site-agent",
            effect_class=EffectClass.PROPOSAL,
            availability=CapabilityAvailability.AVAILABLE,
        ),
        Capability(
            capability_id="review.site_change",
            provider_id="site-agent",
            effect_class=EffectClass.SITE_MUTATION,
            availability=CapabilityAvailability.AVAILABLE,
            approval_required=True,
        ),
        Capability(
            capability_id="social.post.publish",
            provider_id="social",
            effect_class=EffectClass.EXTERNAL_MUTATION,
            availability=CapabilityAvailability.UNAVAILABLE,
            approval_required=True,
        ),
    )


__all__ = ["CapabilityRegistry", "CapabilityRegistryError", "default_capabilities"]
