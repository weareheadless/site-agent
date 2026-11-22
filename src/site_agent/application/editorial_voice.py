"""A tenant's voice, derived from the tenant, once, for every tenant.

An editorial brief used to carry six empty business fields and `voice: "default"`,
so the writer was told it was writing for *a site* and never which one. The
article that reached an owner as a result read like a trade journal about a
private hair and makeup studio: it never named her, recommended clinic treatments
she does not perform, and arrived in eleven identical "Step N" sections.

The fix is not a per-tenant voice file. A voice file must be authored, so it
becomes an onboarding step and a tenant config key, and the eleven tenants that
never got one all fell back to the same generic sentence. The voice already
exists: the owner wrote it, on their own site, and it is the best description of
how the business writes that anyone will produce. So this reads it.

Three sources, in that order, and the order matters:

1. Accepted customer context. The owner told the platform directly, in an
   interview, what the business is and who it serves. Nothing beats that.
2. The site's own published words. Plainly authored prose, already live, and the
   only source that exists for every tenant that has a website at all.
3. Nothing. Recorded as `none` rather than papered over: a writer that cannot
   tell "no house style" from "a house style it has not been told" invents a
   personality and repeats it with confidence.

Deriving a voice must never fail an article. A site that cannot be read degrades
to `none`, which is an honest instruction, not an outage.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from ..hands.web_read import Page, WebReadError, fetch_page

# One homepage plus at most two service pages. Voice is a register, not a corpus:
# three pages carry it, and a longer crawl costs time on every article to say
# the same thing.
MAX_PAGES = 3
# The sample is handed to the writer inside its prompt. Enough to establish a
# register, short enough not to displace the evidence.
MAX_SAMPLE_CHARS = 2400
# Real copy, not chrome. A service page on a small studio site can be three
# sentences: the bar rejects a redirect shell or a nav-only stub, not brevity.
MIN_PAGE_CHARS = 120
# A site with no published page still renders — a scaffold saying "No home page
# has been published for this site yet". Handing that to the writer as a voice
# sample teaches it to imitate a placeholder, which is worse than admitting the
# voice is unknown.
SCAFFOLD_MARKERS = (
    "no home page has been published",
    "this site is not published",
    "coming soon",
    "under construction",
    "próximamente",
    "sitio en construcción",
)
# Below this, the page cannot be describing a business; it is a placeholder or a
# redirect shell that renders a title.
SCAFFOLD_FLOOR = 120

# Paths that are never the site's own voice: utilities, legal boilerplate, feeds.
_SKIP_PATH_PARTS = (
    "blog", "news", "politica", "privacy", "privacidad", "legal", "terms",
    "cookies", "login", "admin", "cart", "carrito", "checkout", "search",
    "buscar", "feed", "rss", "sitemap", "robots", "404", "tag", "category",
    "categoria", "author", "autor", "page", "wp-",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any, limit: int = 2000) -> str:
    return " ".join(str(value or "").split())[:limit]


def _origin(url: str) -> str:
    parts = urlsplit(str(url or "").strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def _same_origin(candidate: str, origin: str) -> bool:
    return bool(origin) and _origin(candidate) == origin


def _absolute(href: str, base: str) -> str:
    """Resolve a link against the page it appeared on.

    A real site links its own sections relatively ("/novias/"), so comparing an
    unresolved href with the origin rejects every internal page a business
    offers — and the services list comes back empty while the site plainly
    names them.
    """
    from urllib.parse import urljoin

    href = str(href or "").strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return ""
    return urljoin(base, href)


def _path_of(url: str) -> str:
    return (urlsplit(url).path or "/").rstrip("/") or "/"


def _is_content_path(url: str, origin: str) -> bool:
    """A page that says something about the business, not a utility."""
    if not _same_origin(url, origin):
        return False
    path = _path_of(url)
    if path == "/":
        return False
    lowered = path.lower()
    if any(part in lowered for part in _SKIP_PATH_PARTS):
        return False
    # Deep paths are usually articles; the business describes itself near the root.
    return len([part for part in lowered.split("/") if part]) <= 2


def _service_label(text: str, url: str) -> str:
    """What the site calls this part of its work, from its own navigation."""
    label = _text(text, 60)
    if label and len(label.split()) <= 6:
        return label
    last = _path_of(url).rsplit("/", 1)[-1]
    return _text(last.replace("-", " "), 60)


def _join_sample(pages: list[str]) -> str:
    """The site's own sentences, unedited, up to the budget."""
    joined = "\n\n".join(_clean_lines(page) for page in pages if page.strip())
    if len(joined) <= MAX_SAMPLE_CHARS:
        return joined
    # Cut on a paragraph boundary so the sample ends on a whole sentence rather
    # than mid-word: the point is the rhythm, which a truncated clause destroys.
    trimmed = joined[:MAX_SAMPLE_CHARS]
    for separator in ("\n\n", ". ", "\n"):
        index = trimmed.rfind(separator)
        if index > MAX_SAMPLE_CHARS // 2:
            return trimmed[: index + len(separator)].strip()
    return trimmed.strip()


