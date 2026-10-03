"""editor.py — the admin chat: owner asks, Ada implements, owner approves.

She has hands, not scripts: repository tools (read / spawn_build) matching
writable_patterns, plus read-only senses. Source changes are implemented by
the builder in an approval-gated preview; nothing reaches production without
approval.

``propose_changes`` remains as a compatibility fallback for installations
without the builder. It only records an edit draft and cannot produce the
compiled preview used by an existing source-backed site.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..hands.base import AdapterError, SiteAdapter
from ..hands.repo_changes import HARD_DENY, normalize_path, writable
from ..core.design_contracts import DesignRequest
from .owner_copy import owner_safe_reply as _owner_safe_reply
from .prompts import configured_site_profile_prompt, inner_life_context


class EditError(ValueError):
    pass


def slugify(text: str) -> str:
    allowed = []
    for ch in text.lower():
        if ch.isalnum():
            allowed.append(ch)
        elif ch in " -_":
            allowed.append("-")
    slug = "".join(allowed).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "untitled"


def _workspace_language(message: str) -> str:
    """Read only the explicit language metadata added by the trusted bridge."""
    context_block = str(message or "").split("[User request]", 1)[0]
    match = re.search(r'"language"\s*:\s*"([a-z]{2,3}(?:-[a-z0-9]{2,8}){0,2})"', context_block, re.IGNORECASE)
    return match.group(1).lower() if match else ""


def set_dotted(doc: dict[str, Any], field: str, value: Any) -> Any:
    keys = [k for k in field.split(".") if k]
    if not keys:
        raise EditError("empty field path")
    current: Any = doc
    for key in keys[:-1]:
        if not isinstance(current, dict) or key not in current:
            raise EditError(f"unknown section '{key}'")
        current = current[key]
    if not isinstance(current, dict) or keys[-1] not in current:
        raise EditError(f"unknown field '{field}' — only existing fields can be changed")
    old = current[keys[-1]]
    current[keys[-1]] = value
    return old


_READ_ACTIONS = {"read_file", "list_files", "get_content", "get_metrics", "get_growth", "list_drafts", "recall",
                 "search_media", "search_business_knowledge", "read_payload_content",
                 "inspect_editable_fields", "validate_editable_fields"}


def _looks_like_design_request(message: str) -> bool:
    """Keep broad visual work on the typed design path, not focused edit tools."""
    text = str(message or "").lower()
    broad = (
        "redesign", "new website", "new site", "new homepage", "new landing page",
        "design the homepage", "design a page", "build a page", "create a page",
        "look and feel", "visual direction", "restyle the site", "rethink the layout",
        "make the homepage", "make the site",
    )
    focused = ("typo", "spelling", "change the text", "update the link", "fix the link")
    return any(phrase in text for phrase in broad) and not any(phrase in text for phrase in focused)


def _looks_like_source_edit_request(message: str) -> bool:
    """Recognize a targeted rendered/source change on an existing site.

    This is intentionally narrower than ``_looks_like_design_request``. The
    operational distinction matters: a source-backed site needs a real build
    even when the requested change is only one CSS selector.
    """
    text = str(message or "").lower()
    source_terms = (
        "css", "stylesheet", "style", "styles", "layout", "spacing", "padding", "margin",
        "heading", "headings", "paragraph", "line break", "line-break", "wrap", "wrapped",
        "typography", "font", "responsive", "mobile", "desktop", "animation", "motion",
        "component", "section", "button", "cramped", "break every", "breaking every",
    )
    action_terms = (
        "fix", "adjust", "change", "review", "make", "give", "stop", "remove", "improve",
        "widen", "narrow", "loosen", "tighten", "prevent", "correct", "update",
    )
    return any(term in text for term in source_terms) and any(term in text for term in action_terms)


def _content_summary(content: dict[str, Any]) -> str:
    def shape(value: Any, depth: int = 0) -> str:
        if isinstance(value, dict):
            inner = ", ".join(f"{k}: {shape(v, depth + 1)}" for k, v in list(value.items())[:12])
            return "{" + inner + "}"
        if isinstance(value, list):
            if value and all(isinstance(item, dict) for item in value[:5]):
                sample = ", ".join(shape(item, depth + 1) for item in value[:5])
                suffix = ", …" if len(value) > 5 else ""
                return f"list[{len(value)}] [{sample}{suffix}]"
            return f"list[{len(value)}]"
        text = str(value)
        return f"{text[:60]}…" if len(text) > 60 else text

    return shape(content)


def _staged_branch(context: dict[str, Any]) -> str | None:
    """Use the same preview ref the Design tab uses while a build is pending."""
    memory = context.get("memory")
    if memory is None:
        return None
    try:
        has_merge = any(d.get("kind") == "merge" for d in memory.list_drafts(status="pending"))
    except Exception:  # noqa: BLE001
        has_merge = False
    if not has_merge:
        return None
    branch = str((context.get("config", {}).get("site") or {}).get("preview_branch") or "preview")
    return branch


def _get_file(context: dict[str, Any], adapter: SiteAdapter, path: str):
    branch = _staged_branch(context)
    try:
        return adapter.get_file(str(path).lstrip("/"), branch=branch)
    except TypeError:
        return adapter.get_file(str(path).lstrip("/"))


def _cached_file(context: dict[str, Any], adapter: SiteAdapter, path: str) -> bytes | None:
    from ..hands import file_cache

    return file_cache.get(context["config"], adapter, path, branch=_staged_branch(context))


def _cached_content(context: dict[str, Any], adapter: SiteAdapter) -> dict[str, Any] | None:
    path = str((context["config"].get("site") or {}).get("content_path", "content.json"))
    raw = _cached_file(context, adapter, path)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode(errors="replace"))
    except json.JSONDecodeError:
        return None


def _decision_ledger_block(context: dict[str, Any]) -> str:
    """Recent owner decisions supplied as structured conversational context."""
    memory = context.get("memory")
    if memory is None:
        return ""
    try:
        decisions = memory.recent_decisions(limit=8)
    except Exception:  # noqa: BLE001 — never let the ledger break chat
        return ""
    if not decisions:
        return ""
    lines = []
    for d in decisions:
        kind = f"[{d['kind']}]"
        title = str(d.get("title") or "").strip()[:120]
        status = str(d.get("status") or "").upper()
        ops = (d.get("meta") or {}).get("ops") or []
        paths = ", ".join(sorted({str(o.get("path") or "") for o in ops if o.get("path")}))
        entry = f"- #{d['id']} {status} {kind} {title}"
        if paths:
            entry += f" (files: {paths})"
        feedback = str((d.get("meta") or {}).get("feedback") or "").strip()
        if status == "DECLINED" and feedback:
            entry += f" — owner's note: {feedback[:140]}"
        lines.append(entry)
    return ("\n\nOwner decision ledger (recent approved/declined proposals, newest first — "
            "context so you don't repeat rejected work and know what shipped):\n" + "\n".join(lines))


def _content_summary_cached(context: dict[str, Any], adapter: SiteAdapter) -> str:
    try:
        doc = _cached_content(context, adapter)
        if doc is not None:
            return _content_summary(doc)
    except Exception:  # noqa: BLE001
        pass
    try:
        branch = _staged_branch(context)
        try:
            doc = adapter.get_content(branch=branch)
        except TypeError:
            doc = adapter.get_content()
        return _content_summary(doc)
    except Exception:  # noqa: BLE001
        return ""


def validate_ops(context: dict[str, Any], ops: list[dict[str, Any]], adapter: SiteAdapter) -> list[dict[str, Any]]:
    """Normalize + sanity-check ops against writable patterns. Raises EditError."""
    patterns = [str(p) for p in ((context["config"].get("site") or {}).get("writable_patterns") or [])]
    clean = []
    for op in (ops or [])[:10]:
        kind = str(op.get("op", "")).strip().lower()
        path = normalize_path(str(op.get("path", "")))
        if kind == "set_field":
            if "field" not in op or "value" not in op:
                raise EditError("set_field needs field + value")
            content_path = str((context["config"].get("site") or {}).get("content_path", "content.json")).lstrip("/")
            target = normalize_path(str(op.get("path") or content_path))
            if target != content_path or any(denied in target for denied in HARD_DENY):
                raise EditError(f"set_field can only change {content_path}")
            _, raw = _get_file(context, adapter, target)   # live read: validation is the safety net
            if raw is None:
                raise EditError(f"{target}: file not found")
            probe = json.loads(raw)
            node: Any = probe
            for key in [k for k in op["field"].split(".") if k][:-1]:
                if not isinstance(node, dict) or key not in node:
                    raise EditError(f"unknown section '{key}' in {target}")
                node = node[key]
            last = op["field"].split(".")[-1]
            if not isinstance(node, dict) or last not in node:
                raise EditError(f"unknown field '{op['field']}' in {target}")
            clean.append({"op": "set_field", "path": target,
                          "field": str(op["field"]), "value": op.get("value")})
            continue
        if kind not in ("write", "edit", "delete"):
            raise EditError(f"unknown op '{kind}'")
        if not path or not writable(path, patterns):
            raise EditError(f"'{path}' is outside my writable area ({patterns or 'none configured'})")
        entry = {"op": kind, "path": path}
        if kind == "write":
            content = str(op.get("content", ""))
            if not content.strip():
                raise EditError(f"write {path}: empty content")
            entry["content"] = content
        elif kind == "edit":
            find, replace = str(op.get("find", "")), str(op.get("replace", ""))
            if not find.strip():
                raise EditError(f"edit {path}: missing find")
            _, raw = _get_file(context, adapter, path)   # live read: validation is the safety net
            if raw is None:
                raise EditError(f"edit {path}: file not found")
            count = raw.decode().count(find)
            if count == 0:
                raise EditError(f"edit {path}: snippet not found — read_file first")
            if count > 1:
                raise EditError(f"edit {path}: snippet appears {count} times — include more context")
            entry.update({"find": find, "replace": replace})
        clean.append(entry)
    if not clean:
        raise EditError("no operations provided")
    return clean


def store_proposal(memory: Any, meta: dict[str, Any], summary: str) -> int:
    """Persist one reviewable edit proposal."""
    ops = list(meta.get("ops") or [])
    return memory.save_draft(
        title=f"Proposed changes: {summary}"[:120],
        body=json.dumps(ops, indent=2),
        kind="edit",
        meta={**meta, "ops": ops, "summary": summary},
    )


def _apply_ops(adapter: SiteAdapter, ops: list[dict[str, Any]], branch: str | None = None, memory: Any = None):
    results = []
    for op in ops:
        kind, path = op["op"], op["path"]
        if kind == "set_field":  # content.json dotted-field edit (legacy/structured)
            try:
                doc = adapter.get_content(branch=branch)
            except TypeError:
                doc = adapter.get_content()
            set_dotted(doc, op["field"], op["value"])
            r = adapter.commit_file(
                path or "content.json",
                (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode(),
                f"[{branch or 'main'}] set {op['field']}", branch=branch,
            )
        elif kind == "write":
            r = adapter.commit_file(path, op["content"].encode(), f"[{branch or 'main'}] write {path}", branch=branch)
        elif kind == "edit":
            _, raw = adapter.get_file(path, branch=branch)
            if raw is None:
                base_raw = adapter.get_file(path)
                raw = base_raw[1]
            text = (raw or b"").decode()
            if op["find"] not in text:
                # already applied (e.g. an approve retry) — nothing to do
                results.append({"skipped": True, "path": path})
                continue
            r = adapter.commit_file(
                path, text.replace(op["find"], op["replace"], 1).encode(),
                f"[{branch or 'main'}] edit {path}", branch=branch,
            )
        else:
            r = adapter.delete_file(path, f"[{branch or 'main'}] delete {path}", branch=branch)
        results.append(r)
    return results


def _writable_patterns(context: dict[str, Any]) -> list[str]:
    return [str(p) for p in ((context["config"].get("site") or {}).get("writable_patterns") or [])]


def _payload_gateway(context: dict[str, Any]):
    return context.get("payload_gateway")


def _payload_result(document: Any, *, action: str) -> str:
    if not isinstance(document, dict):
        return f"Payload {action} completed, but returned no document."
    compact = {
        key: document.get(key)
        for key in ("id", "sourceId", "slug", "title", "_status", "updatedAt")
        if key in document
    }
    if action == "read":
        for key in ("content", "sections", "description", "excerpt", "metaDescription", "seo"):
            if key in document:
                compact[key] = document[key]
    rendered = json.dumps(compact, ensure_ascii=False, default=str)
    return rendered[:8000] + ("…" if len(rendered) > 8000 else "")


def _editable_fields_result(result: Any, *, action: str) -> str:
    """Keep the field gateway response useful without exposing a whole document."""
    if not isinstance(result, dict):
        return f"Editable field {action} completed, but returned no result."
    compact = {
        key: result.get(key)
        for key in (
            "collection", "document_id", "revision", "valid", "validation_errors", "field", "fields",
        )
        if key in result
    }
    rendered = json.dumps(compact, ensure_ascii=False, default=str)
    return rendered[:8000] + ("…" if len(rendered) > 8000 else "")


def _tools_spec(
    context: dict[str, Any],
    *,
    design_intent: bool = False,
    source_edit_intent: bool = False,
) -> list[dict[str, Any]]:
    # ``source_edit_intent`` is retained as a compatibility argument for
    # callers that still pass the old classifier result.  Capability, not
    # English wording, decides whether a source mutation is a builder job.
    from ..hands import opencode_runner as _runner

    cfg = context.get("config") if isinstance(context.get("config"), dict) else context
    source_builder_available = _runner.builder_available(cfg)
    canonical_design_handoff = design_intent and context.get("design_service") is not None
    use_existing_builder = source_builder_available and not canonical_design_handoff

    def fn(name, desc, props, required=None):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {"type": "object", "properties": props, "required": required or []},
            },
        }

    tools = [
        fn("read_file", "Read a file from the site repo. For big files pass "
           "'contains' with a distinctive substring (e.g. 'footer') to jump straight "
           "to that region instead of getting the head of the file.",
           {"path": {"type": "string"},
            "contains": {"type": "string", "description": "substring to locate"}}, ["path"]),
        fn("list_files", "List every file path in the site repo", {}),
        fn("get_content", "Read the structured text fields (content.json)", {}),
        fn("get_metrics", "Read persisted GA4 and Search Console evidence with collection timestamps; no collection or spending", {}),
        fn("get_growth", "Read the current Growth workspace: provider configuration, verification, evidence freshness, keyword research readiness, schedules and approvals. Never provisions or spends.", {}),
        fn("list_drafts", "Pending proposals awaiting owner approval", {}),
        fn("recall_memory",
           "Remember by meaning: pull your own past memories — what you learned, "
           "dreamed, observed, or thought about a topic — ranked by relevance. "
           "Use this when you should answer from your own memory instead of "
           "guessing or asking.",
            {"query": {"type": "string", "description": "what you want to remember"}}, ["query"]),
        fn("search_media", "Find ready Library images by description, tags, OCR, name, or suggested use. Returns IDs only, never URLs.",
           {"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]),
        fn("search_business_knowledge", "Find owner-approved business information from the Library.",
           {"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]),
    ]
    if not source_builder_available or canonical_design_handoff:
        tools.extend([
            fn("design_request",
               "Start the canonical asynchronous design workflow for a new site, redesign, or complete page. "
               "Return a complete validated intake; do not invent facts or destinations.",
                {
                    "intent": {"type": "string", "enum": ["initial_site", "redesign", "derived_page"]},
                    "intake": {"type": "object"},
                    "owner_summary": {"type": "string"},
                    "target": {
                        "type": "object",
                        "description": "The selected post-intake workspace target, when supplied in context.",
                        "additionalProperties": True,
                    },
                }, ["intent", "intake", "owner_summary"]),
        ])
    if not source_builder_available and not canonical_design_handoff:
        tools.append(fn(
            "propose_changes",
            "Compatibility fallback: stage one or more file operations as a proposal the owner must approve. "
            "This records an edit draft but does not build a rendered preview. "
            "ops entries: {op:'edit',path,find(unique exact snippet),replace} | "
            "{op:'write',path,content(full file)} | {op:'delete',path} | "
            "{op:'set_field',field(dotted into content.json),value}",
            {"summary": {"type": "string"},
             "ops": {"type": "array", "items": {"type": "object"}}},
            ["summary", "ops"]),
        )
    if _payload_gateway(context) is not None:
        payload = _payload_gateway(context)
        contract = getattr(payload, "contract", None)
        configured_collections = tuple(getattr(contract, "collections", ()) or ())
        configured_globals = tuple(getattr(contract, "globals", ()) or ())
        collection = {"type": "string"}
        if configured_collections:
            collection["enum"] = list(configured_collections)
        payload_global = {"type": "string"}
        if configured_globals:
            payload_global["enum"] = list(configured_globals)
        data = {
            "type": "object",
            "description": "Only fields from the selected collection's editable draft schema.",
            "additionalProperties": True,
        }
        tools.extend([
            fn(
                "read_payload_content",
                "Read one Payload document. Use this before changing content; identify it with the selected workspace document sourceId when available.",
                {
                    "collection": collection,
                    "identifier": {"type": "string", "description": "Payload id, sourceId, or slug"},
                    "identifier_kind": {"type": "string", "enum": ["id", "sourceId", "slug"]},
                    "draft": {"type": "boolean"},
                },
                ["collection", "identifier"],
            ),
            fn(
                "inspect_editable_fields",
                "Read the explicit editable-field registry for one Payload document. Do not scan source code or infer fields from rendered text; use only the returned stable field IDs.",
                {
                    "collection": collection,
                    "identifier": {"type": "string", "description": "Payload id, sourceId, or slug"},
                    "identifier_kind": {"type": "string", "enum": ["id", "sourceId", "slug"]},
                    "draft": {"type": "boolean"},
                },
                ["collection", "identifier"],
            ),
            fn(
                "define_editable_field",
                "Define one stable, declarative field binding on an existing Payload document. This writes a draft only. Use a dotted field ID such as page.hero.heading; never generate a field ID from visible copy or a DOM position.",
                {
                    "collection": collection,
                    "identifier": {"type": "string", "description": "Payload id, sourceId, or slug"},
                    "identifier_kind": {"type": "string", "enum": ["id", "sourceId", "slug"]},
                    "key": {"type": "string", "description": "Stable dotted ID, for example page.hero.heading"},
                    "type": {"type": "string", "enum": ["text", "richText", "image", "link"]},
                    "label": {"type": "string"},
                    "section": {"type": "string"},
                    "value": {"description": "Initial text, rich-text-compatible value, or portable image source ID"},
                    "image": {"description": "Portable media source ID or {sourceId/id} reference for an image field"},
                    "rich_text": {"type": "object", "additionalProperties": True},
                },
                ["collection", "identifier", "key", "type", "label"],
            ),
            fn(
                "migrate_editable_fields",
                "Apply an explicit batch of declarative field definitions to an existing Payload document in one draft update. The definitions must come from an intentional migration plan; this tool does not scan source code or infer fields.",
                {
                    "collection": collection,
                    "identifier": {"type": "string", "description": "Payload id, sourceId, or slug"},
                    "identifier_kind": {"type": "string", "enum": ["id", "sourceId", "slug"]},
                    "fields": {
                        "type": "array",
                        "maxItems": 100,
                        "items": {
                            "type": "object",
                            "required": ["key", "type", "label"],
                            "additionalProperties": True,
                        },
                    },
                },
                ["collection", "identifier", "fields"],
            ),
            fn(
                "set_editable_field",
                "Update the value of an existing registered field in a draft. Inspect the registry first and pass expected_value when the current value matters; this tool cannot create a missing binding.",
                {
                    "collection": collection,
                    "identifier": {"type": "string", "description": "Payload id, sourceId, or slug"},
                    "identifier_kind": {"type": "string", "enum": ["id", "sourceId", "slug"]},
                    "key": {"type": "string"},
                    "value": {"description": "New text or rich text value"},
                    "image": {"description": "New portable media source ID or {sourceId/id} reference"},
                    "expected_value": {"type": "string"},
                },
                ["collection", "identifier", "key"],
            ),
            fn(
                "validate_editable_fields",
                "Validate the explicit field registry without writing. Reports invalid IDs, duplicate bindings, missing labels, or unsupported types.",
                {
                    "collection": collection,
                    "identifier": {"type": "string", "description": "Payload id, sourceId, or slug"},
                    "identifier_kind": {"type": "string", "enum": ["id", "sourceId", "slug"]},
                },
                ["collection", "identifier"],
            ),
            fn(
                "create_payload_draft",
                "Create a new Payload draft. Ask for missing required business facts instead of inventing them.",
                {"collection": collection, "data": data},
                ["collection", "data"],
            ),
            fn(
                "update_payload_draft",
                "Update only the requested fields on an existing Payload draft. Never publish as part of this tool.",
                {"collection": collection, "id": {"type": "string"}, "data": data},
                ["collection", "id", "data"],
            ),
             fn(
                 "publish_payload_document",
                  "Publish an existing Payload document only when the owner explicitly asks to publish it.",
                 {"collection": collection, "id": {"type": "string"}},
                 ["collection", "id"],
             ),
             fn(
                 "read_payload_global",
                  "Read one shared Payload global. Use this before changing navigation or site-wide settings.",
                 {
                      "global": payload_global,
                     "draft": {"type": "boolean"},
                 },
                 ["global"],
             ),
             fn(
                 "update_payload_global",
                  "Update selected fields on a shared Payload global draft. Never publish as part of this tool.",
                 {
                      "global": payload_global,
                     "data": {"type": "object", "additionalProperties": True},
                 },
                 ["global", "data"],
             ),
             fn(
                 "publish_payload_global",
                  "Publish a shared Payload global only when the owner explicitly asks to publish it.",
                  {"global": payload_global},
                 ["global"],
             ),
         ])
    if use_existing_builder:
        tools.append(fn(
            "spawn_build",
            "Open an autonomous coding session on the existing repository for every "
            "source, style, layout, responsive, or visual change — including a "
            "one-line focused fix. The builder reads the current files, implements "
            "the change in an isolated preview, and returns an approval-gated merge "
            "draft. Do not use a proposal-only tool for source changes. The builder's tools:\n" +
            _runner.BUILDER_TOOLSET,
            {"brief": {"type": "string"}}, ["brief"]),
        )
    return tools


SYSTEM_NOTE_TOOLS = (
    "\n\nYou operate the site repository through your tools. Sandbox: writable paths are %%WRITABLE%%. "
    "Every implementation goes to an approval-gated preview first and ships only when the owner approves. "
    "You are the creative lead: the owner expects high-end, distinctive design, not a template "
    "or typical CMS look, and you have full coding capability through the builder for that. "
    "For an existing source-backed site, use spawn_build for every source, style, layout, "
    "responsive, or visual change — even a focused one-line fix. It inspects the repository, "
    "implements the change, and creates the rendered preview/approval draft. Do not use the "
    "legacy proposal-only path for source changes. The typed design handoff is only for a "
    "site without an existing source workspace. "
    "Read tools exist to inform your answer; once you have what you need, act. "
    "Do not re-read what you already saw."
    "\n\nOWNER-FACING COMMUNICATION (important): "
    "The owner is not technical. Never expose repository, branch, worktree, GitHub, API, "
    "credential, sandbox, prompt, model, or tooling details in the visible reply unless the "
    "owner explicitly asks for a technical diagnosis. Do not claim that files failed to open "
    "unless a read/list tool call in this turn actually returned an error. If you are only "
    "offering initial ideas, say plainly that they are ideas based on the brief, that nothing "
    "has changed or been previewed, and that you will verify the current page before building. "
    "If a real inspection or build is blocked, explain the owner-facing consequence and next "
    "step without naming the internal failure: for example, 'I couldn't verify the current "
    "page yet, so I haven't made a preview. I'll verify it first, then continue.' Never turn "
    "a transient tool failure into a claim about the site's files."
)


def _execute_tool(context: dict[str, Any], adapter: SiteAdapter, name: str, args: dict[str, Any], say) -> str:
    memory = context["memory"]
    phrase = {
        "read_file": lambda: f"reading {args.get('path', '')}",
        "list_files": lambda: "listing repository files",
        "get_content": lambda: "reading content.json",
        "get_metrics": lambda: "reading saved analytics and search evidence",
        "get_growth": lambda: "checking growth connections and approvals",
        "list_drafts": lambda: "checking pending drafts",
        "recall_memory": lambda: "searching my memory",
        "search_media": lambda: "searching the Library",
        "search_business_knowledge": lambda: "searching approved business knowledge",
        "propose_changes": lambda: "staging the change",
        "spawn_build": lambda: "briefing the builder agent",
        "design_request": lambda: "preparing the typed design handoff",
         "read_payload_content": lambda: "reading the selected Payload document",
        "inspect_editable_fields": lambda: "reading the declared editable fields",
        "define_editable_field": lambda: "declaring an editable field draft",
        "set_editable_field": lambda: "updating an editable field draft",
        "migrate_editable_fields": lambda: "migrating declared editable fields",
        "validate_editable_fields": lambda: "validating the declared editable fields",
        "create_payload_draft": lambda: "creating a Payload draft",
        "update_payload_draft": lambda: "updating the Payload draft",
        "publish_payload_document": lambda: "publishing the Payload document",
        "read_payload_global": lambda: "reading the shared Payload global",
        "update_payload_global": lambda: "updating the shared Payload global draft",
        "publish_payload_global": lambda: "publishing the shared Payload global",
    }.get(name, lambda: name)
    say(phrase())
    if name == "read_file":
        from ..hands import file_cache

        path = str(args.get("path", "")).lstrip("/")
        contains = str(args.get("contains") or "")
        if file_cache.has(context["config"], path, branch=_staged_branch(context)):
            say(f"{name}: {path} (cached)")
        cache = context.setdefault("_read_cache", {})
        key = f"{path}::{contains}"
        if key in cache:
            if len(cache[key]) > 1500:
                return (f"[You already read {path} this turn; the content is in context. "
                        "Use read_file with 'contains' to probe a specific region, or act on what you have.]")
            return cache[key]
        blob = _cached_file(context, adapter, path)
        if blob is None:
            out = "File does not exist."
        else:
            text = blob.decode(errors="replace")
            if contains and contains in text:
                idx = max(0, text.find(contains) - 400)
                window = text[idx:idx + 3600]
                from ..hands import opencode_runner as _runner
                next_step = (
                    "use spawn_build with a concise implementation brief"
                    if _runner.builder_available(context.get("config") or {})
                    else "use propose_changes edit with an exact unique snippet"
                )
                out = f"[{path} around '{contains}']\n{window}\n\n[{next_step}]"
            elif contains:
                out = f"'{contains}' not found in {path} ({len(text)} chars). Head of file:\n" + text[:3600]
            elif len(text) > 3600:
                out = (text[:3600] + "\n\n[file continues — call read_file with 'contains' "
                       "to jump to the region you need (e.g. 'hero', 'reveal', 'motion')]")
            else:
                out = text
        cache[key] = out
        return out
    if name == "list_files":
        try:
            branch = _staged_branch(context)
            try:
                files = adapter.list_files(branch=branch)
            except TypeError:
                files = adapter.list_files()
            return "\n".join(files[:150])
        except AttributeError:
            return "Listing not supported on this adapter."
    if name == "get_content":
        doc = _cached_content(context, adapter)
        if doc is None:
            return "content.json not found."
        return _content_summary(doc)
    if name == "get_metrics":
        from ..application.growth import growth_metrics
        return json.dumps(growth_metrics(memory), ensure_ascii=False)
    if name == "get_growth":
        from ..application.growth import growth_chat_context
        return json.dumps(growth_chat_context(memory, context["config"], context), ensure_ascii=False)
    if name == "list_drafts":
        drafts = memory.list_drafts(status="pending", limit=10)
        return "\n".join(f"#{d['id']} [{d['kind']}] {d['title']}" for d in drafts) or "(no pending drafts)"
    if name == "recall_memory":
        from ..core import memory_store

        query = str(args.get("query", "")).strip()
        if not query:
            return "recall_memory needs a non-empty query."
        try:
            recalled = memory_store.recall_by_meaning(memory, query, k=8)
            return memory_store.fmt_recall(recalled)
        except Exception as exc:  # noqa: BLE001
            return f"recall failed: {exc}"
    if name == "search_media":
        service = context.get("media_service")
        if service is None:
            return "The media Library is not enabled."
        query = str(args.get("query") or "").strip()
        terms = set(query.lower().split())
        rows = []
        for asset in memory.list_media_assets(status="ready", media_kind="image", limit=500):
            haystack = " ".join([asset.original_name, asset.description, asset.ocr_text, *asset.tags,
                                  *[str(x) for x in (asset.analysis.get("suggested_uses") or [])]]).lower()
            score = sum(term in haystack for term in terms)
            if score:
                rows.append((score, {"asset_id": asset.asset_id, "name": asset.original_name,
                                     "description": asset.description[:400], "width": asset.width,
                                     "height": asset.height, "media_kind": asset.media_kind.value}))
        return json.dumps([item for _, item in sorted(rows, key=lambda x: -x[0])[:int(args.get("limit", 8))]])
    if name == "search_business_knowledge":
        service = context.get("business_knowledge_service")
        if service is None:
            return "Approved business knowledge is not available."
        return json.dumps(service.search(str(args.get("query") or ""), int(args.get("limit", 8))))
    if name in {
        "read_payload_content", "create_payload_draft", "update_payload_draft", "publish_payload_document",
        "read_payload_global", "update_payload_global", "publish_payload_global",
        "inspect_editable_fields", "define_editable_field", "set_editable_field", "validate_editable_fields",
        "migrate_editable_fields",
    }:
        payload = _payload_gateway(context)
        if payload is None:
            return "Payload content editing is not configured on this site-agent instance."
        try:
            locale = context.get("_workspace_language") or None
            if name == "read_payload_content":
                read_kwargs = {
                    "identifier": str(args.get("identifier") or ""),
                    "identifier_kind": str(args.get("identifier_kind") or "sourceId"),
                    "draft": bool(args.get("draft", True)),
                }
                if locale:
                    read_kwargs["locale"] = locale
                document = payload.read(
                    str(args.get("collection") or ""),
                    **read_kwargs,
                )
                return _payload_result(document, action="read")
            if name == "inspect_editable_fields":
                result = payload.inspect_editable_fields(
                    str(args.get("collection") or ""),
                    identifier=str(args.get("identifier") or ""),
                    identifier_kind=str(args.get("identifier_kind") or "sourceId"),
                    draft=bool(args.get("draft", True)),
                    locale=locale,
                )
                return _editable_fields_result(result, action="inspection")
            if name == "define_editable_field":
                result = payload.define_editable_field(
                    str(args.get("collection") or ""),
                    identifier=str(args.get("identifier") or ""),
                    identifier_kind=str(args.get("identifier_kind") or "sourceId"),
                    key=str(args.get("key") or ""),
                    field_type=str(args.get("type") or ""),
                    label=str(args.get("label") or ""),
                    section=args.get("section"),
                    value=args.get("value"),
                    image=args.get("image"),
                    rich_text=args.get("rich_text"),
                    locale=locale,
                )
                context["_last_action_succeeded"] = True
                return f"Editable field draft defined: {_editable_fields_result(result, action='definition')}"
            if name == "set_editable_field":
                result = payload.set_editable_field(
                    str(args.get("collection") or ""),
                    identifier=str(args.get("identifier") or ""),
                    identifier_kind=str(args.get("identifier_kind") or "sourceId"),
                    key=str(args.get("key") or ""),
                    value=args.get("value"),
                    image=args.get("image"),
                    expected_value=args.get("expected_value"),
                    locale=locale,
                )
                context["_last_action_succeeded"] = True
                return f"Editable field draft updated: {_editable_fields_result(result, action='update')}"
            if name == "migrate_editable_fields":
                result = payload.migrate_editable_fields(
                    str(args.get("collection") or ""),
                    identifier=str(args.get("identifier") or ""),
                    identifier_kind=str(args.get("identifier_kind") or "sourceId"),
                    fields=args.get("fields") or [],
                    locale=locale,
                )
                context["_last_action_succeeded"] = True
                return f"Editable field migration draft applied: {_editable_fields_result(result, action='migration')}"
            if name == "validate_editable_fields":
                result = payload.validate_editable_fields(
                    str(args.get("collection") or ""),
                    identifier=str(args.get("identifier") or ""),
                    identifier_kind=str(args.get("identifier_kind") or "sourceId"),
                    locale=locale,
                )
                return _editable_fields_result(result, action="validation")
            if name == "read_payload_global":
                read_kwargs = {"draft": bool(args.get("draft", True))}
                if locale:
                    read_kwargs["locale"] = locale
                document = payload.read_global(str(args.get("global") or ""), **read_kwargs)
                return _payload_result(document, action="read")
            if name == "create_payload_draft":
                write_kwargs = {"locale": locale} if locale else {}
                document = payload.create(str(args.get("collection") or ""), args.get("data") or {}, **write_kwargs)
                context["_last_action_succeeded"] = True
                return f"Payload draft created: {_payload_result(document, action='write')}"
            if name == "update_payload_draft":
                write_kwargs = {"locale": locale} if locale else {}
                document = payload.update(
                    str(args.get("collection") or ""),
                    str(args.get("id") or ""),
                    args.get("data") or {},
                    **write_kwargs,
                )
                context["_last_action_succeeded"] = True
                return f"Payload draft updated: {_payload_result(document, action='write')}"
            if name == "publish_payload_document":
                document = payload.publish(str(args.get("collection") or ""), str(args.get("id") or ""))
                context["_last_action_succeeded"] = True
                return f"Payload document published: {_payload_result(document, action='write')}"
            if name == "update_payload_global":
                write_kwargs = {"locale": locale} if locale else {}
                document = payload.update_global(str(args.get("global") or ""), args.get("data") or {}, **write_kwargs)
                context["_last_action_succeeded"] = True
                return f"Payload global draft updated: {_payload_result(document, action='write')}"
            document = payload.publish_global(str(args.get("global") or ""))
            context["_last_action_succeeded"] = True
            return f"Payload global published: {_payload_result(document, action='write')}"
        except Exception as exc:  # noqa: BLE001 — a tool failure should be explained to Ada
            return f"REFUSED: Payload content action failed: {str(exc)[:500]}"
    if name == "propose_changes":
        summary = str(args.get("summary", "site changes"))[:200]
        say("checking every operation against the live files")
        try:
            ops = validate_ops(context, args.get("ops"), adapter)
        except EditError as exc:
            return f"REFUSED: {exc}"
        try:
            proposal_id = store_proposal(memory, {"ops": ops}, summary)
        except EditError as exc:
            return f"REFUSED: {exc}"
        say(f"proposal #{proposal_id} ready")
        context["_last_proposal_id"] = proposal_id
        context["_last_change"] = {
            "status": "stored_only",
            "draft_id": proposal_id,
            "changed_paths": sorted({str(item.get("path") or "") for item in ops}),
            "preview": None,
        }
        context["_last_action_succeeded"] = True
        lines = "\n".join(f"[{o['op']}] {o['path']}" for o in ops)
        return (
            f"Technical edit draft #{proposal_id} recorded.\n"
            "No rendered preview was created by this compatibility path, and no source change is ready for review. "
            "Use the implementation build workflow before asking the owner to review a result.\n"
            f"Operations recorded: {lines}"
        )
    if name == "spawn_build":
        from ..hands import opencode_runner as runner
        brief = str(args.get("brief", "")).strip()
        if not brief:
            return "REFUSED: spawn_build needs a non-empty brief."
        if not runner.builder_available(context["config"]):
            return "Builder agent is not enabled on this instance."
        try:
            outcome = runner.stage_build(context, brief, say)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Builder failed: {exc}") from exc
        context["_last_merge_draft_id"] = outcome.get("merge_draft_id")
        context["_last_preview"] = outcome.get("preview")
        context["_last_change"] = outcome.get("change")
        context["_last_changed"] = outcome.get("changed")
        context["_last_action_succeeded"] = True
        return (outcome.get("reply") or "Builder finished.")[:4000]
    if name == "design_request":
        payload = dict(args)
        if context.get("_source_message_id") is not None:
            payload["source_message_id"] = context["_source_message_id"]
        try:
            request = DesignRequest.from_dict(payload)
        except (TypeError, ValueError) as exc:
            return f"REFUSED: invalid design request: {exc}"
        context["_design_request"] = request.to_dict()
        context["_last_action_succeeded"] = True
        return "Design request accepted; the host will queue the reviewable build asynchronously."
    return f"Unknown tool {name}"


def _tweakmap_block(context: dict[str, Any]) -> str:
    """Compact summary of the site's editable parameters, when the instance has
    a local clone to index and a map is available."""
    from ..hands import tweakmap

    try:
        files = tweakmap.ensure(context.get("memory"), context["config"])
        block = tweakmap.summary(files) if files else ""
    except Exception:  # noqa: BLE001 — never let the map break chat
        return ""
    if not block:
        return ""
    return ("\n\nEditable parameters (site map — current snippets; \"unique\" means "
            "the snippet appears exactly once, so it can be edited directly if "
            "you're confident, but read_file whenever you want more context):\n" + block)


def _template_tokens_block(context: dict[str, Any]) -> str:
    """The validated main page's design contract, measured and exact — a new
    page/section must match these values so the site stays consistent."""
    from ..hands import template_tokens

    clone_path = str((context["config"].get("site") or {}).get("clone_path", "")).strip()
    if not clone_path:
        return ""
    from pathlib import Path
    clone = Path(clone_path)
    if not clone.exists() or not (clone / ".git").exists():
        return ""
    try:
        block = template_tokens.cached(clone, context.get("memory"))
    except Exception:  # noqa: BLE001 — never let the tokens break chat
        return ""
    if not block:
        return ""
    return ("\n\nDesign reference — use these measured values from the sampled main "
            "page to preserve recognizable brand conventions. Adapt incidental "
            "values when needed to improve hierarchy, contrast, accessibility, "
            "depth, or responsiveness; quality rules in the design skills win:\n" + block)


def _max_work_steps(context: dict[str, Any], default: int = 8) -> int:
    """Return a bounded continuation budget for one user request."""
    try:
        configured = int((context.get("config") or {}).get("llm", {}).get("max_work_steps", default))
    except (TypeError, ValueError):
        configured = default
    return max(1, min(configured, 24))


SIDE_EFFECTS = {
    "propose_changes",
    "spawn_build",
    "create_payload_draft",
    "update_payload_draft",
    "define_editable_field",
    "set_editable_field",
    "migrate_editable_fields",
    "publish_payload_document",
    "update_payload_global",
    "publish_payload_global",
}


def _handle_message_tools(context: dict[str, Any], adapter: SiteAdapter, message: str,
                           history: list[dict[str, str]] | None, progress, persona: str,
                           source_message_id: int | None = None) -> dict[str, Any]:
    history = history or []
    say = progress or (lambda text: None)
    llm = context["llm"]
    patterns = ", ".join(_writable_patterns(context))
    inner = inner_life_context(context["memory"])
    system = (
        persona
        + ("\n\n" + inner if inner else "")
        + SYSTEM_NOTE_TOOLS.replace("%%WRITABLE%%", patterns)
        + "\n\nReference — content.json fields: " + _content_summary_cached(context, adapter)
    )
    profile = configured_site_profile_prompt(context.get("config") or {})
    if profile:
        system += "\n\n" + profile
    workspace_language = _workspace_language(message)
    if workspace_language:
        system += (
            "\n\nExplicit workspace language setting: " + workspace_language
            + ". Write the owner-facing reply in this language unless the owner explicitly requests a translation."
        )
    intake = context.get("intake_coordinator")
    if intake is not None and callable(getattr(intake, "context_prompt", None)):
        try:
            intake_context = intake.context_prompt()
        except Exception:  # noqa: BLE001 — intake context must never break editing
            intake_context = ""
        if intake_context:
            system += "\n\n" + intake_context
    system += _tweakmap_block(context)
    system += _template_tokens_block(context)
    system += _decision_ledger_block(context)
    from ..application.growth import growth_chat_context
    system += (
        "\n\nCurrent Growth workspace state (read-only platform records):\n"
        + json.dumps(growth_chat_context(context["memory"], context["config"], context), ensure_ascii=False)
        + "\nTreat provider configuration, verification, evidence availability and freshness as separate facts. "
        "Missing keyword seeds or empty search results do not mean a configured service is disconnected. "
        "Use get_metrics for persisted numbers and their timestamps. Do not describe old snapshots as live data. "
        "Use these records before asking the owner to create accounts or supply access already managed by the platform. "
        "A read-only check never authorizes provisioning, paid research or publication. "
        "Do not claim an enabled schedule or a missing consent/access setting without recorded evidence."
    )
    if _payload_gateway(context) is not None:
        system += (
            "\n\nPayload workflow: the selected workspace document is supplied in the user context. "
            "For a focused content request, inspect the explicit editable-field registry first, then "
            "use set_editable_field for a registered binding. Use define_editable_field only when Ada "
            "is creating or deliberately migrating a stable field ID; never scan source code, rendered "
            "text, or image URLs to discover fields. Payload edits remain drafts. Read the document first "
            "when broader context is needed, and use update_payload_draft only for non-visual structured "
            "document fields. Use create_payload_draft "
            "only when the owner has supplied the required facts; do not invent titles, prices, dates, "
            "or URLs. Never call publish_payload_document unless the owner explicitly asks to publish. "
            "For shared navigation or site identity, read the relevant global first and use update_payload_global; "
            "global edits remain drafts. Never call publish_payload_global unless the owner explicitly asks to publish. "
            "Broad visual requests belong on the typed design workflow instead of Payload content tools."
        )
    try:
        from .prompts import memory_context
        mem = memory_context(context["memory"], max_observations=20)
        if mem:
            system += "\n\n" + mem
    except Exception:  # noqa: BLE001 — memory context must never break chat
        pass

    convo = [{"role": "system", "content": system}, *history, {"role": "user", "content": message}]
    workspace_language = _workspace_language(message)
    if workspace_language:
        context["_workspace_language"] = workspace_language
    context.pop("_last_proposal_id", None)
    context.pop("_last_merge_draft_id", None)
    context.pop("_last_preview", None)
    context.pop("_last_change", None)
    context.pop("_last_changed", None)
    context.pop("_last_action_succeeded", None)
    context.pop("_design_request", None)
    context.pop("_read_cache", None)
    if source_message_id is not None:
        context["_source_message_id"] = source_message_id

    max_steps = _max_work_steps(context)
    for hop in range(max_steps):
        design_intent = _looks_like_design_request(message)
        tool_spec = _tools_spec(
            context,
            design_intent=design_intent,
        )
        offered_tools = {
            str(item.get("function", {}).get("name") or "")
            for item in tool_spec
            if isinstance(item, dict)
        }
        resp = llm.chat_tools(
            convo,
            tool_spec,
            temperature=0.4,
        )
        calls = resp.get("tool_calls") or []
        assistant_msg = {"role": "assistant", "content": resp.get("content")}
        if calls:
            assistant_msg["tool_calls"] = [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}}
                for c in calls
            ]
        convo.append(assistant_msg)
        if not calls:
            reply = (resp.get("content") or "").strip()
            if not reply:
                raise RuntimeError("Connection issue, try again.")
            return {
                "reply": _owner_safe_reply(reply),
                "proposal_id": context.get("_last_proposal_id"),
                "merge_draft_id": context.get("_last_merge_draft_id"),
                "preview": context.get("_last_preview"),
                "change": context.get("_last_change"),
                "changed": context.get("_last_changed"),
            }
        side_effect_calls = [c for c in calls if c["function"]["name"] in SIDE_EFFECTS]
        if side_effect_calls and len(calls) != 1:
            error = "REFUSED: send exactly one mutating tool call in a model turn; read-only calls may be batched."
            for call in calls:
                convo.append({"role": "tool", "tool_call_id": call["id"], "content": error})
            continue
        for call in calls:
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                convo.append({"role": "tool", "tool_call_id": call["id"],
                              "content": "REFUSED: tool arguments were not valid JSON."})
                continue
            name = call["function"]["name"]
            if name not in offered_tools:
                result = f"REFUSED: tool '{name}' is not available for this request. Use one of the tools offered in this turn."
                convo.append({"role": "tool", "tool_call_id": call["id"], "content": result})
                continue
            result = _execute_tool(context, adapter, name, args, say)
            convo.append({"role": "tool", "tool_call_id": call["id"], "content": result[:4000]})
            if name == "design_request" and context.get("_design_request"):
                return {
                    "reply": _owner_safe_reply(result),
                    "proposal_id": context.get("_last_proposal_id"),
                    "merge_draft_id": context.get("_last_merge_draft_id"),
                    "preview": context.get("_last_preview"),
                    "change": context.get("_last_change"),
                    "changed": context.get("_last_changed"),
                    "design_request": context["_design_request"],
                }
            if name in SIDE_EFFECTS and context.get("_last_action_succeeded"):
                return {
                    "reply": _owner_safe_reply(result),
                    "proposal_id": context.get("_last_proposal_id"),
                    "merge_draft_id": context.get("_last_merge_draft_id"),
                    "preview": context.get("_last_preview"),
                    "change": context.get("_last_change"),
                    "changed": context.get("_last_changed"),
                }
    raise RuntimeError("Connection issue, try again.")


def handle_message(
    context: dict[str, Any],
    adapter: SiteAdapter,
    message: str,
    history: list[dict[str, str]] | None = None,
    progress=None,
    source_message_id: int | None = None,
) -> dict[str, Any]:
    if not hasattr(context.get("llm"), "chat_tools"):
        raise RuntimeError("Native tool calling is required: configure llm.tool_calling with a tool-capable model.")
    return _handle_message_tools(context, adapter, message, history, progress,
                                 context.get("persona_prompt") or "",
                                 source_message_id=(
                                     source_message_id
                                     if source_message_id is not None
                                     else context.get("_source_message_id")
                                 ))
