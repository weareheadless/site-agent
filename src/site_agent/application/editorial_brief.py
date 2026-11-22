"""Turn a CrawlSEO action, or an owner's request, into an editorial brief.

The brief is the whole contract with the writing service. Two things matter
here and nothing else does:

- **Why** the piece exists is already decided. CrawlSEO measured the demand and
  wrote down the reason; that reason is the brief's topic and angle. It is never
  re-measured. Measuring the same demand twice costs the same money to learn the
  same thing.
- **What** is true about the subject is *not* decided. Nobody has read it. So the
  brief carries no source URLs for a news or trend piece, and the service
  researches the subject itself, then verifies every quote against the text it
  actually read.

A brief that named evidence pages would be a different, equally valid case: an
article about the site's own craft, where the site's own crawled pages are the
evidence. `_evidence_urls` decides which case this is, from the action alone.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# A page the site already publishes is evidence about the site's own work. A
# targetless article is a claim about the world, and its evidence must be read
# from the world.
OWN_CONTENT_CAPABILITIES = frozenset({"content.prepare"})


def _text(value: Any, limit: int = 2000) -> str:
    return " ".join(str(value or "").split())[:limit]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def evidence_urls(remote: Mapping[str, Any]) -> list[str]:
    """Pages CrawlSEO's crawl already read, when the article is about them.

    Only for an article that explains the site's own published work: the target
    page and its sibling pages are the source the piece quotes. A news or trend
    article has no such pages, and must not be given the site's homepage as
    evidence — that is how an article about an awards show ends up citing the
    business it was written for.
    """
    target = _mapping(remote.get("target"))
    target_url = _text(target.get("canonicalUrl"))
    required = remote.get("requiredCapabilities")
    required = required if isinstance(required, list) else []
    if not target_url or not OWN_CONTENT_CAPABILITIES.intersection(
        str(item) for item in required
    ):
        return []
    urls: list[str] = []
    for row in remote.get("evidence") or []:
        if not isinstance(row, Mapping):
            continue
        url = _text(row.get("url"))
        if url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    if target_url not in urls:
        urls.insert(0, target_url)
    return urls[:6]


def build_brief(
    *,
    tenant: str,
    remote: Mapping[str, Any],
    business: Mapping[str, Any] | None = None,
    locales: list[str] | None = None,
    default_locale: str = "",
    voice: str = "default",
    must_link: list[str] | None = None,
) -> dict[str, Any]:
    """One brief, from what the destination already knows.

    Nothing here invents a subject. The title and the recommendation are the
    owner-visible statement of what the piece is for; the angle adds why now.
    When CrawlSEO has both, the writer gets both.
    """
    business = business or {}
    title = _text(remote.get("problem") or remote.get("title") or remote.get("recommendation"), 300)
    recommendation = _text(remote.get("recommendation") or remote.get("expectedOutcome"))
    if not title:
        title = _text(remote.get("primaryQuery") or remote.get("title"), 300)
    if not title:
        raise ValueError("This action has no title or recommendation to write from")

    locales = [str(item).strip().lower() for item in (locales or ["en"]) if str(item).strip()]
    if not locales:
        locales = ["en"]
    ordered = list(locales)
    if default_locale and str(default_locale).strip().lower() in ordered:
        primary = str(default_locale).strip().lower()
        ordered = [primary] + [item for item in ordered if item != primary]
    else:
        primary = ordered[0]

    keyword = _text(remote.get("primaryQuery") or remote.get("keyword"), 200)
    angle = " ".join(
        part
        for part in (
            recommendation,
            _text(remote.get("expectedOutcome"), 600),
        )
        if part
    )
    urls = evidence_urls(remote)

    evidence: dict[str, Any] = {"min_sources": 2 if urls else 3}
    if urls:
        evidence["source_urls"] = urls

    brief: dict[str, Any] = {
        "tenant": tenant,
        "destination": {"adapter": "filesystem", "site_id": tenant},
        "mode": "brief",
        "format": "article",
        "locales": ordered,
        "topic": {
            "question": title,
            "angle": angle[:2000],
            "primary_keyword": keyword,
            "cluster": _text(remote.get("cluster") or remote.get("category"), 120),
        },
        "business": {
            "name": _text(business.get("name"), 200),
            "domain": _text(business.get("domain"), 200),
            "audience": _text(business.get("audience"), 500),
            "topics": [str(item)[:120] for item in business.get("topics") or [] if str(item).strip()][:8],
            "services": [str(item)[:120] for item in business.get("services") or [] if str(item).strip()][:8],
            "location": _text(business.get("location"), 200),
            "locale": primary,
        },
        "requirements": {
            "action": _text(remote.get("recommendation") or remote.get("problem")),
            "why_now": _text(remote.get("whyNow") or remote.get("expectedOutcome")),
            "must_link": [str(item) for item in must_link or [] if str(item).startswith("/")][:20],
        },
        "evidence": evidence,
        "voice": voice,
        "target": {"mode": "new"},
        "policy": {
            # Site-agent owns the write and the owner owns the approval. A
            # service that also published would be a second author of the
            # tenant's database, and nobody would know which one landed.
            "approval": "none",
            "publish": False,
            "min_words": 500,
            "max_words": 1800,
            "fact_check_rounds": 2,
            "on_unverified": "hold",
            "deadline_seconds": 900,
        },
        "metadata": {
            "crawlseoActionId": _text(remote.get("id"), 120),
            "crawlseoRevision": remote.get("revision"),
            "research": "own-pages" if urls else "subject",
        },
    }
    action = _text(remote.get("id"), 120) or title[:60]
    revision = remote.get("revision")
    brief["idempotency_key"] = f"crawlseo:action:{action}:rev:{revision}"
    return brief
