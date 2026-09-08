"""site_digest.py — cheap structural digest of the site for the builder agent.

The builder's opencode agent re-reads whole files every run. A compact digest
of the site's shape (pages, nav, sections, headings, CSS fonts/variables/classes)
lets it know where to look and what conventions exist without a cold full read.

Deterministic and stdlib-only; no LLM tokens. Cached in the memory DB keyed on
the origin/main commit so it regenerates only when the published site actually
changes.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

CACHE_KEY = "site_digest_v2"
_MAX_PAGES = 8
_MAX_HEADINGS = 12
_MAX_VARS = 40
_MAX_CLASSES = 50

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_HEADING_RE = re.compile(r"<h([1-4])\b[^>]*>(.*?)</h\1>", re.I | re.S)
_LINK_RE = re.compile(r"<a\b[^>]*\bhref=\"([^\"]+)\"[^>]*>(.*?)</a>", re.I | re.S)
_ID_CLASS_RE = re.compile(r'\b(?:id|class)="([^"]+)"', re.I)
_ASSET_RE = re.compile(r"<(?:script|link)\b[^>]*\b(?:src|href)=\"([^\"]+)\"", re.I)
_VAR_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
_FONT_RE = re.compile(r"font-family:\s*([^;]+);", re.I)
_FONT_FACE_RE = re.compile(r"@font-face", re.I)
_MEDIA_RE = re.compile(r"@media\b")
_LAYOUT_WORDS = (
    "header", "nav", "footer", "hero", "section", "grid", "card", "container",
    "wrapper", "btn", "button", "banner", "gallery", "menu", "cta", "logo",
)


def _git(clone: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(clone), *args], capture_output=True, text=True, timeout=30
    )
    return proc.stdout


def _show(clone: Path, ref: str, path: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(clone), "show", f"{ref}:{path}"],
        capture_output=True, text=True, timeout=30,
    )
    return proc.stdout if proc.returncode == 0 else ""


def _text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _nav_links(html: str) -> list[tuple[str, str]]:
    links = []
    for m in _LINK_RE.finditer(html or ""):
        href, label = m.group(1), _text(m.group(2))
        if not href or href.startswith(("mailto:", "tel:", "#")) or not label:
            continue
        links.append((href, label))
        if len(links) >= 10:
            break
    return links


def _regions(html: str) -> list[str]:
    seen: list[str] = []
    for m in _ID_CLASS_RE.finditer(html or ""):
        for token in m.group(1).split():
            if token and token not in seen:
                seen.append(token)
                if len(seen) >= 24:
                    return seen
    return seen


def _describe_page(clone: Path, ref: str, page: str) -> str:
    html = _show(clone, ref, page)
    if not html:
        return ""
    label = " (homepage)" if page.lower() == "index.html" else ""
    lines = [f"\n{page}{label}:"]
    title = _TITLE_RE.search(html)
    if title:
        lines.append(f"  title: {_text(title.group(1))[:80]}")
    links = _nav_links(html)
    if links:
        lines.append("  nav: " + ", ".join(f"{label} ({href})" for href, label in links[:8]))
    regions = _regions(html)
    if regions:
        lines.append("  ids/classes: " + ", ".join(regions[:18]))
    heads = _HEADING_RE.findall(html)
    if heads:
        lines.append(
            "  headings: " + "; ".join(f"h{level} {_text(t)[:60]}" for level, t in heads[:_MAX_HEADINGS])
        )
    assets = list(dict.fromkeys(_ASSET_RE.findall(html)))
    if assets:
        lines.append("  assets: " + ", ".join(assets[:6]))
    return "\n".join(lines)


def _describe_css(clone: Path, ref: str, sheet: str) -> str:
    css = _show(clone, ref, sheet)
    if not css:
        return ""
    lines = [f"\n{sheet}:"]
    fonts = list(dict.fromkeys(f.strip().rstrip(",") for f in _FONT_RE.findall(css)))[:6]
    if fonts:
        lines.append("  fonts: " + ", ".join(fonts))
    faces = len(_FONT_FACE_RE.findall(css))
    if faces:
        lines.append(f"  @font-face blocks: {faces}")
    media = len(_MEDIA_RE.findall(css))
    if media:
        lines.append(f"  media queries: {media}")
    variables = list(dict.fromkeys((v.strip(), val.strip()) for v, val in _VAR_RE.findall(css)))[:_MAX_VARS]
    if variables:
        lines.append("  css variables: " + ", ".join(f"{v} {val}" for v, val in variables))
    classes = list(dict.fromkeys(re.findall(r"\.([\w-]+)", css)))
    layout = [c for c in classes if any(w in c for w in _LAYOUT_WORDS)][:20]
    other = [c for c in classes if c not in layout][:_MAX_CLASSES - len(layout)]
    if layout or other:
        lines.append("  classes: " + ", ".join(layout + other))
    return "\n".join(lines)


def build(clone: Path, ref: str = "origin/main") -> str:
    """Structural summary of the site as stored at the given git ref."""
    files = [f for f in _git(clone, "ls-tree", "-r", "--name-only", ref).splitlines() if f.strip()]
    if not files:
        return ""
    html = sorted(
        [f for f in files if f.lower().endswith((".html", ".htm"))],
        key=lambda p: (p.lower() != "index.html", p),
    )
    css = sorted(
        [f for f in files if f.lower().endswith(".css")],
        key=lambda p: (p.lower() != "styles.css", p),
    )
    lines = [
        f"Files ({len(files)}): {len(html)} pages, {len(css)} stylesheets, "
        f"content.json: {'yes' if 'content.json' in files else 'no'}"
    ]
    for page in html[:_MAX_PAGES]:
        block = _describe_page(clone, ref, page)
        if block:
            lines.append(block)
    for sheet in css[:2]:
        block = _describe_css(clone, ref, sheet)
        if block:
            lines.append(block)
    return "\n".join(lines)[:2800]


def cached(clone: Path, memory: Any = None, ref: str = "origin/main") -> str:
    """Build the digest, caching against the exact source ref and commit."""
    head = _git(clone, "rev-parse", ref).strip()
    if memory is not None and head:
        try:
            previous = memory.kv_get(CACHE_KEY)
        except Exception:  # noqa: BLE001
            previous = None
        if (isinstance(previous, dict) and previous.get("ref") == ref
                and previous.get("head") == head and previous.get("digest")):
            return previous["digest"]
    text = build(clone, ref=ref)
    if memory is not None and head:
        try:
            memory.kv_set(CACHE_KEY, {"ref": ref, "head": head, "digest": text})
        except Exception:  # noqa: BLE001
            pass
    return text
