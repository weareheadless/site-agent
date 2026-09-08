"""editor.py — the admin chat: owner asks, Ada proposes, owner approves.

She has hands, not scripts: repository tools (read / propose_changes /
spawn_build) matching writable_patterns, plus read-only senses. Every proposal
lands on the preview branch first; nothing reaches production without
approval.
"""

from __future__ import annotations

import json
from typing import Any

from ..hands.base import AdapterError, SiteAdapter
from ..hands.repo_changes import HARD_DENY, normalize_path, writable
from ..core.design_contracts import DesignRequest
from .prompts import inner_life_context


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


_READ_ACTIONS = {"read_file", "list_files", "get_content", "get_metrics", "list_drafts", "recall",
                 "search_media", "search_business_knowledge"}


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


def _content_summary(content: dict[str, Any]) -> str:
    def shape(value: Any, depth: int = 0) -> str:
        if isinstance(value, dict):
            inner = ", ".join(f"{k}: {shape(v, depth + 1)}" for k, v in list(value.items())[:12])
            return "{" + inner + "}"
        if isinstance(value, list):
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


def _tools_spec(context: dict[str, Any], *, design_intent: bool = False) -> list[dict[str, Any]]:
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
        fn("get_metrics", "GA4 traffic snapshot plus weekly LLM cost", {}),
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
        fn("design_request",
           "Start the canonical asynchronous design workflow for a new site, redesign, or complete page. "
           "Return a complete validated intake; do not invent facts or destinations.",
           {
               "intent": {"type": "string", "enum": ["initial_site", "redesign", "derived_page"]},
               "intake": {"type": "object"},
               "owner_summary": {"type": "string"},
           }, ["intent", "intake", "owner_summary"]),
        fn("propose_changes",
           "Stage one or more file operations as a proposal the owner must approve. "
           "ops entries: {op:'edit',path,find(unique exact snippet),replace} | "
           "{op:'write',path,content(full file)} | {op:'delete',path} | "
           "{op:'set_field',field(dotted into content.json),value}",
           {"summary": {"type": "string"},
            "ops": {"type": "array", "items": {"type": "object"}}},
           ["summary", "ops"]),
    ]
    from ..hands import opencode_runner as _runner

    cfg = context.get("config") if isinstance(context.get("config"), dict) else context
    if _runner.builder_available(cfg) and not (
        design_intent and context.get("design_service") is not None
    ):
        tools.append(fn(
            "spawn_build",
            "Open an autonomous coding session on the repository when the request "
            "benefits from free-form implementation (a new page, a redesign, a "
            "motion system). You decide when it is the right tool; focused edits "
            "can equally go through propose_changes. The builder's tools:\n" +
            _runner.BUILDER_TOOLSET,
            {"brief": {"type": "string"}}, ["brief"]),
        )
    return tools


SYSTEM_NOTE_TOOLS = (
    "\n\nYou operate the site repository through your tools. Sandbox: writable paths are %%WRITABLE%%. "
    "Every change goes to a preview branch first and ships only when the owner approves. "
    "You are the creative lead: the owner expects high-end, distinctive design, not a template "
    "or typical CMS look, and you have full coding capability through the builder for that. "
    "For a broad or creative request (a new page, a redesign, a motion system), brief the "
    "builder with spawn_build — it inspects the repository itself and implements, and its "
    "toolset is listed in the tool description. Use propose_changes for focused edits. "
    "Read tools exist to inform your answer; once you have what you need, act. "
    "Do not re-read what you already saw."
)


def _execute_tool(context: dict[str, Any], adapter: SiteAdapter, name: str, args: dict[str, Any], say) -> str:
    memory = context["memory"]
    phrase = {
        "read_file": lambda: f"reading {args.get('path', '')}",
        "list_files": lambda: "listing repository files",
        "get_content": lambda: "reading content.json",
        "get_metrics": lambda: "pulling GA4 numbers",
        "list_drafts": lambda: "checking pending drafts",
        "recall_memory": lambda: "searching my memory",
        "search_media": lambda: "searching the Library",
        "search_business_knowledge": lambda: "searching approved business knowledge",
        "propose_changes": lambda: "staging the change",
        "spawn_build": lambda: "briefing the builder agent",
        "design_request": lambda: "preparing the typed design handoff",
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
                out = (f"[{path} around '{contains}']\n" + window +
                       "\n\n[use propose_changes edit with an exact unique snippet from this region]")
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
        snap = (memory.latest_snapshot("ga4") or {}).get("data", {})
        spend = memory.llm_spend(since_hours=24 * 7)
        return json.dumps({"traffic": snap, "weekly_llm_cost_usd": round(spend["cost_usd"], 2)})[:1500]
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
        context["_last_action_succeeded"] = True
        lines = "\n".join(f"[{o['op']}] {o['path']}" for o in ops)
        return f"Proposal #{proposal_id} staged. Ops:\n{lines}\nReview the preview, then approve or decline it."
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


SIDE_EFFECTS = {"propose_changes", "spawn_build"}


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
    system += _tweakmap_block(context)
    system += _template_tokens_block(context)
    system += _decision_ledger_block(context)
    try:
        from .prompts import memory_context
        mem = memory_context(context["memory"], max_observations=20)
        if mem:
            system += "\n\n" + mem
    except Exception:  # noqa: BLE001 — memory context must never break chat
        pass

    convo = [{"role": "system", "content": system}, *history, {"role": "user", "content": message}]
    context.pop("_last_proposal_id", None)
    context.pop("_last_merge_draft_id", None)
    context.pop("_last_action_succeeded", None)
    context.pop("_design_request", None)
    context.pop("_read_cache", None)
    if source_message_id is not None:
        context["_source_message_id"] = source_message_id

    max_steps = _max_work_steps(context)
    for hop in range(max_steps):
        design_intent = _looks_like_design_request(message)
        resp = llm.chat_tools(
            convo,
            _tools_spec(context, design_intent=design_intent),
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
            return {"reply": (resp.get("content") or "").strip() or "(no reply)",
                    "proposal_id": context.get("_last_proposal_id"),
                    "merge_draft_id": context.get("_last_merge_draft_id")}
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
            result = _execute_tool(context, adapter, name, args, say)
            convo.append({"role": "tool", "tool_call_id": call["id"], "content": result[:4000]})
            if name == "design_request" and context.get("_design_request"):
                return {
                    "reply": result,
                    "proposal_id": context.get("_last_proposal_id"),
                    "merge_draft_id": context.get("_last_merge_draft_id"),
                    "design_request": context["_design_request"],
                }
            if name in SIDE_EFFECTS and context.get("_last_action_succeeded"):
                return {"reply": result,
                        "proposal_id": context.get("_last_proposal_id"),
                        "merge_draft_id": context.get("_last_merge_draft_id")}
    return {"reply": f"I reached the {max_steps}-step working limit mid-task — say \"continue\" and I'll pick it up.",
            "proposal_id": context.get("_last_proposal_id"),
            "merge_draft_id": context.get("_last_merge_draft_id")}


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
