"""opencode_runner.py — she works through a real coding agent.

Each site instance keeps a local git clone (site.clone_path). Chat requests
route here: we sync a `preview` branch from origin/main, hand the brief to a
headless `opencode run` session (which brings its own agentic loop, tools and
skills), commit whatever it changed, push the branch, and return the diff.
Production is touched only when the owner approves the merge.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable


class RunnerError(RuntimeError):
    pass


PREVIEW_BRANCH = "preview"


import re as _re

_ANSI_RE = _re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_HEADER_RE = _re.compile(r"^>\s*[\w./-]+\s*·\s*[\w./-]+\s*$")
_TOOL_EVENT_RE = _re.compile(r"^[→←✗✓]\s")
_RE_PERMS = _re.compile(r"^[-dl][rwxSt-]{9}\s")
_FENCE_RE = _re.compile(r"^\s*(?:```|~~~)")
_CODE_SYMBOLS = "{}=;|#&*"
_MECH_PREFIXES = ("total ", "permission", "chmod ", "error:", "warning:", "usage:", "fatal: ")
_DIFF_LEADS = ("diff --git", "index ", "--- a/", "+++ b/", "@@", "deleted file", "new file", "similarity index")
_DSML_RE = _re.compile(r"(?:DSML|<\s*tool\b|<\s*invoke\b|<\s*parameter\b)", _re.I)
_EXTENSIONS = frozenset((
    "html", "htm", "css", "js", "jsx", "ts", "tsx", "json", "md", "py",
    "svg", "png", "jpg", "jpeg", "webp", "gif", "toml", "txt", "yml", "yaml",
))


def _clean_ui_line(line: str) -> str:
    """Strip opencode's terminal chrome (ANSI escapes and its `> agent · model`
    message headers) so raw CLI output never leaks into the owner-facing reply."""
    line = _ANSI_RE.sub("", line).strip()
    if not line or _HEADER_RE.match(line):
        return ""
    return line


def _token_is_path(token: str) -> bool:
    if token.startswith(("http://", "https://")) or "/" in token or "\\" in token:
        return True
    if "." not in token:
        return False
    suffix = token.lower().rsplit(".", 1)[1].split("?", 1)[0].split("#", 1)[0]
    return bool(suffix) and suffix in _EXTENSIONS


def _css_value_tail(value: str) -> bool:
    """True when a 'key:' value looks like a machine property value (#fff,
    var(--x), 40px, 100%) rather than a sentence the agent wrote."""
    value = value.strip()
    if not value:
        return False
    if value.startswith(("#", "var(", "rgb", "rgba", "url(", "calc(", "--")):
        return True
    return bool(_re.match(r"^-?\d+(\.\d+)?(px|rem|em|vh|vw|%|s|ms)?$", value))


def _looks_like_prose(line: str) -> bool:
    """True when one cleaned CLI line is the agent's own words — safe to show
    the owner — rather than terminal chrome, a file listing, a git/diff dump, or
    a code snippet. The bias is false-negative: uncertain lines are dropped, so
    repository content, paths and listings never reach owner-facing output.
    This classifies machine output; it never tries to read owner intent."""
    if not line or len(line) > 300:
        return False
    if _TOOL_EVENT_RE.match(line):
        return False
    low = line.lstrip().lower()
    if _RE_PERMS.match(line) or low.startswith(_MECH_PREFIXES):
        return False
    if low.startswith(_DIFF_LEADS):
        return False
    if any(ch in _CODE_SYMBOLS for ch in line):
        return False
    match = _re.match(r"^[a-z][a-z0-9-]*\s*:\s*(.*)$", low)
    if match and _css_value_tail(match.group(1)):
        return False
    tokens = line.split()
    if len(tokens) < 2 or all(_token_is_path(t) for t in tokens):
        return False
    return True


class ProseFilter:
    """Extract the agent's prose from a headless opencode session stream.

    Feeds terminal-clean lines (see _clean_ui_line) in order; yields only the
    agent's own natural-language lines. Markdown code fences and their
    contents, repository listings, paths, diffs and other machine artifacts are
    dropped, so both the live progress steps and the final reply stay clean and
    safe for the owner."""

    def __init__(self) -> None:
        self._in_fence = False

    def feed(self, line: str) -> str:
        if not line:
            return ""
        if self._in_fence:
            if _FENCE_RE.match(line):
                self._in_fence = False
            return ""
        if _FENCE_RE.match(line):
            self._in_fence = True
            return ""
        return line if _looks_like_prose(line) else ""


def _git(clone: Path, *args: str, token: str | None = None, timeout: int = 120) -> str:
    cmd = ["git", "-C", str(clone), *args]
    env = os.environ.copy()
    if token:
        auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update({
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {auth}",
        })
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if proc.returncode != 0:
        raise RunnerError(f"git {' '.join(args[:2])}: {proc.stderr.strip()[:300]}")
    return proc.stdout


def _origin_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def worktree_status(config: dict[str, Any]) -> dict[str, Any]:
    """Return the operator-visible state of the persistent site clone."""
    clone = Path(str((config.get("site") or {}).get("clone_path", "")).strip())
    if not clone.exists() or not (clone / ".git").exists():
        return {"available": False, "dirty": False, "path": str(clone), "files": [],
                "error": "site clone is not configured or does not exist"}
    try:
        raw = _git(clone, "status", "--short")
        branch = _git(clone, "branch", "--show-current").strip()
        head = _git(clone, "rev-parse", "--short", "HEAD").strip()
    except RunnerError as exc:
        return {"available": False, "dirty": False, "path": str(clone), "files": [],
                "error": str(exc)[:300]}
    files = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        files.append({"status": line[:2], "path": line[3:] if len(line) > 3 else ""})
    return {
        "available": True,
        "dirty": bool(files),
        "path": str(clone),
        "branch": branch or "(detached)",
        "head": head,
        "files": files[:100],
        "file_count": len(files),
    }


def discard_worktree(config: dict[str, Any]) -> dict[str, Any]:
    """Discard only uncommitted files in the persistent site clone.

    This is intentionally separate from preview reset: committed branches and
    remote refs are never changed by the operator's local cleanup action.
    """
    state = worktree_status(config)
    if not state.get("available"):
        raise RunnerError(str(state.get("error") or "site clone unavailable"))
    if not state.get("dirty"):
        return state
    clone = Path(state["path"])
    _git(clone, "reset", "--hard", "HEAD")
    _git(clone, "clean", "-fd")
    return worktree_status(config)


def ensure_clone(config: dict[str, Any], progress=None) -> Path:
    site = config.get("site") or {}
    clone = Path(str(site.get("clone_path", "")).strip())
    repo = str(site.get("repository", ""))
    if not clone.exists() or not (clone / ".git").exists():
        raise RunnerError(f"clone missing at {clone} — run: git clone {repo} {clone}")
    token = _token(config)
    _git(clone, "config", "user.name", "Ada (site-agent)")
    _git(clone, "config", "user.email", "ada@site-agent.local")
    _git(clone, "remote", "set-url", "origin", _origin_url(repo))
    if progress:
        progress("syncing with GitHub")
    _git(clone, "fetch", "origin", "--prune", token=token, timeout=180)
    return clone


def _token(config: dict[str, Any]) -> str:
    from ..config import resolve_secret

    return resolve_secret(config, "github_token")


def _builder_worktree_path(config: dict[str, Any]) -> Path:
    import time

    root = Path(str(config.get("data_dir") or (Path.cwd() / ".site-agent-data"))) / "builder-worktrees"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"build-{time.time_ns()}"


def _remove_builder_worktree(repo: Path, worktree: Path) -> None:
    try:
        _git(repo, "worktree", "remove", "--force", str(worktree))
    except RunnerError:
        # The worktree is disposable; never let cleanup hide the build result.
        import shutil

        shutil.rmtree(worktree, ignore_errors=True)
        try:
            _git(repo, "worktree", "prune")
        except RunnerError:
            pass


def prepare_preview(config: dict[str, Any], progress=None, base_ref: str | None = None) -> Path:
    """A fresh detached worktree for the agent. Starts from base_ref
    (default origin/main). When an earlier build is still pending approval the
    caller passes origin/preview so new work stacks on the unapproved changes
    instead of clobbering them. Always isolated: builder state never lands in
    the persistent site clone."""
    clone = ensure_clone(config, progress)
    base = base_ref or "origin/main"
    if progress and base != "origin/main":
        progress("building on top of the unapproved preview")
    elif progress:
        progress("resetting preview branch from origin/main")
    if base != "origin/main":
        try:
            _git(clone, "rev-parse", "--verify", f"{base}^{{commit}}")
        except RunnerError:
            base = "origin/main"
    worktree = _builder_worktree_path(config)
    if progress:
        progress("using an isolated preview worktree")
    _git(clone, "worktree", "add", "--detach", str(worktree), base, timeout=180)
    return worktree


def builder_available(config: dict[str, Any]) -> bool:
    b = config.get("builder") or {}
    return bool(b.get("enabled")) and bool(str(config.get("site", {}).get("clone_path", "")).strip())


def _build_base_ref(memory: Any) -> str:
    """Start from origin/preview when an earlier build is still waiting for
    approval, so a follow-up request improves that preview instead of
    discarding the unapproved page and starting from main again."""
    if memory is not None:
        try:
            pending = memory.list_drafts(status="pending")
        except Exception:  # noqa: BLE001
            pending = []
        if any(d.get("kind") == "merge" for d in pending):
            return "origin/preview"
    return "origin/main"


def stage_merge_draft(context: dict[str, Any], message: str, outcome: dict[str, Any]) -> int:
    """Turn a finished build into an approval-gated merge draft. A new build
    replaces the preview branch wholesale, so older pending merge drafts are
    marked discarded — their work is folded into the new cumulative preview."""
    memory = context["memory"]
    for older in memory.list_drafts(status="pending"):
        if older.get("kind") == "merge":
            memory.update_draft_status(older["id"], "discarded")
    return memory.save_draft(
        title=f"Preview ready: {message[:60]}",
        body=outcome.get("diff_stat", ""),
        kind="merge",
        meta={"head": "preview", "base": "main", "summary": message[:160]},
    )


def stage_build(context: dict[str, Any], message: str, progress=None) -> dict[str, Any]:
    """Full build cycle that lands as an approval-gated merge draft."""
    outcome = run_brief(context, message, progress)
    reply = (outcome.get("output") or "").strip()
    merge_draft_id = None
    if outcome.get("changed") and context.get("memory") is not None:
        merge_draft_id = stage_merge_draft(context, message, outcome)
        reply += f"\n\nReview it live on the preview URL — approve draft #{merge_draft_id} to publish."
    return {"reply": reply, "merge_draft_id": merge_draft_id, "changed": bool(outcome.get("changed"))}


ADA_INSTRUCTIONS = """# Ada's Working Instructions