# Lines that are the site's furniture rather than its writing. A sample that
# opens "Ir al contenido Inicio Menú" teaches the model to write navigation.
_CHROME = frozenset(
    {
        "ir al contenido", "menú", "menu", "cerrar", "close", "search", "buscar",
        "inicio", "home", "en", "es", "compartir", "share", "siguiente", "anterior",
        "next", "previous", "volver", "back", "leer más", "read more",
    }
)
# Arrow and control glyphs a site uses to decorate its own navigation.
_CHROME_GLYPHS = ("↗", "↓", "←", "→", "＋", "✕", "×", "☰")


def _is_chrome(line: str) -> bool:
    text = " ".join(line.split())
    if not text:
        return True
    if any(glyph in text for glyph in _CHROME_GLYPHS):
        return True
    stripped = text.strip(" .·|/-–—").lower()
    if stripped in _CHROME:
        return True
    # A bare language switch or a two-letter token is never prose.
    return len(stripped) <= 2


# Words that appear in a site's navigation. Used only to recognise a line that
# is *entirely* navigation: trimming them out of real sentences deleted "Color"
# from "Color, balayage y corte en Playa del Carmen", which is the site writing
# about itself.
_NAV_WORDS = frozenset(
    {
        "inicio", "home", "menú", "menu", "color", "corte", "y", "maquillaje",
        "peinado", "novias", "servicios", "services", "contacto", "contact",
        "en", "es", "blog", "conóceme", "conoce", "mis", "ir", "al", "contenido",
        "quien", "soy", "precios", "prices", "reservar", "book", "galería",
    }
)


def _is_navigation(line: str) -> bool:
    """A flattened header: every word is a nav label and nothing is a sentence."""
    text = " ".join(line.split())
    if text.rstrip().endswith((".", "?", "!", ":")):
        return False
    words = [word.strip(" .,·|/-–—,↗↓←→").lower() for word in text.split()]
    words = [word for word in words if word]
    if len(words) < 3:
        return False
    return all(word in _NAV_WORDS for word in words)


def _is_scaffold(sample: str) -> bool:
    """True when the page is a placeholder rather than the business writing."""
    lowered = sample.lower()
    if any(marker in lowered for marker in SCAFFOLD_MARKERS):
        return True
    # Placeholder pages are short by nature; real copy that describes a business
    # does not fit in a sentence and a half.
    return len(sample) < SCAFFOLD_FLOOR


def _clean_lines(page: str) -> str:
    """Drop furniture and repeated lines, keeping the site's actual sentences."""
    seen: set[str] = set()
    kept: list[str] = []
    for line in page.splitlines():
        text = " ".join(line.split())
        if _is_chrome(text) or _is_navigation(text):
            continue
        # Navigation repeats on every page; it is not part of the voice.
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(text)
    return "\n".join(kept)


def _from_customer_context(business_view: Mapping[str, Any]) -> dict[str, Any]:
    """What the owner said directly, as the voice and the brief's facts."""
    business = _mapping(business_view.get("business"))
    audience = _mapping(business_view.get("audience"))
    brand = _mapping(business_view.get("brand"))

    name = _text(
        business.get("name") or business.get("businessName") or brand.get("name"), 200
    )
    audience_text = _text(
        audience.get("description") or audience.get("primary") or audience.get("who"), 500
    )
    location = _text(business.get("location") or business.get("city"), 200)
    services = _text_list(business.get("services") or business.get("offerings"), 8)
    topics = _text_list(business.get("topics") or business.get("subjects"), 8)
    identity = _text(
        brand.get("voice")
        or brand.get("tone")
        or business.get("voice")
        or business.get("tone"),
        800,
    )

    return {
        "name": name,
        "audience": audience_text,
        "location": location,
        "services": services,
        "topics": topics,
        "identity": identity,
        "voice_sample": "",
        "voice_basis": "customer_context" if (identity or services or audience_text) else "none",
    }


