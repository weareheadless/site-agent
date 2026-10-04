"""hands package — publish target adapters."""

from .base import ADAPTERS, AdapterError, SiteAdapter, get_adapter, register
from . import cloudflare_pages, github_static  # noqa: F401  (register adapters)
from . import neutral_scaffold  # noqa: F401  (register local customer adapter)
from . import payload_gateway  # noqa: F401  (Payload gateway adapter)
__all__ = ["ADAPTERS", "AdapterError", "SiteAdapter", "get_adapter", "register"]
