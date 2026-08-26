"""tweakmap.py — a map of a page's editable parameters.

When the builder finishes a page she writes a semantic map of the knobs she
made tweakable; a deterministic extractor backfills every page so the fast
tier always has one. The map lets the chat model stage a small tweak (one CSS
property, a heading's text, a content field) from a compact reference instead
of re-reading whole files: each entry carries the exact current snippet, so
propose_changes can be issued blind and the existing validation still catches
staleness.

Entry kinds:
  css   {"kind":"css",   "label","file","selector","prop","current","find"}
  text  {"kind":"text",  "label","file","selector","current","find"}
  field {"kind":"field", "label","file","field","current"}

The map is cached in the memory DB keyed on the origin/main commit, so it
regenerates only when the published site changes. The builder's semantic
overlay is stored separately and merged on top (builder wins per knob).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

CACHE_KEY = "tweakmap_v3"
BUILDER_KEY = "tweakmap_builder_v1"
_MAX_PER_FILE = 24
_MAX_TOTAL = 90
_MAX_TEXT = 140
_MAX_FIELD = 80

_CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_CSS_DECL_RE = re.compile(r"([\w-]+)\s*:\s*([^;}]+);")
_TEXT_TAGS = ("h1", "h2", "h3", "h4", "p", "button", "a", "blockquote", "strong")
_TEXT_RE = re.compile(rf"<({'|'.join(_TEXT_TAGS)})\b[^>]*>(.*?)</\1>", re.I | re.S)
_PLACEHOLDER_RE = re.compile(r"^[\$\d\{\}\s\|<>:%]+$")
_LAYOUT_WORDS = (
    "hero", "footer", "header", "nav", "section", "grid", "card", "container",
    "wrapper", "btn", "button", "banner", "gallery", "menu", "cta", "logo",
)
# Structural regions first, so a request about "the bottom of the page" finds
# the footer knobs before generic card/button styling.
_REGION_ORDER = (
    "site-footer", "footer", "site-header", "header", "hero", "closing",
    "nav", "section-heading", "manifesto", "location", "course", "card",
    "button",
)


def _layout_rank(selector: str) -> int:
    """Prioritise real layout knobs over bare tags and :root variable blocks."""
    if selector.startswith(":root"):
        return 3
    if any(w in selector.lower() for w in _LAYOUT_WORDS):
        return 0
    if selector.startswith((".", "#")):
        return 1
    return 2


def _region_key(selector: str) -> int:
    low = selector.lower()
    for i, word in enumerate(_REGION_ORDER):
        if word in low:
            return i
    return len(_REGION_ORDER)


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


def _css_entries(css: str, file: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for m in _CSS_RULE_RE.finditer(css or ""):
        selector = re.sub(r"\s+", " ", m.group(1)).strip()
        body = m.group(2)
        if not selector or "{" in selector or not body:
            continue
        for dm in _CSS_DECL_RE.finditer(body):
            prop, value = dm.group(1).strip(), dm.group(2).strip()
            key = (selector, prop)
            if key in seen:
                continue
            seen.add(key)
            # find = the declaration only: compact, and unique enough that the
            # model can use it blind (validation still catches ambiguity).
            rule_open = m.start() + len(m.group(1)) + 1  # position of '{' in css
            decl = re.sub(
                r"\s+", " ", css[rule_open + dm.start():rule_open + dm.end()]
            ).strip()
            entries.append({
                "kind": "css", "label": f"{selector} {prop}", "file": file,
                "selector": selector, "prop": prop, "current": value, "find": decl,
                "unique": css.count(decl) == 1,
            })
    entries.sort(key=lambda e: (_layout_rank(e["selector"]), _region_key(e["selector"]),
                                e["selector"], e["prop"]))
    trimmed = [e for e in entries if not e["selector"].startswith(":root")]
    trimmed += [e for e in entries if e["selector"].startswith(":root")][:8]
    return trimmed


def _text_entries(html: str, file: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for m in _TEXT_RE.finditer(html or ""):
        tag, inner = m.group(1).lower(), m.group(2)
        text = _text(inner)
        if len(text) < 2 or text in seen or _PLACEHOLDER_RE.match(text):
            continue
        key = (tag, text[:_MAX_TEXT])
        if key in seen:
            continue
        seen.add(key)
        find = text[:80]  # real prefix substring — usable blind
        entries.append({
            "kind": "text", "label": f"{tag} \"{text[:40]}\"", "file": file,
            "selector": tag, "current": text[:_MAX_TEXT], "find": find,
            "unique": (html or "").count(find) == 1,
        })
        if len(entries) >= _MAX_PER_FILE:
            return entries
    return entries


def _field_entries(content: dict[str, Any], file: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                walk(value, path)
        elif isinstance(node, (str, int, float, bool)) and node != "" and prefix:
            entries.append({
                "kind": "field", "label": f"content {prefix}", "file": file,
                "field": prefix, "current": str(node)[:_MAX_FIELD],
            })

    walk(content, "")
    return entries[:_MAX_PER_FILE]


def build(clone: Path, ref: str = "origin/main") -> dict[str, list[dict[str, Any]]]:
    """Deterministic map keyed by file, straight out of the git ref."""
    files = [f for f in _git(clone, "ls-tree", "-r", "--name-only", ref).splitlines() if f.strip()]
    if not files:
        return {}
    html = sorted(
        [f for f in files if f.lower().endswith((".html", ".htm"))],
        key=lambda p: (p.lower() != "index.html", p),
    )
    css = sorted(
        [f for f in files if f.lower().endswith(".css")],
        key=lambda p: (p.lower() != "styles.css", p),
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for sheet in css[:2]:
        if sheet.rsplit("/", 1)[-1].startswith("admin"):
            continue
        text = _show(clone, ref, sheet)
        if text:
            result[sheet] = _css_entries(text, sheet)
    for page in html[:10]:
        if page.rsplit("/", 1)[-1].startswith("admin"):
            continue
        text = _show(clone, ref, page)
        if text:
            result[page] = _text_entries(text, page)
    if "content.json" in files:
        try:
            content = json.loads(_show(clone, ref, "content.json") or "{}")
            if isinstance(content, dict):
                result["content.json"] = _field_entries(content, "content.json")
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def _dedupe(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for e in entries:
        key = (e.get("kind", ""), e.get("selector", e.get("field", e.get("label", ""))),
               e.get("prop", e.get("current", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
        if len(out) >= _MAX_PER_FILE:
            break
    return out


def merge(base: dict[str, list[dict[str, Any]]],
          overlay: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Builder's semantic entries win over the deterministic ones per knob."""
    out = dict(base)
    for file, entries in (overlay or {}).items():
        if not isinstance(entries, list):
            continue
        out[file] = _dedupe(list(entries) + out.get(file, []))
    return out


