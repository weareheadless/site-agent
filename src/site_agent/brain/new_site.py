"""The first-page brief for a website that is still the published scaffold.

A new site is provisioned from the canonical template, so it is live before it
has a design: the home route renders framed empty sections and nothing else.
This module recognises that exact state and supplies Ada with the only thing
she is missing on such a site — the instruction to establish the brief with the
owner and then author the first page. It adds no mechanism, store or flag: the
state is the committed source of the tenant's own home route.
"""

from __future__ import annotations

from pathlib import Path

HOME_ROUTE = Path("src/app/(frontend)/page.tsx")
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates" / "next-payload"

NEW_SITE_BRIEF = """# A new website, before its first design

This website was just provisioned and still publishes the scaffold home page:
framed empty sections, no copy, no design. Nothing on this site has been
designed by anyone yet, and the owner is waiting for their first page.

Establish the brief with the owner before you author anything: what the
business really is and what the website has to do for it, who it is speaking
to, the voice and words they already use, the colours and references they have
in mind, and which images you may use - ask them to attach photographs when the
page depends on real imagery rather than described it. Ask only what you do not
already know from this conversation, in the owner's own language and register,
and do not present a menu of stock directions.

Then author the first page here: replace the scaffold with one page of a few
sections, write its copy from that brief and that voice, place the images they
gave you, and give the page a design that belongs to this business - its
typography, framing, spacing and placement, not a default layout. Add one
restrained motion that comes from the subject. Everything else - further pages,
products, publishing, measurement - waits until the owner has seen this page.

The owner reviews the result as a preview and approves it; nothing is published
by this turn. Once the scaffold home page is replaced, this instruction no
longer applies.
"""


def _read_canonical_route(root: Path) -> str:
    try:
        return (root / HOME_ROUTE).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def homepage_is_scaffold(root: str | Path) -> bool:
    """True when the tenant still serves the untouched template home page."""
    canonical = _read_canonical_route(TEMPLATE_ROOT)
    current = _read_canonical_route(Path(root))
    return bool(canonical) and current == canonical


def new_site_brief() -> str:
    return NEW_SITE_BRIEF


__all__ = ["NEW_SITE_BRIEF", "homepage_is_scaffold", "new_site_brief"]