def _text_list(value: Any, limit: int) -> list[str]:
    if isinstance(value, str):
        items = [item for item in value.split(",")]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return []
    out: list[str] = []
    for item in items:
        text = _text(item, 120)
        if text and text not in out:
            out.append(text)
    return out[:limit]


def _from_site_copy(
    *,
    origin: str,
    name: str,
    fetch: Callable[[str], Page],
) -> dict[str, Any]:
    """The site's own published words: voice sample and the work it names.

    Only the homepage's internal links are followed, so the pages read are the
    ones the site itself offers as its description of the business. Nothing is
    fetched from another origin.
    """
    pages: list[str] = []
    services: list[str] = []
    visited: set[str] = {_path_of(origin)}
    try:
        homepage = fetch(origin)
    except (WebReadError, OSError, ValueError):
        return {}
    pages.append(homepage.text)

    # The site's own navigation is its own list of what it does. Reading it is
    # how "color-y-corte" and "novias" reach the brief as real services instead
    # of an invented subject area.
    for label, href in homepage.links:
        if len(pages) >= MAX_PAGES:
            break
        url = _absolute(href, homepage.url or origin)
        if not url or not _is_content_path(url, origin):
            continue
        if _path_of(url) in visited:
            continue
        visited.add(_path_of(url))
        try:
            page = fetch(url)
        except (WebReadError, OSError, ValueError):
            continue
        if len(page.text) < MIN_PAGE_CHARS:
            continue
        pages.append(page.text)
        service = _service_label(label, url)
        if service and service not in services:
            services.append(service)

    sample = _join_sample(pages)
    # One page of real copy is a voice; the stub bar above is for deciding
    # whether an extra page adds anything, not for discarding the homepage.
    if not sample or _is_scaffold(sample):
        return {}
    return {
        "name": name,
        "services": services[:8],
        "voice_sample": sample,
        "voice_basis": "site_copy",
    }


def derive_voice(
    *,
    customer_context: Mapping[str, Any] | None = None,
    site: Mapping[str, Any] | None = None,
    display_name: str = "",
    fetch: Callable[[str], Page] | None = None,
) -> dict[str, Any]:
    """The brief's business view: who this site is and how it writes.

    Returns the exact fields ``build_brief`` consumes, so there is one shape for
    every source. ``voice_basis`` always says which source produced it.
    """
    from_context = _from_customer_context(customer_context or {})
    name = from_context.get("name") or _text(display_name, 200)
    result: dict[str, Any] = {
        "name": name,
        "audience": from_context.get("audience", ""),
        "location": from_context.get("location", ""),
        "services": list(from_context.get("services") or []),
        "topics": list(from_context.get("topics") or []),
        "identity": from_context.get("identity", ""),
        "voice_sample": "",
        "voice_basis": from_context.get("voice_basis", "none"),
    }

    # The owner's own words were an explicit instruction about the voice: a
    # description of it from the person who owns it is better than a sample.
    if result["voice_basis"] == "customer_context" and result["identity"]:
        return result

    configured = _mapping(site)
    origin = _origin(
        str(configured.get("public_url") or configured.get("url") or configured.get("custom_domain") or "")
    )
    if not origin:
        return result

    reader = fetch or fetch_page
    try:
        site_copy = _from_site_copy(origin=origin, name=name, fetch=reader)
    except (WebReadError, OSError, ValueError):
        site_copy = {}
    if not site_copy:
        return result

    # Site copy fills gaps rather than overwriting what the owner stated, and it
    # supplies the voice itself when no description of the voice exists.
    for key in ("name", "services"):
        if not result.get(key) and site_copy.get(key):
            result[key] = site_copy[key]
    if not result.get("identity"):
        result["voice_sample"] = site_copy.get("voice_sample", "")
        result["voice_basis"] = "site_copy"
    return result
