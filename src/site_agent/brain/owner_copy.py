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


_CLAIM_NEGATED = re.compile(
    r"\b(?:not|never|haven['’]t|hasn['’]t|isn['’]t|wasn['’]t|no)\b",
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


_CORRECTION = (
    "I haven't built or previewed this yet, so nothing has changed. "
    "Choose a direction, then ask me to build it when you're ready."
)


def owner_message_without_unstarted_build(message: str, *, action_started: bool) -> str:
    """Remove a false completion claim without discarding the rest of the answer.

    This used to replace the whole message whenever it merely *offered* to build
    something later ("I'll build it once you confirm the portrait"). A complete,
    correct plan was replaced by one canned sentence, and that sentence then
    became the assistant turn in the conversation history, so the owner's next
    "state the plan again" had no plan left to restate. Only a claim that work
    already happened is unsupported here; a forward-looking offer is not, and a
    false claim is now removed sentence by sentence.
    """
    text = owner_safe_reply(message)
    if action_started or not _POSITIVE_COMPLETION.search(text):
        return text
    kept: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if _POSITIVE_COMPLETION.search(sentence) and not _CLAIM_NEGATED.search(sentence):
            continue
        kept.append(sentence)
    remainder = " ".join(part.strip() for part in kept if part.strip()).strip()
    if len(remainder) < 40:
        return _CORRECTION
    return remainder


_CREDIT_MARKERS = (
    "no credit left",
    "exceed your available credits",
    "insufficient credits",
    "insufficient balance",
    "credit balance",
    "payment required",
    "quota exceeded",
)


def owner_safe_failure(error: str) -> str:
    """Turn an internal job failure into a useful, non-technical owner status."""
    lowered = str(error or "").lower()
    if any(marker in lowered for marker in _CREDIT_MARKERS):
        return (
            "The model provider rejected this request because the account has run out of "
            "credit, so I stopped. Nothing was changed or published. The account needs "
            "topping up before I can try again."
        )
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
