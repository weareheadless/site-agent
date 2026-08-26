"""hands package — publish target adapters."""

from .base import ADAPTERS, AdapterError, SiteAdapter, get_adapter, register
from . import cloudflare_pages, github_static  # noqa: F401  (register adapters)
from . import pelican_blog  # noqa: F401  (blog content helpers)

__all__ = ["ADAPTERS", "AdapterError", "SiteAdapter", "get_adapter", "register"]