You are Ada, webmaster for this website. The owner talks to you; you edit THIS
repository directly with your tools. You are a person with a point of view,
not a generic assistant - everything you write (code, copy, replies to the
owner) carries the identity below.

You are also the creative lead: the owner expects high-end, distinctive design
that does not read like a template or a typical CMS site. You have full coding
capability and access to libraries such as GSAP — use them decisively when they
make the result memorable. What to use, and where, is your call.

GSAP production guardrails:
- Use GSAP 3 APIs only: gsap.to(), gsap.from(), gsap.fromTo(), gsap.timeline(),
  and current plugin APIs. Never use TweenMax, TimelineLite, Power2, or other
  GSAP 2 syntax. Do not invent methods or plugins; inspect the installed version
  or ask when an API is uncertain.
- Prefer transform and opacity properties (x, y, scale, rotation, opacity) for
  motion. Do not animate top, left, width, height, or margin when a transform
  can achieve the same result. Use layout properties only when the requested
  behavior genuinely requires layout to change, and check responsive behavior.
- Every animation must have teardown. In React, use @gsap/react's useGSAP()
  when that dependency is available; otherwise use gsap.context() and revert it.
  In other frameworks, use the framework lifecycle and clean up timelines,
  ScrollTriggers, listeners, and contexts on unmount or route change.
