"""The owner, as a participant rather than a fixture.

An intake conversation cannot be replayed from a script. Ada asks three things
in one turn, rephrases when she gets a partial answer, and follows up on whatever
the owner just said. A keyword table answers the wrong question and loops; a
model answers the conversation.

So the owner is an agent with a brief: who they are, what they know, and what
they will not invent. It is the same idea as the product's own intake advisor,
pointed the other way.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Sequence

# A completion callable takes chat messages and returns the assistant text.
Complete = Callable[[Sequence[Mapping[str, str]]], str]

_OWNER_RULES = """
You are the owner of a small business, talking to Ada, who is building your
website. You are not an assistant and you are not evaluating anything: you are
simply the person answering.

How you answer:
- Reply only with what you would actually say. No preamble, no headings, one to
  three sentences.
- If she asks several things at once, answer all of them in that one reply.
- Answer only what was asked. Do not volunteer your whole brief.
- Never repeat something you already told her.
- Never invent a fact you were not given. If she asks something you do not know,
  say you are not sure and tell her to use her judgement.
- Stay in character: same voice, same level of detail, throughout.
"""


class OwnerAgent:
    """Holds the owner's side of the conversation."""

    def __init__(self, brief: str, complete: Complete, *, max_turns: int = 12) -> None:
        if not brief or not brief.strip():
            raise ValueError("an owner agent needs a brief")
        self.brief = brief.strip()
        self.complete = complete
        self.max_turns = max_turns
        self.transcript: list[dict[str, str]] = []

    def reply(self, ada_said: str) -> str:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _OWNER_RULES.strip() + "\n\nWHO YOU ARE\n" + self.brief},
        ]
        for turn in self.transcript:
            messages.append({"role": "user", "content": turn["ada"]})
            messages.append({"role": "assistant", "content": turn["owner"]})
        messages.append({"role": "user", "content": ada_said or "(Ada is waiting for you to start.)"})
        answer = (self.complete(messages) or "").strip()
        if not answer:
            raise RuntimeError("the owner agent returned an empty reply")
        self.transcript.append({"ada": ada_said, "owner": answer})
        return answer


def chat_completion(
    *,
    model: str,
    api_key: str,
    base_url: str = "https://openrouter.ai/api/v1",
    timeout: int = 120,
    temperature: float = 0.7,
    max_tokens: int = 400,
) -> Complete:
    """An OpenAI-compatible completion callable.

    No provider SDK: the harness should not grow a dependency graph or its own
    credential store. It takes a model name and a key, and the caller decides
    where both come from -- today a fallback provider, later the runner's own
    credentials.
    """

    endpoint = base_url.rstrip("/") + "/chat/completions"

    def complete(messages: Sequence[Mapping[str, str]]) -> str:
        payload = json.dumps(
            {
                "model": model,
                "messages": list(messages),
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(f"owner model returned {exc.code}: {detail}") from exc
        try:
            return str(body["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"unexpected owner model response: {json.dumps(body)[:300]}") from exc

    return complete
