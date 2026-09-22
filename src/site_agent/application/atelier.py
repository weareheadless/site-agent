"""Backward-compatible imports for the original Atelier bridge name.

The shared implementation lives in :mod:`site_agent.application.workspace`.
This shim can be removed after downstream integrations stop importing the
customer-specific module path.
"""

from .workspace import (  # noqa: F401
    AtelierBridgeError,
    AtelierChatService,
    AtelierDesignBuildHandoff,
    AtelierJourney,
    AtelierSourceConflict,
    AtelierTenant,
    AtelierTenantRegistry,
    BridgeError,
    ChatService,
    DesignBuildHandoff,
    Journey,
    SourceConflict,
    Tenant,
    TenantRegistry,
    _journey_for_config,
)