- For ScrollTrigger, identify the trigger, target, start, end, scrub/pin behavior,
  and pinSpacing explicitly. Use markers: true while debugging, then remove or
  disable them before finishing. Avoid hard-coded measurements when refresh,
  responsive layout, or dynamic content can change them.
- Account for prefers-reduced-motion. Use gsap.matchMedia() or an equivalent
  media-query branch to reduce motion to opacity-only or disable nonessential
  transforms. Consider resize, route changes, and dynamic content before coding.

%%BUILDER_TOOLSET%%%%PERSONA%%Hard rules:
- You are working in a disposable checkout on the `preview` branch. Work here;
  never switch branches, never push.
- Never touch admin.html, .github/, CNAME, package.json, or any credentials.
- Read files before editing so your edits preserve recognizable brand conventions,
  unless the execution contract supplies the relevant files and measured design
  references and explicitly requires immediate editing.
- New pages must account for fixed or sticky site chrome: measure the header and
  give the first content block a deliberate safe offset rather than assuming
  normal document flow.
- You may use the native task tool to delegate bounded exploration or validation
  to the configured explore/general subagents when it materially reduces work.
  Keep final design decisions and implementation edits in this primary session;
  never have subagents edit the same worktree concurrently.
- Never introduce a class in a template without defining its layout and type
  styles, and render the generated output after editing templates.
- The available design and motion skills are tools, not a prescribed direction.
  Use them when they help; ignore them when they do not.
- Not every message is a work order. When the owner just talks — greets you,
  asks how you are, wonders out loud — answer as yourself, in plain prose,
  and touch nothing. Only make changes when something is actually requested,
  and never invent work to have something to commit.
- You are honest about being a model with no body or location. Never claim to
  have personally been somewhere, never invent live conditions (weather, water
  temperature, crowds, this-morning reports), even inside the persona. Vivid,
  specific writing comes from knowledge and sources, never from faked visits.
- When you build or redesign a page, also write the editable parameters you
  created or changed to .opencode/tweak-map.json (JSON, gitignored — never
  commit it). One object keyed by file: entries like
  {"label":"footer.padding","file":"styles.css","kind":"css","selector":".footer","prop":"padding","current":"4px","find":"padding: 4px;"}
  or {"label":"hero.title","file":"index.html","kind":"text","selector":"h1","current":"Breathe deep","find":"Breathe deep"}
  or {"label":"content.heroTitle","file":"content.json","kind":"field","field":"heroTitle","current":"Breathe deep"}.
  "find" must be the EXACT snippet currently in the file (the whole
  declaration for css, the exact text for a heading). The owner later tweaks
  from this map — list the knobs an owner would actually change, tightly.
- When done, state plainly: what you changed, file by file, and anything the
  owner should check.
