"""template_tokens.py — the main page's design contract, extracted as numbers.

The generic design skills say *"double the whitespace"*; this says *"the main
page's sections sit 120px apart, its body is 15px/1.6, its container is
min(1240px, calc(100% - 48px)), its footer pads 54px top."* A new page is told
to match these exact measured values so consistency with the already-validated
homepage is automatic instead of aspirational.

Deterministic and stdlib-only (same shape as site_digest / tweakmap), cached in
the memory DB keyed on the origin/main commit so it regenerates only when the
published site changes. The "main page" is index.html and the first stylesheet
that isn't an admin/utility sheet.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

CACHE_KEY = "template_tokens_v1"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
# a declaration ends with ';' OR is the last one before the closing '}' of the
# block body (which is passed in without the '}'), so allow an end-of-string match.
_CSS_DECL_RE = re.compile(r"([\w-]+)\s*:\s*([^;}]+?)(?:;|$)", re.S)
_VAR_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;}]+?)(?:;|$)")
_MEDIA_RE = re.compile(r"@media\b")


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


def _css_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """[(selector, {prop: value})] for base (non-media) rules, order preserved."""
    rules: list[tuple[str, dict[str, str]]] = []
    for m in _CSS_RULE_RE.finditer(css or ""):
        sel = re.sub(r"\s+", " ", m.group(1)).strip()
        body = m.group(2)
        if not sel or "{" in sel or not body:
            continue
        decls: dict[str, str] = {}
        for dm in _CSS_DECL_RE.finditer(body):
            prop, val = dm.group(1).strip().lower(), dm.group(2).strip()
            if prop not in decls:
                decls[prop] = val
        rules.append((sel, decls))
    return rules


def _first_value(rules: list[tuple[str, dict[str, str]]], sel_like: str,
                 prop: str) -> str:
    """First non-empty value of `prop` across rules whose selector contains
    sel_like, in document order. Returns '' if none."""
    low = sel_like.lower()
    for sel, decls in rules:
        if low in sel.lower():
            val = decls.get(prop)
            if val:
                return val
    return ""


def _raw_declaration(css: str, selector: str, prop: str) -> str:
    """Read one declaration from a concrete selector in compressed CSS.

    The homepage stylesheet is intentionally compact and contains several
    adjacent rules. The generic rule parser is useful for broad measurements,
    but layout safety needs an exact selector lookup.
    """
    match = re.search(r"(?:^|})\s*" + re.escape(selector) + r"\s*\{([^{}]*)\}", css or "")
    if not match:
        return ""
    declaration = re.search(r"(?:^|;)\s*" + re.escape(prop) + r"\s*:\s*([^;}]+)", match.group(1))
    return declaration.group(1).strip() if declaration else ""


_SECTION_WORDS = ("section", "hero", "manifesto", "closing", "course", "footer")


def _px(value: str) -> float:
    """Numeric value of a length, for comparison. ''/0 for non-lengths."""
    m = re.search(r"(\d+(?:\.\d+)?)(?:px|em|rem)?", value or "")
    return float(m.group(1)) if m else 0.0


def _vertical(pad: str) -> str:
    """The vertical component of a padding shorthand (top), or '' if none."""
    parts = [p for p in (pad or "").split() if p and not p.startswith("var(")]
    if len(parts) >= 2:
        return parts[0]
    if len(parts) == 1:
        return parts[0]
    return ""


def _largest_section_padding(rules: list[tuple[str, dict[str, str]]]) -> str:
    """The dominant vertical section rhythm: the largest section-like block's
    vertical padding in the file (excluding :root and media blocks already
    stripped)."""
    best, best_sel = "", ""
    for sel, decls in rules:
        if ":root" in sel or sel == "*":
            continue
        pad = decls.get("padding") or decls.get("padding-top") or decls.get("padding-bottom") or ""
        if not pad:
            continue
        vert = _vertical(pad)
        if not vert:
            continue
        low = sel.lower()
        is_section = any(w in low for w in _SECTION_WORDS)
        if not best:
            best, best_sel = vert, low
        elif is_section and not any(w in best_sel for w in _SECTION_WORDS):
            best, best_sel = vert, low
        elif is_section and _px(vert) > _px(best):
            best, best_sel = vert, low
    return best


def build(clone: Path, ref: str = "origin/main") -> str:
    """The main page's design contract as plain text, straight out of the git
    ref. Empty string when the repo has no readable main page."""
    files = [f for f in _git(clone, "ls-tree", "-r", "--name-only", ref).splitlines() if f.strip()]
    if not files:
        return ""
    htmls = sorted([f for f in files if f.lower().endswith((".html", ".htm"))],
                   key=lambda p: (p.lower() != "index.html", p))
    if not htmls:
        return ""
    main = htmls[0]

    sheets = sorted([f for f in files if f.lower().endswith(".css")],
                    key=lambda p: (p.lower() != "styles.css", p))
    sheet = ""
    for s in sheets:
        if s.rsplit("/", 1)[-1].startswith("admin"):
            continue
        sheet = s
        break
    css = _show(clone, ref, sheet) if sheet else ""
    rules = _css_rules(css) if css else []
    if not rules:
        return ""

    m = _TITLE_RE.search(_show(clone, ref, main))
    brand = _text(m.group(1))[:60] if m else main

    # :root variables are the identity backbone — surface them first. Only read
    # them from the actual :root block so a stray `--x` inside other rules (or a
    # trailing `}` bleeding into the value) can't pollute the list.
    root_block = ""
    for sel, decls in _css_rules(css):
        if sel == ":root":
            # rebuild a clean block string from parsed declarations
            root_block = ";".join(f"{k}:{v}" for k, v in decls.items())
            break
    vars_ = list(dict.fromkeys((v.strip(), val.strip())
                               for v, val in _VAR_RE.findall(root_block)))[:10]
    lines = [f"Main page template ({brand or main}) — match these exact values on every new page:"]
    if vars_:
        lines.append("design variables: " + ", ".join(f"{v} {val}" for v, val in vars_))

    page_margin = _first_value(rules, "body", "margin") or "0"
    lines.append(f"page margin (body): {page_margin}")

    # container width: a true .container/.main/.wrapper width if present, else
    # the header's constrained width as the best proxy for the page's gutters.
    width = _first_value(rules, "container", "width") or _first_value(rules, "main", "width")
    if not width:
        width = _first_value(rules, "wrapper", "width")
    if not width:
        width = _first_value(rules, "header", "width")
        if width:
            width = width + " (header gutter proxy)"
    lines.append(f"container width: {width or '(not fixed — grid/flow layout)'}")

    section_spacing = _largest_section_padding(rules)
    if section_spacing:
        lines.append(f"section vertical spacing: {section_spacing} (largest section padding)")
    footer_pad = _first_value(rules, "footer", "padding")
    lines.append(f"footer padding: {footer_pad or '(not set explicitly)'}")

    header_position = _raw_declaration(css, ".site-header", "position")
    header_top = _raw_declaration(css, ".site-header", "top")
    header_padding = _raw_declaration(css, ".site-header", "padding")
    header_z = _raw_declaration(css, ".site-header", "z-index")
    if header_position:
        lines.append(
            "primary header layout: .site-header "
            f"position {header_position}, top {header_top or '0'}, "
            f"padding {header_padding or '(not set)'}, z-index {header_z or '(not set)'}"
        )
        if header_position in {"fixed", "sticky", "absolute"}:
            top_px = _px(header_top)
            pad_parts = [p for p in (header_padding or "").split() if p]
            pad_px = _px(pad_parts[0]) if pad_parts else 0
            safe_offset = max(64, int(top_px + (pad_px * 2) + 24))
            lines.append(
                f"fixed-header content safety: every new page's first content block must start at least {safe_offset}px from the viewport top"
            )

    radius = _first_value(rules, "border-radius", "") or _first_value(rules, "", "border-radius")
    lines.append(f"border radius: {radius or '(none)'}")

    border = _first_value(rules, "", "border")
    lines.append(f"border style: {border or '(none)'}")

    body_font = _first_value(rules, "body", "font-size")
    body_lh = _first_value(rules, "body", "line-height")
    lines.append(f"body type: {body_font or '?'} / {body_lh or '?'}")

    shadow = _first_value(rules, "", "box-shadow")
    if shadow == "none!important" or shadow == "none":
        shadow = "none on sampled rules"
    lines.append(f"shadow: {shadow or '(none)'}")

    media = len(_MEDIA_RE.findall(css))
    lines.append(f"responsive breakpoints (media queries): {media}")

    return "\n".join(lines)[:1600]


def cached(clone: Path, memory: Any = None) -> str:
    """Build the template contract, reusing the cached copy while origin/main
    hasn't moved."""
    head = _git(clone, "rev-parse", "origin/main").strip()
    if memory is not None and head:
        try:
            previous = memory.kv_get(CACHE_KEY)
        except Exception:  # noqa: BLE001
            previous = None
        if isinstance(previous, dict) and previous.get("main_head") == head and previous.get("tokens"):
            return previous["tokens"]
    text = build(clone)
    if memory is not None and head:
        try:
            memory.kv_set(CACHE_KEY, {"main_head": head, "tokens": text})
        except Exception:  # noqa: BLE001
            pass
    return text
