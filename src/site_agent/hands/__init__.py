"""hands package — publish target adapters."""

from .base import ADAPTERS, AdapterError, SiteAdapter, get_adapter, register
from . import cloudflare_pages, github_static  # noqa: F401  (register adapters)
from . import neutral_scaffold  # noqa: F401  (register local customer adapter)
from . import atelier_payload  # noqa: F401  (Payload-backed Atelier adapter)
from . import pelican_blog  # noqa: F401  (blog content helpers)

__all__ = ["ADAPTERS", "AdapterError", "SiteAdapter", "get_adapter", "register"]