"""


BUILDER_TOOLSET = (
    "YOUR TOOLSET (what you actually have, use it freely):\n"
    "- Shell: bash — run commands, download files with curl (e.g. self-hosting a library "
    "into vendor/), git, any CLI.\n"
    "- Files: read, write, edit, patch any repository file.\n"
    "- Search: glob + grep across the repo, web search and web fetch when you need "
    "pinned versions or external references.\n"
    "- Delegation: task can invoke the native explore/general subagents for bounded "
    "read-only exploration or validation when that genuinely helps.\n"
)


def _render_instructions(persona: str) -> str:
    block = ""
    if persona and persona.strip():
        block = "WHO YOU ARE AND HOW YOU SPEAK:\n" + persona.strip() + "\n\n"
    return ADA_INSTRUCTIONS.replace("%%PERSONA%%", block).replace("%%BUILDER_TOOLSET%%", BUILDER_TOOLSET)


def install_agent_files(clone: Path, skills_src: Path | None, model: str | None,
                        openrouter_key: str | None = None, persona: str = "",
                        site_digest: str = "", template_tokens: str = "",
                        memory: Any | None = None,
                        provider_timeout_seconds: int = 2100,
                        provider_chunk_timeout_seconds: int = 180,
                        output_tokens: int = 8192,
                        reasoning_effort: str = "low") -> None:
    """Install Ada's project instructions and skills for native OpenCode Build.

    The primary agent remains OpenCode's built-in ``build`` agent. Ada's identity,
    site context, and task permission are project-scoped instead of replacing the
    native agent profile.
    """
    oc = clone / ".opencode"
    try:
        exclude_path = (clone / _git(clone, "rev-parse", "--git-path", "info/exclude").strip()).resolve()
        content = exclude_path.read_text() if exclude_path.exists() else ""
        for entry in (".opencode/", ".agent-home/", "opencode.json"):
            if entry not in content:
                content = content.rstrip() + "\n" + entry + "\n"
        if content != (exclude_path.read_text() if exclude_path.exists() else ""):
            exclude_path.parent.mkdir(parents=True, exist_ok=True)
            exclude_path.write_text(content.lstrip("\n"))
    except RunnerError:
        pass

    oc.mkdir(parents=True, exist_ok=True)
    model_id = _qualified_model(model or "")
    opencode_config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "instructions": [".opencode/ada-instructions.md"],
        "permission": {"task": {"*": "allow"}},
    }
    if model_id:
        opencode_config["model"] = model_id
    if openrouter_key and model_id.startswith("openrouter/"):
        import json as _json
        bare = model_id.split("/", 1)[1]
        opencode_config.update({
            "small_model": f"openrouter/{bare}",
            "provider": {
                     "openrouter": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "OpenRouter",
                        "options": {
                            "baseURL": "https://openrouter.ai/api/v1",
                            "apiKey": "{env:OPENROUTER_API_KEY}",
                        # DeepSeek averages 8 output tokens/sec. Keep the provider
                        # request alive longer than the host watchdog and fail only
                        # after a genuinely silent stream.
                        "timeout": max(300, int(provider_timeout_seconds)) * 1000,
                        "chunkTimeout": max(30, int(provider_chunk_timeout_seconds)) * 1000,
                    },
                    "models": {bare: {
                        "name": "Ada's working model",
                        "limit": {
                            "context": 1_048_576,
                            "output": max(1024, int(output_tokens)),
                        },
                        "options": {
                            "max_tokens": max(1024, int(output_tokens)),
                            "reasoning_effort": str(reasoning_effort or "low").strip() or "low",
                        },
                    }},
                }
            },
        })
    rendered = _render_instructions(persona)
    if site_digest and site_digest.strip():
        rendered += ("\n\nSITE REFERENCE (structural digest — read this before "
                     "reading whole files, it covers what you'd otherwise re-read):\n"
                     + site_digest.strip())
    if template_tokens and template_tokens.strip():
        rendered += ("\n\nDESIGN REFERENCE (measured values from the sampled main page. "
                     "Preserve recognizable brand conventions, but adapt incidental "
                     "values when needed for hierarchy, contrast, accessibility, "
                     "depth, or responsiveness. The design quality core wins):\n" +
                     template_tokens.strip())
    if memory is not None:
        try:
            from ..brain.prompts import memory_context
            mem = memory_context(memory, max_observations=20)
            if mem:
                rendered += "\n\n" + mem
        except Exception:  # noqa: BLE001 — memory context must never block a build
            pass
    (oc / "ada-instructions.md").write_text(rendered.rstrip() + "\n")
    import json as _json
    # Project configuration is read from the repository root. `.opencode/` is
    # reserved for agents, skills, and other extension directories.
    (clone / "opencode.json").write_text(_json.dumps(opencode_config, indent=2) + "\n")
    if skills_src and Path(skills_src).exists():
        skills_dst = oc / "skill"
        skills_dst.mkdir(parents=True, exist_ok=True)
        for src in Path(skills_src).glob("*.md"):
            name = src.stem
            dst_dir = skills_dst / name
            dst_dir.mkdir(exist_ok=True)
            (dst_dir / "SKILL.md").write_text(src.read_text())


def build_brief(message: str, config: dict[str, Any]) -> str:
    persona = (config.get("persona") or {})
    voice = persona.get("voice") or ""
    lines = [f"Owner: {message}"]
    if voice:
        lines.append(f"Site tone: {voice}")
    lines.append(
        "Inspect the repository, decide how best to handle the request, and carry it "
        "through in this same run. The available design and motion skills are tools, "
        "not a prescribed direction. You are the creative lead: deliver high-end, "
        "distinctive design that does not read like a template or typical CMS site, "
        "using your full coding capability and libraries such as GSAP when they make "
        "the result memorable."
    )
    lines.append(
        "If this is a request to change the site, implement it here now — leave all "
        "changes UNCOMMITTED in the working tree when you finish (no git add/commit/push) "
        "and summarize what you changed. If it is just conversation — a greeting, a "
        "question, small talk — answer as yourself in plain prose and change nothing."
    )
    if "journal" in message.lower() or "pelican" in message.lower():
        lines.append(
            "JOURNAL REQUEST: own the complete design and implementation autonomously in "
            "this Build session. Inspect the existing Pelican templates and site chrome, "
            "preserve Pelican behavior, keep journal styles scoped, respect the fixed-header "
            "safe offset and the 1240px / 48px gutter system, do not invent article content, "
            "run the site's build and inspect the generated pages, then leave the working "
            "tree ready for the normal approval-gated preview flow."
        )
    return "\n".join(lines)


def _isolated_env(clone: Path, openrouter_key: str = "") -> dict[str, str]:
    """Give the builder only the process environment it needs.

    The key is passed through the child environment because OpenCode supports
    ``{env:...}`` config interpolation; it is never written to the worktree.
    """
    import os

    home = clone / ".agent-home"
    passthrough = {
        "PATH", "LANG", "LC_ALL", "TERM", "TMPDIR", "NO_COLOR", "CI",
        "SSL_CERT_FILE", "SSL_CERT_DIR",
    }
    env = {key: value for key, value in os.environ.items() if key in passthrough}
    for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                     ("XDG_CACHE_HOME", "cache")):
        d = home / sub
        d.mkdir(parents=True, exist_ok=True)
        env[var] = str(d)
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    if openrouter_key:
        env["OPENROUTER_API_KEY"] = openrouter_key
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    env["PWD"] = str(clone)   # subprocess cwd does not update PWD; opencode trusts PWD
    env.pop("OLDPWD", None)
    return env


def _opencode_bin(config: dict[str, Any]) -> str:
    """Find the opencode CLI without relying on $PATH (systemd units have a
    minimal PATH that misses ~/.opencode/bin)."""
    import shutil

    b = config.get("builder") or {}
    custom = str(b.get("bin") or "").strip()
    if custom:
        if Path(custom).exists():
            return custom
        raise RunnerError(f"builder.bin points to missing file: {custom}")
    found = shutil.which("opencode")
    if found:
        return found
    for cand in (Path.home() / ".opencode" / "bin" / "opencode",
                 "/usr/local/bin/opencode", "/usr/bin/opencode"):
        if cand.exists():
            return str(cand)
    raise RunnerError("opencode CLI not found — set builder.bin in config.yaml")


def _qualified_model(model: str) -> str:
    model = str(model or "").strip()
    if model and "/" in model and not model.startswith(("openrouter/", "anthropic/", "openai/")):
        return "openrouter/" + model
    return model


def run_opencode(clone: Path, brief: str, config: dict[str, Any], progress=None) -> str:
    """Run one native Build turn and return its owner-facing reply."""
    result = run_opencode_turn(clone, brief, config, progress=progress)
    return str(result.get("reply") or "")


def _event_value(event: dict[str, Any], key: str) -> Any:
    if event.get(key) is not None:
        return event[key]
    part = event.get("part") or {}
    return part.get(key)


def run_opencode_turn(clone: Path, brief: str, config: dict[str, Any],
                      progress=None, session_id: str | None = None,
                      timeout_seconds: int | None = None) -> dict[str, Any]:
    """Run one structured OpenCode turn, optionally continuing a session.

    OpenCode's JSON event stream is the source of truth for tool calls. Plain
    DSML/XML emitted inside a text event is a provider protocol failure, not a
    successful turn, and is rejected immediately.
    """
    import signal
    import threading
    from ..config import resolve_secret

    b = config.get("builder") or {}
    timeout = max(1, int(timeout_seconds or b.get("timeout_seconds", 1800)))
    cmd = [
        _opencode_bin(config), "run", "--auto", "--format", "json",
        "--print-logs", "--log-level", "ERROR",
        "--agent", "build",
    ]
    builder_model = str(b.get("model") or (config.get("llm") or {}).get("model") or "").strip()
    if builder_model:
        cmd.extend(["--model", _qualified_model(builder_model)])
    if session_id:
        cmd.extend(["--session", session_id])
    cmd.append(brief)
    if progress:
        progress("opencode is at work on the repository")
    proc = subprocess.Popen(
        cmd, cwd=clone, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, stdin=subprocess.DEVNULL,
        env=_isolated_env(clone, resolve_secret(config, "llm_api_key")), start_new_session=True,
    )
    timed_out = threading.Event()

    def terminate_process() -> None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (AttributeError, OSError):
            try:
                proc.terminate()
            except OSError:
                pass

    def stop_after_timeout() -> None:
        timed_out.set()
        terminate_process()

    watchdog = threading.Timer(timeout, stop_after_timeout)
    watchdog.daemon = True
    watchdog.start()
    tail: list[str] = []
    prose: list[str] = []
    seen: set[str] = set()
    filter_prose = ProseFilter()
    events: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    session = session_id
    protocol_error: str | None = None
    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"type": "raw", "text": _clean_ui_line(line)}
            if not isinstance(event, dict):
                continue
            events.append(event)
            session = session or _event_value(event, "sessionID")
            part = event.get("part") or {}
            event_type = event.get("type") or part.get("type") or ""
            if event_type == "tool_use" or part.get("type") == "tool":
                state = part.get("state") or {}
                tool_calls.append({
                    "tool": part.get("tool") or part.get("name") or "unknown",
                    "status": state.get("status") if isinstance(state, dict) else "unknown",
                })
            text = event.get("text") or part.get("text") or ""
            if not isinstance(text, str) or not text:
                continue
            if _DSML_RE.search(text):
                protocol_error = text[:400]
                terminate_process()
                break
            for text_line in text.splitlines():
                cleaned = _clean_ui_line(text_line)
                if not cleaned:
                    continue
                tail.append(cleaned)
                step = filter_prose.feed(cleaned)
                if not step:
                    continue
                prose.append(step)
                if progress and len(seen) < 8:
                    key = step[:100].lower()
                    if key not in seen:
                        seen.add(key)
                        progress(step[:120])
        proc.wait(timeout=10)
    except BaseException:
        terminate_process()
        raise
    finally:
        watchdog.cancel()
    if timed_out.is_set():
        raise RunnerError(f"opencode timed out after {timeout}s")
    if protocol_error:
        raise RunnerError("opencode emitted unsupported DSML/XML instead of a native tool call: " + protocol_error)
    if proc.returncode != 0:
        detail = chr(10).join(tail[-8:])
        raise RunnerError(f"opencode exited {proc.returncode}: {detail[:400]}")
    if tail and tail[-1].startswith("✗ "):
        raise RunnerError(f"opencode stopped after a failed tool call: {tail[-1][:300]}")
    failed_tools = [call for call in tool_calls if call.get("status") == "error"]
    if failed_tools and not any(call.get("status") == "completed" for call in tool_calls[-1:]):
        raise RunnerError(f"opencode stopped after a failed tool call: {failed_tools[-1].get('tool', 'unknown')}")
    reply_lines = prose[-24:] or tail[-24:]
    return {
        "reply": chr(10).join(reply_lines),
        "session_id": str(session or ""),
        "tool_calls": tool_calls,
        "event_count": len(events),
        "native_tool_calls": len(tool_calls),
    }


def _current_persona(config: dict[str, Any], memory: Any = None) -> str:
    """The full identity block: base persona + owner-approved reflection notes."""
    from ..brain.prompts import persona_prompt
    from ..core.reflect import effective_persona

    if memory is not None:
        return effective_persona(config, memory)
    return persona_prompt(config)



def _bump_asset_versions(clone: Path) -> None:
    """If styles.css changed, bump its ?v= query in index.html so visitors'
    cached copies can't hide her update."""
    import re
    import time as _t

    try:
        changed = _git(clone, "diff", "--name-only").strip().splitlines()
    except RunnerError:
        return
    if not any(f.strip() == "styles.css" for f in changed):
        return
    idx = clone / "index.html"
    if not idx.is_file():
        return
    text = idx.read_text()
    stamp = format(int(_t.time()), "x")
    new = re.sub(r"(styles\.css\?v=)[^\"']+", lambda m: m.group(1) + stamp, text)
    if new != text:
        idx.write_text(new)