def ensure(memory: Any, config: dict[str, Any]) -> dict[str, list[dict[str, Any]]] | None:
    """The site map: deterministic base (kv-cached on the origin/main commit)
    with the builder's semantic overlay merged on top fresh each call."""
    if memory is None:
        return None
    clone = Path(str((config.get("site") or {}).get("clone_path", "")).strip())
    if not clone.exists() or not (clone / ".git").exists():
        return None
    head = _git(clone, "rev-parse", "origin/main").strip()
    if not head:
        return None
    cached = memory.kv_get(CACHE_KEY)
    if isinstance(cached, dict) and cached.get("head") == head and isinstance(cached.get("files"), dict):
        base = cached["files"]
    else:
        base = build(clone)
        try:
            memory.kv_set(CACHE_KEY, {"head": head, "files": base})
        except Exception:  # noqa: BLE001
            pass
    overlay = memory.kv_get(BUILDER_KEY)
    overlay_files = overlay.get("files") if isinstance(overlay, dict) else None
    return merge(base, overlay_files) if overlay_files else base


def store_builder_map(clone: Path, memory: Any, preview_head: str) -> None:
    """Persist the map the builder agent wrote into .opencode/tweak-map.json."""
    if memory is None:
        return
    path = clone / ".opencode" / "tweak-map.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    files = data.get("files") if isinstance(data, dict) and isinstance(data.get("files"), dict) else (data if isinstance(data, dict) else None)
    if not files:
        return
    memory.kv_set(BUILDER_KEY, {"head": preview_head, "files": files})


def drop_builder_map(memory: Any) -> None:
    if memory is not None:
        try:
            memory.kv_set(BUILDER_KEY, None)
        except Exception:  # noqa: BLE001
            pass


def summary(files: dict[str, list[dict[str, Any]]] | None, max_chars: int = 2400) -> str:
    if not files:
        return ""
    lines: list[str] = []
    total = 0
    for file, entries in files.items():
        if not entries:
            continue
        lines.append(f"{file}:")
        for e in entries[:_MAX_PER_FILE]:
            if e.get("kind") == "css":
                tag = "unique" if e.get("unique") else "ambiguous"
                lines.append(f'  {e["selector"]} {e["prop"]} = {e["current"]}  '
                             f'(snippet: "{e.get("find", "")}" — {tag})')
            elif e.get("kind") == "field":
                lines.append(f'  content field {e["field"]} = "{e["current"]}"')
            else:
                lines.append(f'  {e.get("selector", "text")} "{e["current"]}"')
            total += 1
            if total >= _MAX_TOTAL:
                break
        if total >= _MAX_TOTAL:
            break
    return "\n".join(lines)[:max_chars]