"""Backward-compatible imports for the original Atelier route module.

The shared implementation lives in :mod:`site_agent.web.workspace`.
"""

from .workspace import (  # noqa: F401
    create_atelier_api_app,
    create_workspace_api_app,
    register_atelier_routes,
    register_workspace_routes,
)