def _brand_context(config: dict[str, Any]) -> str:
    """The site's brand contract as plain text for her plan to interpret — the
    ground truth she references so she does not have to guess at identity."""
    site = config.get("site") or {}
    brand = site.get("brand") or {}
    parts = []
    if brand.get("name"):
        parts.append(f"Brand name: {brand['name']}")
    if brand.get("tagline"):
        parts.append(f"Tagline: {brand['tagline']}")
    fonts = brand.get("fonts")
    if not fonts and (brand.get("font_body") or brand.get("font_display")):
        fonts = {k: brand[k] for k in ("font_body", "font_display") if brand.get(k)}
    if fonts:
        parts.append(f"Fonts: {fonts}")
    if brand.get("colors"):
        parts.append(f"Colors: {brand['colors']}")
    logo = brand.get("logo_url") or brand.get("logo")
    if logo:
        parts.append(f"Logo: {logo}")
    if brand.get("nav"):
        parts.append(f"Navbar (in order): {brand['nav']}")
    if brand.get("footer"):
        parts.append(f"Footer: {brand['footer']}")
    if brand.get("cta"):
        parts.append(f"Primary CTA: {brand['cta']}")
    persona = config.get("persona") or {}
    if persona.get("voice"):
        parts.append(f"Site voice: {persona['voice']}")
    if persona.get("audience"):
        parts.append(f"Site audience: {persona['audience']}")
    return "\n".join(parts) if parts else "(no brand block configured)"


