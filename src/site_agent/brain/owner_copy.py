"""Small presentation guards for Ada's owner-facing messages."""

from __future__ import annotations

import re


_INTERNAL_FAILURE_MARKERS = (
    "repo",
    "repository",
    "source file",
    "worktree",
    "github",
    "sandbox",
    "tooling",
    "api token",
)
_FAILURE_MARKERS = (
    "couldn't",
    "could not",
    "wouldn't",
    "would not",
    "unable",
    "failed",
    "failure",
    "hiccup",
    "not open",
    "not read",
    "not access",
)
_POSITIVE_COMPLETION = re.compile(
    r"(?:"
    r"\b(?:i['’]ve|i have|i just)\s+(?:built|created|implemented|made|finished|completed|staged|previewed)\b"
    r"|\b(?:i['’]ve|i have|i just)\s+(?:updated|changed|verified|rechecked)\s+(?:the\s+)?(?:site|website|page|preview|candidate|homepage)\b"
    r"|\b(?:done|finished|completed)\s*(?:[—:-]|$)"
    r"|\b(?:the|your)\s+(?:preview|site|website|candidate)\s+(?:is|looks)\s+(?:now\s+)?(?:ready|live|updated|built)\b"
    r"|\bpreview\s+is\s+(?:now\s+)?ready\b"
    r")",
    re.IGNORECASE,
)


def owner_safe_reply(reply: str) -> str:
    """Keep transient implementation failures out of Ada's visible prose.

    The model is instructed not to narrate infrastructure, but a final
    presentation guard prevents an unsupported story about a repository or tool
    failure from reaching a non-technical owner.
    """
    text = str(reply or "").strip()
    if not text:
        return text
    paragraphs = re.split(r"(\n\s*\n)", text)
    replacement = (
        "These are initial ideas based on our brief, not a change to the site. "
        "I'll verify the current page before building anything; nothing has been changed "
        "or previewed yet."
    )
    for index in range(0, len(paragraphs), 2):
        paragraph = paragraphs[index]
        lowered = paragraph.lower()
        has_internal_marker = any(marker in lowered for marker in _INTERNAL_FAILURE_MARKERS)
        has_failure_marker = any(marker in lowered for marker in _FAILURE_MARKERS)
        if has_internal_marker and has_failure_marker:
            paragraphs[index] = replacement
    return "".join(paragraphs).strip()


def owner_message_without_unstarted_build(message: str, *, action_started: bool) -> str:
    """Prevent an advice turn from promising a build or result it did not start."""
    text = owner_safe_reply(message)
    if action_started or not (
        re.search(r"\b(?:i['’]ll|i will|i can)\s+(?:build|create|implement|make)\b", text, re.IGNORECASE)
        or _POSITIVE_COMPLETION.search(text)
    ):
        return text
    return (
        "To be clear, I haven't built or previewed this yet. These are directions only. "
        "Choose a direction, then ask me to build it when you're ready."
    )


def owner_safe_failure(error: str) -> str:
    """Turn an internal job failure into a useful, non-technical owner status."""
    lowered = str(error or "").lower()
    if any(marker in lowered for marker in ("github", "git fetch", "repository", "source file", "remote")):
        return "I couldn't reach the site's source files for this check. Nothing was changed. Please try again."
    if any(marker in lowered for marker in ("builder", "build", "preview", "deploy")):
        return "I couldn't finish the preview check. Nothing was changed or published. Please try again."
    return "I couldn't complete that request. Nothing was changed. Please try again."


__all__ = [
    "owner_message_without_unstarted_build",
    "owner_safe_failure",
    "owner_safe_reply",
]
