"""The media ceiling and the ingress that carries it must agree.

An owner upload travels through the shared API's public ingress before the
tenant bridge reads the file. The bridge declares a 25 MB ceiling, but the
checked-in api.helloada.app vhost never declared a body limit, so nginx's 1 MB
default answered every real clip with its own HTML 413 and the gallery showed
it as a connection failure. Reinstalling the reviewed vhost therefore silently
re-broke owner video uploads.

These tests tie the two numbers together so that class of failure cannot return
unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NGINX = ROOT / "deploy" / "nginx-ada-api.helloada.app.conf"
BRIDGE = ROOT / "src/site_agent/templates/next-payload/src/app/api/helloada/[...path]/route.ts"

MEGABYTE = 1024 * 1024


def media_ceiling() -> int:
    """The size the tenant bridge promises an owner's browser."""
    match = re.search(r"const maxMediaBytes = (\d+) \* 1024 \* 1024", BRIDGE.read_text())
    assert match, "the tenant bridge no longer declares its media ceiling in whole megabytes"
    return int(match.group(1)) * MEGABYTE


def ingress_limit() -> int:
    """The largest request body the checked-in API vhost accepts."""
    source = NGINX.read_text()
    assert "server_name api.helloada.app;" in source
    https = source.split("listen 443 ssl http2;", 1)[1].split("server_name api.helloada.app;", 1)[1]
    # The directive must sit on the server itself: a location-scoped limit would
    # only cover one route and silently miss the one that carries media.
    match = re.search(r"^\s{4}client_max_body_size (\d+)([km]);", https, re.MULTILINE)
    assert match, "the API ingress declares no client_max_body_size, so nginx's 1 MB default applies"
    value, unit = int(match.group(1)), match.group(2)
    return value * (MEGABYTE if unit == "m" else 1024)


def test_the_ingress_carries_at_least_the_declared_media_ceiling() -> None:
    ceiling = media_ceiling()
    assert ceiling == 25 * MEGABYTE
    limit = ingress_limit()
    # The file travels inside a multipart body with its own framing and fields.
    assert limit >= ceiling + MEGABYTE, (
        f"the API ingress accepts {limit} bytes but the bridge promises {ceiling}; "
        "a real clip is rejected before the tenant sees it"
    )
    assert limit <= 64 * MEGABYTE, "an ingress this far above the contract is untested surface"


def test_the_ingress_streams_an_upload_instead_of_buffering_it() -> None:
    source = NGINX.read_text()
    assert "proxy_request_buffering off;" in source, (
        "an upload is a body in flight; nginx buffering it to disk first delays the "
        "transfer the owner is waiting on"
    )