def _site_digest(context: dict[str, Any], clone: Path) -> str:
    from .site_digest import cached as digest_cached

    try:
        return digest_cached(clone, context.get("memory"))
    except Exception:  # noqa: BLE001 — a digest failure must never block a build
        return ""


def _vision_context(config: dict[str, Any], clone: Path) -> str:
    from ..core.vision import site_image_context

    try:
        return site_image_context(config, clone)
    except Exception:  # noqa: BLE001 — vision is optional and never blocks builds
        return ""


def _template_tokens(context: dict[str, Any], clone: Path) -> str:
    from .template_tokens import cached as tokens_cached

    try:
        return tokens_cached(clone, context.get("memory"))
    except Exception:  # noqa: BLE001 — a tokens failure must never block a build
        return ""


def _changed_paths(clone: Path, base_ref: str) -> set[str]:
    """Paths changed by the agent, including committed and untracked work."""
    outputs = [
        _git(clone, "diff", "--name-only", "-z", f"{base_ref}...HEAD"),
        _git(clone, "diff", "--name-only", "-z", "HEAD"),
        _git(clone, "ls-files", "--others", "--exclude-standard", "-z"),
    ]
    return {path for output in outputs for path in output.split("\0") if path}


def _change_state(clone: Path) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Fingerprint committed and working-tree state while ignoring agent metadata."""
    import hashlib

    head = _git(clone, "rev-parse", "HEAD").strip()
    files: list[tuple[str, str]] = []
    for relative in sorted(_changed_paths(clone, "HEAD")):
        path = clone / relative
        if path.is_symlink():
            digest = "link:" + os.readlink(path)
        elif path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            digest = "missing"
        files.append((relative, digest))
    return head, tuple(files)


def _validate_build_paths(config: dict[str, Any], clone: Path, base_ref: str) -> None:
    """Enforce the same path sandbox as editor proposals before git can stage."""
    from .repo_changes import writable

    patterns = [str(p) for p in ((config.get("site") or {}).get("writable_patterns") or [])]
    refused = sorted(path for path in _changed_paths(clone, base_ref) if not writable(path, patterns))
    if refused:
        raise RunnerError("builder changed files outside the writable sandbox: " + ", ".join(refused[:10]))


def _validate_journal_build(clone: Path, base_ref: str) -> None:
    """Reject journal previews that changed templates without producing a
    usable, styled public page. A merge draft is a customer-facing artifact, so
    a successful agent exit is not sufficient evidence of a successful design.
    """
    import re
    import subprocess

    changed = set(_changed_paths(clone, base_ref))
    required = {
        "themes/oceanicvibes/templates/base.html",
        "themes/oceanicvibes/templates/index.html",
        "themes/oceanicvibes/templates/article.html",
    }
    missing = sorted(required - changed)
    if missing:
        raise RunnerError("journal preview must redesign all journal templates: " + ", ".join(missing))

    build = subprocess.run(
        ["bash", "build.sh"], cwd=clone, capture_output=True, text=True, timeout=90,
    )
    if build.returncode != 0:
        raise RunnerError(f"journal build failed: {(build.stderr or build.stdout)[-500:]}")
    output = clone / "output"
    listing = output / "articles.html"
    if not listing.exists():
        raise RunnerError("journal build did not produce output/articles.html")
    leaked = [p for p in output.rglob("*") if p.is_file() and ("themes" in p.parts or p.suffix in {".jinja", ".jinja2"})]
    if leaked:
        raise RunnerError("journal build leaked source templates into public output")

    templates = "\n".join(
        (clone / path).read_text(errors="replace") for path in sorted(required)
    )
    styles = "\n".join(
        p.read_text(errors="replace") for p in clone.rglob("*.css")
        if ".git" not in p.parts and "output" not in p.parts
    )
    styles += "\n".join(
        block for block in re.findall(r"<style[^>]*>(.*?)</style>", templates, re.I | re.S)
    )
    journal_classes = {
        token for group in re.findall(r'class=["\']([^"\']*)["\']', templates)
        for token in group.split() if token.startswith("journal-")
    }
    missing_styles = [
        token for token in journal_classes
        if f".{token}" not in styles and f"#{token}" not in styles
    ]
    if missing_styles:
        raise RunnerError("journal templates reference unstyled classes: " + ", ".join(sorted(set(missing_styles))))
    if "journal-body" in templates and "position:fixed" in styles and "journal-masthead" not in styles:
        raise RunnerError("journal content has no scoped layout styles for the fixed homepage header")
    if "article.content" not in templates and "article.content" not in templates.replace(" ", ""):
        raise RunnerError("article template does not render Pelican article content")


def _is_journal_request(message: str) -> bool:
    lowered = message.lower()
    return "journal" in lowered or "pelican" in lowered


CANONICAL_JOURNAL_REQUEST = (
    "Set up the customer-facing journal for this website. Inspect the existing homepage "
    "and design language. Ada must personally design and implement the Pelican article "
    "listing and article page so they feel like this website, not a generic CMS. Make the "
    "journal discoverable from the existing navigation when appropriate, keep it responsive "
    "and accessible, and limit code changes to the existing Pelican templates, journal-scoped "
    "CSS, and public navigation; do not modify build.sh, pelicanconf.py, or deployment "
    "configuration. The homepage header is fixed and uses the 1240px/48px gutter system: "
    "keep every journal first-content block below the header safe offset, and do not reuse "
    "homepage class names without supplying the required journal styles. Redesign base.html, "
    "index.html, and article.html as one coherent system. Run build.sh, inspect "
    "output/articles.html, and verify the article template before finishing. Work "
    "autonomously in the native Build session; use native task delegation when it materially "
    "helps, but keep final design decisions and implementation in the primary session. Do "
    "not invent customer content. Work in the normal preview flow; do not publish directly. "
    "When the design is ready, leave a preview for the owner to approve."
)


def normalize_journal_message(message: str) -> str:
    """Upgrade persisted pre-native-build journal jobs before execution."""
    lowered = message.lower()
    if _is_journal_request(message) and (
        "spawn_build" in lowered or "background builder" in lowered or "phased" in lowered
    ):
        return CANONICAL_JOURNAL_REQUEST
    return message


def _validate_preview(config: dict[str, Any], clone: Path, base_ref: str, message: str) -> None:
    _validate_build_paths(config, clone, base_ref)
    if _is_journal_request(message):
        _validate_journal_build(clone, base_ref)


def _prepare_builder_context(context: dict[str, Any], progress=None,
                             base_ref: str | None = None) -> tuple[Path, Path, str, tuple[str, tuple[tuple[str, str], ...]]]:
    """Prepare one isolated builder checkout and inject Ada's site context."""
    from ..config import resolve_secret

    config = context["config"]
    memory = context.get("memory")
    base_ref = base_ref or _build_base_ref(memory)
    site_clone = Path(str((config.get("site") or {}).get("clone_path", ""))).resolve()
    clone = prepare_preview(config, progress, base_ref=base_ref)
    if progress:
        progress("mapping the existing site")
    site_digest = _site_digest(context, clone)
    if progress and (config.get("vision") or {}).get("enabled"):
        progress("checking the site's imagery")
    vision_context = _vision_context(config, clone)
    if vision_context:
        site_digest = (site_digest + "\n\n" + vision_context).strip()
    if progress:
        progress("preparing design tools")
    template_tokens = _template_tokens(context, clone)
    builder = config.get("builder") or {}
    install_agent_files(
        clone, Path(__file__).parent.parent / "skills",
        builder.get("model") or (config.get("llm") or {}).get("model"),
        resolve_secret(config, "llm_api_key"),
        persona=_current_persona(config, memory),
        site_digest=site_digest,
        template_tokens=template_tokens,
        memory=memory,
        provider_timeout_seconds=int(builder.get("provider_timeout_seconds", 2100)),
        provider_chunk_timeout_seconds=int(builder.get("provider_chunk_timeout_seconds", 180)),
        output_tokens=int(builder.get("output_tokens", 8192)),
        reasoning_effort=str(builder.get("reasoning_effort", "low")),
    )
    return site_clone, clone, base_ref, _change_state(clone)


