"""Owner chat tools for Payload content and approval-gated source changes."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..hands.base import SiteAdapter
from ..core.design_contracts import DesignRequest
from ..core.contracts import safe_provider_message
from .owner_copy import owner_safe_reply as _owner_safe_reply
from .prompts import configured_site_profile_prompt, inner_life_context


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
    return match.group(1) if match else ""


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


def _writable_patterns(context: dict[str, Any]) -> list[str]:
    return [str(p) for p in ((context["config"].get("site") or {}).get("writable_patterns") or [])]


def _payload_gateway(context: dict[str, Any]):
    return context.get("payload_gateway")


def _payload_locale(payload: Any, context: dict[str, Any]) -> str:
    """Resolve every Payload read/write to one explicitly enabled tenant locale."""
    contract = context.get("_authoring_contract")
    if not isinstance(contract, dict):
        require_contract = getattr(payload, "require_authoring_contract", None)
        if not callable(require_contract):
            raise ValueError("the verified tenant Payload locale contract is unavailable")
        contract = require_contract()
        context["_authoring_contract"] = contract
    locales = contract.get("locales")
    default_locale = contract.get("defaultLocale")
    if (
        not isinstance(locales, list)
        or not locales
        or any(not isinstance(item, str) or not item for item in locales)
        or not isinstance(default_locale, str)
        or default_locale not in locales
    ):
        raise ValueError("the tenant Payload locale contract is invalid")
    requested = str(context.get("_workspace_language") or "").strip()
    if not requested:
        return default_locale
    match = next((item for item in locales if item.casefold() == requested.casefold()), None)
    if match is None:
        raise ValueError(f"the requested language '{requested}' is not enabled for this website")
    return match


def _payload_result(document: Any, *, action: str) -> str:
    if not isinstance(document, dict):
        return f"Payload {action} completed, but returned no document."
    compact = {
        key: document.get(key)
        for key in ("id", "sourceId", "slug", "title", "_status", "updatedAt")
        if key in document
    }
    revision = document.get("_helloadaRevision")
    if isinstance(revision, str) and revision:
        compact["expectedHash"] = revision
    for key in (
        "summary", "sections", "body", "featuredImage", "gallery", "author", "publishedAt",
        "modifiedAt", "category", "canonicalUrl", "seo", "siteName", "tagline", "description",
        "logo", "email", "telephone", "contactLabel", "promoText", "promoHref", "promoCta",
        "footerKicker", "footerTitle", "footerNote", "defaultSeoTitle", "defaultSeoDescription",
        "defaultSocialImage", "journalTitle", "journalDescription", "address", "items", "footer",
        "groups", "footerGroups",
    ):
        if key in document:
            compact[key] = document[key]
    rendered = json.dumps(compact, ensure_ascii=False, default=str)
    return rendered[:8000] + ("…" if len(rendered) > 8000 else "")


def _authoring_value_schema(field: dict[str, Any]) -> dict[str, Any]:
    kind = str(field.get("type") or "")
    if kind in {"text", "textarea", "email", "date", "code", "radio"}:
        schema: dict[str, Any] = {"type": "string"}
        if kind == "email":
            schema["format"] = "email"
        if kind == "date":
            schema["format"] = "date-time"
        if isinstance(field.get("maxLength"), int):
            schema["maxLength"] = int(field["maxLength"])
        if isinstance(field.get("minLength"), int):
            schema["minLength"] = int(field["minLength"])
        return schema
    if kind == "number":
        return {key: field[key] for key in ("type", "min", "max") if key in field} | {"type": "number"}
    if kind == "checkbox":
        return {"type": "boolean"}
    if kind == "select":
        options = field.get("options") if isinstance(field.get("options"), list) else []
        values = [row.get("value") if isinstance(row, dict) else row for row in options]
        if not values:
            raise ValueError(f"authoring field {field.get('name') or '(unnamed)'} has no declared select options")
        return {"type": "string", "enum": values}
    if kind in {"upload", "relationship"}:
        identity: dict[str, Any] = {"oneOf": [{"type": "string", "minLength": 1}, {"type": "integer", "minimum": 1}]}
        return {"type": "array", "items": identity} if field.get("hasMany") else identity
    if kind == "group":
        return _authoring_record_schema(field.get("fields"), nested=False, create=True)
    if kind in {"array", "blocks"}:
        if kind == "blocks":
            variants = []
            for block in field.get("blocks", []):
                if not isinstance(block, dict):
                    continue
                variants.append(_authoring_record_schema(
                    block.get("fields"),
                    nested=True,
                    block_type=str(block.get("slug") or ""),
                ))
            if not variants:
                raise ValueError(f"authoring field {field.get('name') or '(unnamed)'} has no declared blocks")
            item_schema: dict[str, Any] = {"oneOf": variants}
        else:
            item_schema = _authoring_record_schema(field.get("fields"), nested=True)
        return {
            "type": "array",
            **({"minItems": int(field["minRows"])} if isinstance(field.get("minRows"), int) else {}),
            **({"maxItems": int(field["maxRows"])} if isinstance(field.get("maxRows"), int) else {}),
            "items": item_schema,
        }
    if kind == "richText":
        return {
            "type": "object",
            "description": "Payload Lexical document: a root node with supported paragraph, heading, list, link and text children.",
            "properties": {
                "root": {
                    "type": "object",
                    "properties": {
                        "type": {"const": "root"},
                        "version": {"type": "integer"},
                        "format": {"type": "string"},
                        "indent": {"type": "integer"},
                        "direction": {"type": ["string", "null"]},
                        "children": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["type", "children"],
                    "additionalProperties": False,
                },
                "version": {"type": ["string", "integer"]},
            },
            "required": ["root"],
            "additionalProperties": False,
        }
    if kind == "json":
        return {"description": "JSON data; the host validates every nested value before writing."}
    raise ValueError(f"authoring field {field.get('name') or '(unnamed)'} uses unsupported Payload type {kind or '(empty)'}")


def _authoring_record_schema(
    raw_fields: Any,
    *,
    nested: bool,
    block_type: str = "",
    create: bool = False,
) -> dict[str, Any]:
    fields = raw_fields if isinstance(raw_fields, list) else []
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in fields:
        if not isinstance(field, dict) or not str(field.get("name") or "").strip():
            continue
        name = str(field["name"])
        properties[name] = _authoring_value_schema(field)
        if (create or nested) and field.get("required") is True:
            required.append(name)
    if nested:
        properties["id"] = {"oneOf": [{"type": "string"}, {"type": "integer", "minimum": 1}]}
    if block_type:
        properties["blockType"] = {"const": block_type}
        required.append("blockType")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _validate_website_change_plan(
    value: Any,
    authoring_contract: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("the website change plan must be an object")
    content_effects = value.get("content_effects")
    source_brief = str(value.get("source_brief") or "").strip()
    response_only = value.get("response_only") is True
    if not isinstance(content_effects, list) or len(content_effects) > 12:
        raise ValueError("content_effects must be a list of at most twelve changes")
    if response_only:
        if content_effects or source_brief:
            raise ValueError("a response-only plan cannot include website changes")
        return {"content_effects": [], "source_brief": "", "response_only": True}
    if not content_effects and not source_brief:
        raise ValueError("the plan has no content or presentation change")
    if len(source_brief) > 3_000:
        raise ValueError("source_brief is too long")
    source_paths = value.get('source_paths', [])
    source_kind = value.get('source_kind', 'presentation')
    acceptance = value.get('acceptance_criteria', [])
    business_facts = value.get('business_facts', [])
    if source_kind not in ('maintenance', 'presentation'):
        raise ValueError('source_kind must be maintenance or presentation')
    if any(not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items)
           for items in (acceptance, business_facts)):
        raise ValueError('acceptance_criteria and business_facts must contain explicit text facts or requirements')
    if not isinstance(source_paths, list) or any(not isinstance(path, str) for path in source_paths):
        raise ValueError('source_paths must be a list of exact relative file paths')
    if source_brief and (config or {}).get('design_engine', {}).get('build_profile') == 'next_react':
        from ..hands.repo_changes import normalize_path, source_path_allowed

        if not source_paths:
            raise ValueError('source work must declare source_paths before builder execution')
        if not acceptance:
            raise ValueError('source work must declare acceptance_criteria before builder execution')
        refused = [path for path in source_paths if normalize_path(path) != path
                   or any(char in path for char in '*?') or not source_path_allowed(config, path)]
        if refused:
            raise ValueError('source scope is outside tenant ownership: ' + ', '.join(refused)
                             + '. Use Payload for supported content/SEO fields; platform source needs a shared Site-Agent release.')
    if content_effects and not isinstance(authoring_contract, dict):
        raise ValueError("the canonical Payload authoring contract is unavailable")
    authoring = (authoring_contract or {}).get("authoring") or {}
    enabled = (authoring_contract or {}).get("enabled") or {}
    planned: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(content_effects):
        if not isinstance(raw, dict):
            raise ValueError(f"content_effects[{index}] must be an object")
        allowed_keys = {
            "kind", "operation", "collection", "global", "identifier",
            "identifier_kind", "fields", "summary",
        }
        unknown_keys = sorted(set(raw) - allowed_keys)
        if unknown_keys:
            raise ValueError(f"content_effects[{index}] contains unsupported plan fields: {', '.join(unknown_keys)}")
        kind = str(raw.get("kind") or "").strip()
        operation = str(raw.get("operation") or "").strip()
        collection = str(raw.get("collection") or "").strip()
        global_name = str(raw.get("global") or "").strip()
        identifier = str(raw.get("identifier") or "").strip()
        identifier_kind = str(raw.get("identifier_kind") or "").strip()
        summary = str(raw.get("summary") or "").strip()
        fields = raw.get("fields")
        if kind not in {"collection", "global"} or operation not in {"create", "update"}:
            raise ValueError(f"content_effects[{index}] needs a supported target and operation")
        if not isinstance(fields, list) or not fields or any(not isinstance(item, str) or not item.strip() for item in fields):
            raise ValueError(f"content_effects[{index}].fields must name at least one top-level authoring field")
        if len(set(fields)) != len(fields):
            raise ValueError(f"content_effects[{index}].fields cannot contain duplicates")
        if not summary or len(summary) > 600:
            raise ValueError(f"content_effects[{index}].summary must briefly explain the requested content change")
        if kind == "collection":
            if collection not in (enabled.get("collections") or []) or global_name:
                raise ValueError(f"content_effects[{index}] targets a collection that is not enabled")
            schema_fields = (authoring.get("collections") or {}).get(collection)
            target = collection
            if operation == "create" and (collection not in {"pages", "posts", "products"} or identifier_kind != "slug"):
                raise ValueError("collection creates must target a page, post, or product route slug")
            if operation == "create" and not identifier:
                raise ValueError("collection creates need their intended route slug as the exact identity")
        else:
            if global_name not in (enabled.get("globals") or []) or collection or operation != "update":
                raise ValueError(f"content_effects[{index}] targets an unsupported shared global operation")
            schema_fields = (authoring.get("globals") or {}).get(global_name)
            target = global_name
        names = {
            str(field.get("name") or "")
            for field in schema_fields or []
            if isinstance(field, dict)
        }
        unknown = sorted(set(fields) - names)
        if unknown:
            raise ValueError(f"content_effects[{index}] includes fields outside the shared schema: {', '.join(unknown)}")
        if operation == "create":
            required = {str(field.get("name")) for field in schema_fields or []
                        if isinstance(field, dict) and field.get("required") is True}
            missing = sorted(required - set(fields))
            if missing:
                raise ValueError("creation plan is missing required authoring fields: " + ", ".join(missing))
        if operation == "update" and not identifier:
            raise ValueError(f"content_effects[{index}] updates need an exact document/global identity")
        if operation == "update" and kind == "collection" and identifier_kind not in {"id", "sourceId", "slug"}:
            raise ValueError(f"content_effects[{index}] updates need an exact document identity")
        if kind == "global" and (identifier_kind != "global" or identifier != global_name):
            raise ValueError(f"content_effects[{index}] must identify the exact global by name")
        if kind == "collection" and operation == "create" and "slug" not in fields:
            raise ValueError("idempotent content creation must include the route slug")
        identity = (kind, target, identifier if operation == "update" else "create")
        if identity in identities:
            raise ValueError("the plan contains duplicate content targets")
        identities.add(identity)
        planned.append({
            "kind": kind,
            "operation": operation,
            "target": target,
            "collection": collection,
            "global": global_name,
            "identifier": identifier,
            "identifier_kind": identifier_kind,
            "fields": sorted(fields),
            "summary": summary,
            "completed_fields": [],
        })
    return {"content_effects": planned, "source_brief": source_brief, "source_paths": source_paths,
            "source_kind": source_kind, "acceptance_criteria": acceptance, "business_facts": business_facts,
            "response_only": False}


def _payload_plan_complete(context: dict[str, Any]) -> bool:
    plan = context.get("_website_change_plan")
    if not isinstance(plan, dict):
        return False
    return all(
        set(effect.get("fields") or []).issubset(set(effect.get("completed_fields") or []))
        for effect in plan.get("content_effects") or []
    )


def _plan_effect_for_tool(context: dict[str, Any], name: str, args: dict[str, Any]) -> dict[str, Any]:
    plan = context.get("_website_change_plan")
    if not isinstance(plan, dict) or plan.get("response_only"):
        raise ValueError("a validated website change plan is required before making this change")
    data = args.get("data") if isinstance(args.get("data"), dict) else {}
    if name == "create_payload_draft":
        collection = str(args.get("collection") or "")
        operation = "create"
        identifier = str(data.get("slug") or "")
        identifier_kind = "slug"
        kind = "collection"
    elif name == "update_payload_draft":
        collection = str(args.get("collection") or "")
        operation = "update"
        identifier = str(args.get("id") or "")
        identifier_kind = "id"
        kind = "collection"
    elif name == "update_payload_global":
        collection = ""
        operation = "update"
        identifier = str(args.get("global") or "")
        identifier_kind = "global"
        kind = "global"
    else:
        raise ValueError("this tool is not a planned Payload mutation")

    candidates = []
    reads = context.get("_payload_read_documents") or {}
    globals_read = context.get("_payload_read_globals") or {}
    for effect in plan.get("content_effects", []):
        if not isinstance(effect, dict) or effect.get("kind") != kind or effect.get("operation") != operation:
            continue
        if effect.get("target") != (collection or identifier):
            continue
        if operation == "create":
            matches = effect.get("identifier") == identifier and effect.get("identifier_kind") == identifier_kind
        elif kind == "global":
            matches = effect.get("identifier") == identifier and effect.get("identifier_kind") == identifier_kind
        else:
            document = reads.get((collection, identifier)) if isinstance(reads, dict) else None
            locator = str(effect.get("identifier_kind") or "")
            matches = isinstance(document, dict) and str(document.get(locator) or "") == str(effect.get("identifier") or "")
        if matches:
            candidates.append(effect)
    if len(candidates) != 1:
        raise ValueError("the Payload change does not match one exact target in Ada's validated plan")
    effect = candidates[0]
    planned_fields = set(effect.get("fields") or [])
    if set(data) != planned_fields:
        missing_fields = sorted(planned_fields - set(data))
        unexpected_fields = sorted(set(data) - planned_fields)
        raise ValueError(
            "the Payload fields must exactly match the validated plan "
            f"(missing planned fields: {', '.join(missing_fields) or '(none)'}; "
            f"unexpected data fields: {', '.join(unexpected_fields) or '(none)'})"
        )
    if effect.get("completed_fields"):
        raise ValueError("this planned Payload effect has already been applied")

    if name == "update_payload_draft":
        document = reads.get((collection, identifier)) if isinstance(reads, dict) else None
        if not isinstance(document, dict):
            raise ValueError("read the exact Payload document in this request before updating it")
        locator_key = str(effect.get("identifier_kind") or "")
        if str(document.get(locator_key) or "") != str(effect.get("identifier") or ""):
            raise ValueError("the update target differs from the exact document in Ada's plan")
        if str(args.get("expected_hash") or "") != str(document.get("_helloadaRevision") or ""):
            raise ValueError("the update revision is not the exact revision read for this target")
    elif name == "update_payload_global":
        document = globals_read.get(identifier) if isinstance(globals_read, dict) else None
        if not isinstance(document, dict):
            raise ValueError("read the exact Payload global in this request before updating it")
        if str(args.get("expected_hash") or "") != str(document.get("_helloadaRevision") or ""):
            raise ValueError("the global revision is not the exact revision read for this target")
    return effect


def _record_payload_effect(context: dict[str, Any], effect: dict[str, Any], document: Any) -> None:
    if not isinstance(document, dict):
        raise RuntimeError("Payload write returned no exact document receipt")
    revision = str(document.get("_helloadaRevision") or "")
    document_id = str(document.get("id") or (effect.get("target") if effect.get("kind") == "global" else "") or "")
    if not revision.startswith("sha256:") or not document_id:
        raise RuntimeError("Payload write returned no exact document identity and revision")
    fields = list(effect.get("fields") or [])
    effect["completed_fields"] = fields
    receipt = {
        "kind": effect.get("kind"),
        "operation": effect.get("operation"),
        "target": effect.get("target"),
        "document_id": document_id,
        "revision": revision,
        "locale": str(context.get("_resolved_payload_locale") or ""),
        "fields": fields,
        "summary": effect.get("summary"),
    }
    context.setdefault("_completed_payload_effects", []).append(receipt)
    context["_last_payload_effect"] = receipt
    memory = context.get("memory")
    job_id = context.get("_chat_job_id")
    worker = context.get("_chat_job_worker")
    if memory is not None and job_id is not None and worker and hasattr(memory, "record_chat_job_effect"):
        if not memory.record_chat_job_effect(int(job_id), str(worker), receipt):
            raise RuntimeError("Payload draft is saved, but its chat-job receipt could not be persisted")


def _tools_spec(
    context: dict[str, Any],
    *,
    design_intent: bool = False,
    source_edit_intent: bool = False,
    authoring_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # ``source_edit_intent`` is retained as a compatibility argument for
    # callers that still pass the old classifier result.  Capability, not
    # English wording, decides whether a source mutation is a builder job.
    from ..hands import opencode_runner as _runner

    cfg = context.get("config") if isinstance(context.get("config"), dict) else context
    source_builder_available = _runner.builder_available(cfg)
    canonical_design_handoff = design_intent and context.get("design_service") is not None and not source_builder_available
    use_existing_builder = source_builder_available

    def fn(name, desc, props, required=None):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {"type": "object", "properties": props, "required": required or []},
            },
        }

    def raw_fn(name: str, desc: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if parameters.get("type") != "object":
            raise ValueError(f"OpenAI function tool {name} must declare an object root schema")
        return {"type": "function", "function": {"name": name, "description": desc, "parameters": parameters}}

    tools = [
        fn("read_file", "Read a file from the site repo. For big files pass "
           "'contains' with a distinctive substring (e.g. 'footer') to jump straight "
           "to that region instead of getting the head of the file.",
           {"path": {"type": "string"},
            "contains": {"type": "string", "description": "substring to locate"}}, ["path"]),
        fn("list_files", "List every file path in the site repo", {}),
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
    can_author_payload = _payload_gateway(context) is not None and isinstance(authoring_contract, dict)
    if source_builder_available or can_author_payload:
        enabled = (authoring_contract or {}).get("enabled") or {}
        authoring = (authoring_contract or {}).get("authoring") or {}
        effect_variants: list[dict[str, Any]] = []
        for name in enabled.get("collections", []):
            fields = authoring.get("collections", {}).get(name, [])
            names = [str(field.get("name")) for field in fields if isinstance(field, dict) and field.get("name")]
            for operation in ("create", "update"):
                identifier_kinds = ["slug"] if operation == "create" else ["id", "sourceId", "slug"]
                effect_variants.append({
                    "type": "object",
                    "properties": {
                        "kind": {"const": "collection"},
                        "operation": {"const": operation},
                        "collection": {"const": name},
                        "identifier": {"type": "string", "minLength": 1},
                        "identifier_kind": {"type": "string", "enum": identifier_kinds},
                        "fields": {"type": "array", "items": {"type": "string", "enum": names}, "minItems": 1, "uniqueItems": True},
                        "summary": {"type": "string", "minLength": 1, "maxLength": 600},
                    },
                    "required": ["kind", "operation", "collection", "identifier", "identifier_kind", "fields", "summary"],
                    "additionalProperties": False,
                })
        for name in enabled.get("globals", []):
            fields = authoring.get("globals", {}).get(name, [])
            names = [str(field.get("name")) for field in fields if isinstance(field, dict) and field.get("name")]
            effect_variants.append({
                "type": "object",
                "properties": {
                    "kind": {"const": "global"},
                    "operation": {"const": "update"},
                    "global": {"const": name},
                    "identifier": {"const": name},
                    "identifier_kind": {"const": "global"},
                    "fields": {"type": "array", "items": {"type": "string", "enum": names}, "minItems": 1, "uniqueItems": True},
                    "summary": {"type": "string", "minLength": 1, "maxLength": 600},
                },
                "required": ["kind", "operation", "global", "identifier", "identifier_kind", "fields", "summary"],
                "additionalProperties": False,
            })
        plan_properties: dict[str, Any] = {
            "content_effects": {"type": "array", "items": {"oneOf": effect_variants} if effect_variants else {"not": {}}, "maxItems": 12},
            "source_brief": {"type": "string", "maxLength": 3000},
            "source_paths": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
            "source_kind": {"type": "string", "enum": ["maintenance", "presentation"]},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            "business_facts": {"type": "array", "items": {"type": "string"}},
            "response_only": {"type": "boolean"},
        }
        tools.append(raw_fn(
            "plan_website_change",
            "Declare the exact work before any Payload or source mutation. Use response_only for an answer without changes. "
            "Payload effects must identify exact shared-schema fields and targets; source_brief describes only presentation/code work. "
            "For source work, declare the exact source_paths allowed by the source ownership contract before delegation. "
            "Include acceptance_criteria and only business_facts relevant to this task. Choose maintenance for focused engineering or presentation for visual composition requiring the design skills. "
            "The host validates this plan and requires Payload drafts to be saved before source work.",
            {
                "type": "object",
                "properties": plan_properties,
                "required": ["content_effects", "source_brief", "response_only"],
                "additionalProperties": False,
            },
        ))
    if _payload_gateway(context) is not None and isinstance(authoring_contract, dict):
        authoring = authoring_contract.get("authoring") or {}
        enabled = authoring_contract.get("enabled") or {}
        collection_names = [
            name for name in enabled.get("collections", [])
            if isinstance(name, str) and isinstance((authoring.get("collections") or {}).get(name), list)
        ]
        global_names = [
            name for name in enabled.get("globals", [])
            if isinstance(name, str) and isinstance((authoring.get("globals") or {}).get(name), list)
        ]
        collection = {"type": "string", "enum": collection_names}
        payload_global = {"type": "string", "enum": global_names}
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
         ])
        create_variants = []
        update_variants = []
        for name in collection_names:
            fields = authoring["collections"][name]
            create_variants.append({
                "type": "object",
                "properties": {
                    "collection": {"const": name},
                    "data": _authoring_record_schema(fields, nested=False, create=True),
                },
                "required": ["collection", "data"],
                "additionalProperties": False,
            })
            update_variants.append({
                "type": "object",
                "properties": {
                    "collection": {"const": name},
                    "id": {"type": "string", "minLength": 1},
                    "expected_hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                    "data": _authoring_record_schema(fields, nested=False),
                },
                "required": ["collection", "id", "expected_hash", "data"],
                "additionalProperties": False,
            })
        if create_variants:
            tools.append(raw_fn(
                "create_payload_draft",
                "Create a schema-valid Payload draft. Required fields follow the selected document type; never invent business facts.",
                {"type": "object", "oneOf": create_variants},
            ))
        if update_variants:
            tools.append(raw_fn(
                "update_payload_draft",
                "Update only requested fields on an existing Payload draft. Read the document first and pass its exact expectedHash. Never publish as part of this tool.",
                {"type": "object", "oneOf": update_variants},
            ))
        tools.append(fn(
            "read_payload_global",
            "Read one shared Payload global. Use this before changing navigation, footer, or site-wide settings.",
            {"global": payload_global, "draft": {"type": "boolean"}},
            ["global"],
        ))
        global_update_variants = []
        for name in global_names:
            global_update_variants.append({
                "type": "object",
                "properties": {
                    "global": {"const": name},
                    "expected_hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                    "data": _authoring_record_schema(authoring["globals"][name], nested=False),
                },
                "required": ["global", "expected_hash", "data"],
                "additionalProperties": False,
            })
        if global_update_variants:
            tools.append(raw_fn(
                "update_payload_global",
                "Update selected fields on a shared Payload global draft. Read it first and pass its exact expectedHash. Never publish as part of this tool.",
                {"type": "object", "oneOf": global_update_variants},
            ))
        booking_type_id = {"type": "string", "pattern": "^ha_booking_[a-f0-9]{32}$"}
        booking_hours = {
            "type": "array", "maxItems": 84,
            "items": {
                "type": "object",
                "properties": {
                    "day": {"type": "integer", "minimum": 0, "maximum": 6},
                    "startTime": {"type": "string", "pattern": "^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"},
                    "endTime": {"type": "string", "pattern": "^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"},
                },
                "required": ["day", "startTime", "endTime"],
                "additionalProperties": False,
            },
        }
        booking_tools = [
            ("read_booking_configuration", "Read authoritative booking settings and all active/inactive booking types.", {}, []),
            ("read_booking_availability", "Read bounded available slots for one booking type and local business date. Never exposes other calendar details.", {
                "booking_type_id": booking_type_id, "date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
            }, ["booking_type_id", "date"]),
            ("create_booking_type", "Create a business appointment type only with owner-provided name and duration. Returns its immutable ID for the Payload booking block.", {
                "name": {"type": "string", "minLength": 1, "maxLength": 120},
                "duration_minutes": {"type": "integer", "minimum": 10, "maximum": 480, "multipleOf": 5},
                "description": {"type": "string", "maxLength": 2000},
            }, ["name", "duration_minutes"]),
            ("update_booking_type", "Update a booking type after reading it. Keep its immutable ID and include the current integer revision.", {
                "id": booking_type_id, "expected_revision": {"type": "integer", "minimum": 1},
                "name": {"type": "string", "minLength": 1, "maxLength": 120},
                "duration_minutes": {"type": "integer", "minimum": 10, "maximum": 480, "multipleOf": 5},
                "description": {"type": "string", "maxLength": 2000},
            }, ["id", "expected_revision", "name", "duration_minutes", "description"]),
            ("deactivate_booking_type", "Deactivate a booking type without deleting its identity. Read it first and include expectedUpdatedAt.", {
                "id": booking_type_id, "expected_revision": {"type": "integer", "minimum": 1},
            }, ["id", "expected_revision"]),
            ("update_booking_settings", "Update business-wide timezone, weekly hours, notice, horizon, enabled state and simultaneous capacity. Read the current revision first and preserve unchanged settings.", {
                "settings": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "timeZone": {"type": "string", "maxLength": 80},
                        "weeklyAvailability": booking_hours,
                        "maxConcurrentAppointments": {"type": "integer", "minimum": 1, "maximum": 50},
                        "minimumNoticeHours": {"type": "integer", "minimum": 0, "maximum": 8760},
                        "bookingWindowDays": {"type": "integer", "minimum": 1, "maximum": 365},
                        "expectedRevision": {"type": "integer", "minimum": 1},
                    },
                    "required": ["enabled", "timeZone", "weeklyAvailability", "maxConcurrentAppointments", "minimumNoticeHours", "bookingWindowDays", "expectedRevision"],
                    "additionalProperties": False,
                },
            }, ["settings"]),
        ]
        for tool_name, description, properties, required in booking_tools:
            tools.append(raw_fn(tool_name, description, {
                "type": "object", "properties": properties, "required": required, "additionalProperties": False,
            }))
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
        "typed design handoff for an existing source workspace. The typed design handoff is only for a "
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
    context.pop("_last_action_succeeded", None)
    context.pop("_last_payload_effect", None)
    phrase = {
        "read_file": lambda: f"reading {args.get('path', '')}",
        "list_files": lambda: "listing repository files",
        "get_metrics": lambda: "reading saved analytics and search evidence",
        "get_growth": lambda: "checking growth connections and approvals",
        "list_drafts": lambda: "checking pending drafts",
        "recall_memory": lambda: "searching my memory",
        "search_media": lambda: "searching the Library",
        "search_business_knowledge": lambda: "searching approved business knowledge",
        "spawn_build": lambda: "briefing the builder agent",
        "design_request": lambda: "preparing the typed design handoff",
         "read_payload_content": lambda: "reading the selected Payload document",
        "create_payload_draft": lambda: "creating a Payload draft",
        "update_payload_draft": lambda: "updating the Payload draft",
        "read_payload_global": lambda: "reading the shared Payload global",
        "update_payload_global": lambda: "updating the shared Payload global draft",
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
                    else "the canonical source build is unavailable; do not stage an unbuilt edit"
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
    booking_tool_names = {
        "read_booking_configuration", "read_booking_availability", "create_booking_type",
        "update_booking_type", "deactivate_booking_type", "update_booking_settings",
    }
    if name in booking_tool_names:
        payload = _payload_gateway(context)
        if payload is None:
            return "The tenant booking service is not configured."
        try:
            if name == "read_booking_configuration":
                result = payload.read_booking_configuration()
            elif name == "read_booking_availability":
                result = payload.read_booking_availability(str(args.get("booking_type_id") or ""), str(args.get("date") or ""))
            elif name == "create_booking_type":
                result = payload.create_booking_type(
                    name=str(args.get("name") or ""), duration_minutes=int(args.get("duration_minutes") or 0),
                    description=str(args.get("description") or ""),
                )
                context["_last_action_succeeded"] = True
            elif name == "update_booking_type":
                result = payload.update_booking_type(
                    type_id=str(args.get("id") or ""), expected_revision=int(args.get("expected_revision") or 0),
                    name=str(args.get("name") or ""), duration_minutes=int(args.get("duration_minutes") or 0),
                    description=str(args.get("description") or ""),
                )
                context["_last_action_succeeded"] = True
            elif name == "deactivate_booking_type":
                result = payload.deactivate_booking_type(
                    type_id=str(args.get("id") or ""), expected_revision=int(args.get("expected_revision") or 0),
                )
                context["_last_action_succeeded"] = True
            else:
                result = payload.update_booking_settings(args.get("settings") or {})
                context["_last_action_succeeded"] = True
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 — explain service failures to Ada
            return f"Booking service action failed: {str(exc)[:400]}"
    if name == "plan_website_change":
        if context.get("_website_change_plan") is not None:
            return "REFUSED: this request already has a validated plan; do not replace it after effects begin."
        try:
            plan = _validate_website_change_plan(args, context.get("_authoring_contract"), context["config"])
        except (TypeError, ValueError) as exc:
            return f"REFUSED: the website change plan is invalid: {exc}"
        context["_website_change_plan"] = plan
        context["_last_action_succeeded"] = True
        return "Validated website change plan: " + json.dumps(plan, ensure_ascii=False)
    if name in {
        "read_payload_content", "create_payload_draft", "update_payload_draft",
        "read_payload_global", "update_payload_global",
    }:
        payload = _payload_gateway(context)
        if payload is None:
            return "Payload content editing is not configured on this site-agent instance."
        try:
            locale = _payload_locale(payload, context)
            context["_resolved_payload_locale"] = locale
            if name == "read_payload_content":
                read_kwargs = {
                    "identifier": str(args.get("identifier") or ""),
                    "identifier_kind": str(args.get("identifier_kind") or "sourceId"),
                    "draft": bool(args.get("draft", True)),
                }
                read_kwargs["locale"] = locale
                document = payload.read(
                    str(args.get("collection") or ""),
                    **read_kwargs,
                )
                if isinstance(document, dict):
                    reads = context.setdefault("_payload_read_documents", {})
                    for key in ("id", "sourceId", "slug"):
                        value = str(document.get(key) or "").strip()
                        if value:
                            reads[(str(args.get("collection") or ""), value)] = document
                return _payload_result(document, action="read")
            if name == "read_payload_global":
                read_kwargs = {"draft": bool(args.get("draft", True))}
                read_kwargs["locale"] = locale
                document = payload.read_global(str(args.get("global") or ""), **read_kwargs)
                if isinstance(document, dict):
                    context.setdefault("_payload_read_globals", {})[str(args.get("global") or "")] = document
                return _payload_result(document, action="read")
            if name == "create_payload_draft":
                effect = _plan_effect_for_tool(context, name, args)
                write_kwargs = {"locale": locale}
                document = payload.create(str(args.get("collection") or ""), args.get("data") or {}, **write_kwargs)
                _record_payload_effect(context, effect, document)
                context["_last_action_succeeded"] = True
                return f"Payload draft created: {_payload_result(document, action='write')}"
            if name == "update_payload_draft":
                effect = _plan_effect_for_tool(context, name, args)
                write_kwargs = {"locale": locale}
                document = payload.update(
                    str(args.get("collection") or ""),
                    str(args.get("id") or ""),
                    args.get("data") or {},
                    expected_hash=str(args.get("expected_hash") or ""),
                    **write_kwargs,
                )
                _record_payload_effect(context, effect, document)
                context["_last_action_succeeded"] = True
                return f"Payload draft updated: {_payload_result(document, action='write')}"
            if name == "update_payload_global":
                effect = _plan_effect_for_tool(context, name, args)
                write_kwargs = {"locale": locale}
                document = payload.update_global(
                    str(args.get("global") or ""), args.get("data") or {},
                    expected_hash=str(args.get("expected_hash") or ""), **write_kwargs,
                )
                _record_payload_effect(context, effect, document)
                context["_last_action_succeeded"] = True
                return f"Payload global draft updated: {_payload_result(document, action='write')}"
            return "REFUSED: unknown Payload action."
        except Exception as exc:  # noqa: BLE001 — a tool failure should be explained to Ada
            logging.getLogger(__name__).warning(
                "payload_tool_failed tenant=%s job=%s tool=%s reason=%s",
                context.get("tenant_id"), context.get("_chat_job_id"), name,
                safe_provider_message(str(exc), max_chars=500),
            )
            return f"REFUSED: Payload content action failed: {str(exc)[:500]}"
    if name == "spawn_build":
        from ..hands import opencode_runner as runner
        brief = str(args.get("brief", "")).strip()
        if not brief:
            return "REFUSED: spawn_build needs a non-empty brief."
        plan = context.get("_website_change_plan")
        if not isinstance(plan, dict) or plan.get("response_only") or not str(plan.get("source_brief") or "").strip():
            return "REFUSED: source work requires a validated presentation brief in the website change plan."
        if not _payload_plan_complete(context):
            return "REFUSED: complete every planned Payload draft and verify its receipt before starting source work."
        if not runner.builder_available(context["config"]):
            return "Builder agent is not enabled on this instance."
        payload_receipts = context.get("_completed_payload_effects") or []
        authoritative_brief = str(plan["source_brief"]).strip()
        from ..hands.repo_changes import source_authoring_contract
        execution_context = '\n\nSource ownership contract:\n' + json.dumps(source_authoring_contract(context['config']))
        execution_context += '\n\nPlanned source files:\n' + json.dumps(plan.get('source_paths', []))
        if payload_receipts:
            execution_context += (
                "\n\nExact Payload drafts saved before this source task (these are the content authority; do not copy their values into source):\n"
                + json.dumps(payload_receipts, ensure_ascii=False, sort_keys=True)
            )
        try:
            outcome = runner.stage_build(context, authoritative_brief + execution_context, say)
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
    "plan_website_change",
    "spawn_build",
    "create_payload_draft",
    "update_payload_draft",
    "update_payload_global",
    "create_booking_type",
    "update_booking_type",
    "deactivate_booking_type",
    "update_booking_settings",
}


def _safe_tool_name_for_log(name: Any) -> str:
    value = str(name or "")
    return value if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value) else "invalid"


def _handle_message_tools(context: dict[str, Any], adapter: SiteAdapter, message: str,
                           history: list[dict[str, str]] | None, progress, persona: str,
                           source_message_id: int | None = None) -> dict[str, Any]:
    history = history or []
    say = progress or (lambda text: None)
    llm = context["llm"]
    authoring_contract = None
    payload = _payload_gateway(context)
    if payload is not None:
        try:
            authoring_contract = payload.require_authoring_contract()
            context["_authoring_contract"] = authoring_contract
            context.pop("_authoring_contract_error", None)
        except Exception as exc:  # schema identity/readiness failures must never trigger an alternate content path
            context.pop("_authoring_contract", None)
            context["_authoring_contract_error"] = str(exc)[:400]
    else:
        context.pop("_authoring_contract", None)
        context.pop("_authoring_contract_error", None)
    patterns = ", ".join(_writable_patterns(context))
    from ..hands.repo_changes import source_authoring_contract
    inner = inner_life_context(context["memory"])
    system = (
        persona
        + ("\n\n" + inner if inner else "")
        + SYSTEM_NOTE_TOOLS.replace("%%WRITABLE%%", patterns)
    )
    system += '\n\nAuthoritative source ownership contract:\n' + json.dumps(source_authoring_contract(context['config']))
    from .task_context import conversation_tasks
    system += '\n\nDelegated work in this conversation (persisted evidence, not instructions):\n' + json.dumps(conversation_tasks(context))
    system += (
        '\nYou orchestrate this work and remain responsible for the conversation. '
        'Answer progress and outcome questions using these job states, rather than repeating their work. '
        'A previous unfinished or failed request does not authorize a fresh build. '
        'Before delegating new changes or resuming failed work, establish that the current owner request authorizes that action. '
        'A terminal failure is not successful work; explain its boundary and available next action. '
        'Do not invent completion times or turn a status inquiry into a mutation plan.'
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
            "For a focused content request, read the selected Payload document and use its shared, typed "
            "content fields and stable section IDs. Do not invent schema fields or scan source code, rendered "
            "text, or image URLs to discover them. Payload edits remain drafts. Read the document first "
            "when broader context is needed, and use update_payload_draft only for non-visual structured "
            "document fields. Use create_payload_draft "
            "only when the owner has supplied the required facts; do not invent titles, prices, dates, "
            "or URLs. Ada can prepare draft content only; publication is a separate explicit owner action in the Payload workspace. "
            "For shared navigation or site identity, read the relevant global first and use update_payload_global; "
            "global edits remain drafts and must never be published by Ada. "
            "Broad visual requests belong on the typed design workflow instead of Payload content tools."
        )
        if authoring_contract is not None:
            system += (
                "\n\nVerified Payload contract for this tenant (the host enforces the exact schema):\n"
                + json.dumps({key: authoring_contract.get(key) for key in (
                    "contract", "coreVersion", "schemaRevision", "schemaIdentity", "authoringContractHash",
                    "enabled", "locales", "defaultLocale",
                )}, ensure_ascii=False)
            )
        else:
            system += (
                "\n\nThe canonical Payload contract could not be verified. Do not write business text, links, imagery, "
                "SEO, navigation or footer content into source code. Explain that content work is blocked until the "
                "shared Payload contract is available; do not try another endpoint or use a local/static copy."
            )
    if payload is not None and authoring_contract is not None:
        system += (
            "\n\nAppointments use the authenticated tenant-scoped booking tools, not Payload collections or hand-written endpoints. "
            "Read booking configuration before changing it. Never invent service duration, working hours, timezone, capacity, or availability. "
            "For an explicit owner request, make only the requested configuration change using its current revision. "
            "If a request proposes a booking form, reuse an existing type when clearly appropriate; if the type or duration is ambiguous, ask one concise question. "
            "Create new types only from owner-provided details, then bind the Payload helloAdaBooking block's bookingTypeId to the returned immutable ID. "
            "Keep booking schema, availability, persistence, and notifications in the shared service; do not create parallel stores or endpoints."
        )
    system += (
        "\n\nMutation protocol: before any Payload or source change, call plan_website_change exactly once. "
        "Declare every requested Payload target and exact top-level field, plus any source presentation brief. "
        "Read the exact Payload document/global and revision before updating it. The host refuses unplanned fields, "
        "targets, and source work before required Payload drafts are saved. A response_only plan is for read-only answers."
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
    else:
        context.pop("_workspace_language", None)
    context.pop("_last_proposal_id", None)
    context.pop("_last_merge_draft_id", None)
    context.pop("_last_preview", None)
    context.pop("_last_change", None)
    context.pop("_last_changed", None)
    context.pop("_last_action_succeeded", None)
    context.pop("_design_request", None)
    context.pop("_read_cache", None)
    context.pop("_website_change_plan", None)
    context.pop("_completed_payload_effects", None)
    context.pop("_resolved_payload_locale", None)
    context.pop("_payload_read_documents", None)
    context.pop("_payload_read_globals", None)
    context.pop("_source_build_completed", None)
    if source_message_id is not None:
        context["_source_message_id"] = source_message_id

    max_steps = _max_work_steps(context)
    for hop in range(max_steps):
        design_intent = _looks_like_design_request(message)
        tool_spec = _tools_spec(
            context,
            design_intent=design_intent,
            authoring_contract=authoring_contract,
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
            plan = context.get("_website_change_plan")
            if isinstance(plan, dict) and not plan.get("response_only"):
                unfinished = [
                    effect for effect in plan.get("content_effects", [])
                    if not set(effect.get("fields") or []).issubset(set(effect.get("completed_fields") or []))
                ]
                source_pending = bool(str(plan.get("source_brief") or "").strip()) and not context.get("_source_build_completed")
                if unfinished or source_pending:
                    logging.getLogger(__name__).warning(
                        "editor_tool_loop_refused tenant=%s job=%s code=incomplete_plan_without_tool_calls "
                        "tool_names=none tool_count=0 pending_effect_count=%d pending_source_build_count=%d "
                        "step=%d step_limit=%d",
                        context.get("tenant_id"), context.get("_chat_job_id"), len(unfinished),
                        int(source_pending), hop + 1, max_steps,
                    )
                    pending = []
                    if unfinished:
                        pending.append(f"{len(unfinished)} planned Payload effect(s) are incomplete")
                    if source_pending:
                        pending.append("the planned source build has not been staged")
                    convo.append({
                        "role": "system",
                        "content": "Do not give a completion response yet: " + "; ".join(pending)
                        + ". Continue only with the exact remaining effects in the validated plan. If blocked, explain the concrete blocker and do not claim completion.",
                    })
                    continue
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
            tool_names = ",".join(sorted(
                _safe_tool_name_for_log(call["function"]["name"]) for call in calls
            ))
            logging.getLogger(__name__).warning(
                "editor_tool_loop_refused tenant=%s job=%s code=mixed_side_effect_batch "
                "tool_names=%s tool_count=%d side_effect_count=%d",
                context.get("tenant_id"), context.get("_chat_job_id"), tool_names,
                len(calls), len(side_effect_calls),
            )
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
                logging.getLogger(__name__).warning(
                    "editor_tool_loop_refused tenant=%s job=%s code=unoffered_tool "
                    "tool_names=%s tool_count=1",
                    context.get("tenant_id"), context.get("_chat_job_id"),
                    _safe_tool_name_for_log(name),
                )
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
            if name == "spawn_build" and context.get("_last_action_succeeded"):
                context["_source_build_completed"] = True
                return {
                    "reply": _owner_safe_reply(result),
                    "proposal_id": context.get("_last_proposal_id"),
                    "merge_draft_id": context.get("_last_merge_draft_id"),
                    "preview": context.get("_last_preview"),
                    "change": context.get("_last_change"),
                    "changed": context.get("_last_changed"),
                }
    raise RuntimeError(f"Ada reached the configured tool-step limit ({max_steps}); the request did not complete.")


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