def _finish_builder(context: dict[str, Any], clone: Path, base_ref: str,
                    message: str, output: str, progress=None) -> dict[str, Any]:
    """Commit, push, and summarize a build that already passed validation."""
    config = context["config"]
    memory = context.get("memory")
    status = _git(clone, "status", "--porcelain").strip()
    if status:
        if progress:
            progress("committing her changes to the preview branch")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-m", f"Ada: {message[:80]}")
    else:
        try:
            ahead = _git(clone, "rev-list", "--count", "origin/main..HEAD").strip()
        except RunnerError:
            ahead = "0"
        if ahead == "0":
            raise RunnerError("Ada finished without implementation changes")
    if progress:
        progress("pushing preview branch to GitHub")
    _git(clone, "push", "--force-with-lease", "origin", f"HEAD:{PREVIEW_BRANCH}",
         token=_token(config), timeout=180)

    stat = _git(clone, "diff", "--stat", "origin/main...HEAD")
    try:
        preview_head = _git(clone, "rev-parse", "HEAD").strip()
        from .tweakmap import store_builder_map

        store_builder_map(clone, memory, preview_head)
    except Exception:  # noqa: BLE001 — a missing tweak map must never fail the build
        pass
    return {"changed": True, "output": output, "diff_stat": stat[-600:], "branch": PREVIEW_BRANCH}


def run_brief(context: dict[str, Any], message: str, progress=None) -> dict[str, Any]:
    """Run one native Build session, repair objective failures, then stage preview."""
    config = context["config"]
    memory = context.get("memory")
    site_clone, clone, base_ref, prepared_state = _prepare_builder_context(context, progress)
    output: list[str] = []
    session_id: str | None = None
    try:
        if progress:
            progress("Ada is working autonomously in the preview worktree")
        initial = run_opencode_turn(
            clone, build_brief(message, config), config, progress=progress,
        )
        session_id = initial.get("session_id") or None
        output.append(str(initial.get("reply") or ""))

        if _change_state(clone) == prepared_state:
            if progress:
                progress("the Build agent made no implementation changes")
            if _is_journal_request(message):
                raise RunnerError("Ada finished without implementation changes")
            return {"changed": False, "output": "\n\n".join(filter(None, output))}

        repair_limit = max(0, int((config.get("builder") or {}).get(
            "validation_repair_attempts", 2
        )))
        validation_error: RunnerError | None = None
        for attempt in range(repair_limit + 1):
            try:
                if progress:
                    progress("validating the generated preview")
                _validate_preview(config, clone, base_ref, message)
                _bump_asset_versions(clone)
                _validate_preview(config, clone, base_ref, message)
                validation_error = None
                break
            except RunnerError as exc:
                validation_error = exc
                if attempt >= repair_limit:
                    break
                if not session_id:
                    break
                if progress:
                    progress(f"Ada is repairing validation failure ({attempt + 1}/{repair_limit})")
                repair = run_opencode_turn(
                    clone,
                    (
                        "Continue the same owner task in this worktree. Host validation failed "
                        "with the concrete issue below. Inspect the current implementation, "
                        "repair what is necessary using your own design judgment, and run the "
                        "relevant verification before finishing. Do not just describe a fix; "
                        "make the edits. Leave changes uncommitted.\n\n"
                        "VALIDATION ISSUE:\n" + str(exc)[:2000]
                    ),
                    config,
                    progress=progress,
                    session_id=session_id,
                )
                session_id = repair.get("session_id") or session_id
                output.append(str(repair.get("reply") or ""))
        if validation_error is not None:
            raise validation_error

        return _finish_builder(
            context, clone, base_ref, message,
            "\n\n".join(filter(None, output)), progress,
        )
    finally:
        _remove_builder_worktree(site_clone, clone)


def merge_preview(config: dict[str, Any], message: str) -> dict[str, Any]:
    """Owner approved: merge preview into main on GitHub."""
    from ..hands.github_static import _request, API

    repo = str((config.get("site") or {}).get("repository", "")).strip().strip("/")
    token = _token(config)
    status, body = _request(
        "POST",
        f"{API}/repos/{repo}/merges",
        token=token,
        payload={"base": "main", "head": PREVIEW_BRANCH, "commit_message": message[:200]},
    )
    return {"merged": status in (201, 200), "sha": body.get("sha"), "html_url": body.get("html_url")}
