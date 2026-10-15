"""Canonical conversion from Ada's Markdown drafts to Payload Lexical rich text.

The article writer stores editorial copy as Markdown. Payload's shared `posts.body`
field is Lexical, so this module is the single schema-boundary serializer.
Unsupported markup is reduced to its text; it is never stored as HTML.
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

import markdown


def _element(node_type: str, children: list[dict[str, Any]], **fields: Any) -> dict[str, Any]:
    return {
        "type": node_type,
        "children": children,
        "direction": None,
        "format": "",
        "indent": 0,
        "version": 1,
        **fields,
    }


class _LexicalParser(HTMLParser):
    _block_tags = {f"h{level}": "heading" for level in range(1, 7)} | {
        "p": "paragraph",
        "blockquote": "paragraph",
        "pre": "paragraph",
    }
    _format_bits = {"strong": 1, "b": 1, "em": 2, "i": 2, "u": 8, "code": 16}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.children: list[dict[str, Any]] = []
        self.target = self.children
        self.targets: list[tuple[str, list[dict[str, Any]]]] = []
        self.formats: list[tuple[str, int]] = []
        self.format = 0

    def _append_target(self, node: dict[str, Any], tag: str) -> None:
        self.target.append(node)
        self.targets.append((tag, self.target))
        self.target = node["children"]

    def _append_text(self, value: str) -> None:
        if not value:
            return
        text = {
            "detail": 0,
            "format": self.format,
            "mode": "normal",
            "style": "",
            "text": value,
            "type": "text",
            "version": 1,
        }
        if self.target and self.target[-1].get("type") == "text" and self.target[-1].get("format") == self.format:
            self.target[-1]["text"] += value
        else:
            self.target.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in self._block_tags:
            node_type = self._block_tags[tag]
            fields = {"tag": tag} if node_type == "heading" else {}
            self._append_target(_element(node_type, [], **fields), tag)
        elif tag in {"ul", "ol"}:
            node = _element("list", [], listType="number" if tag == "ol" else "bullet", start=1, tag=tag)
            self._append_target(node, tag)
        elif tag == "li":
            value = sum(1 for child in self.target if child.get("type") == "listitem") + 1
            self._append_target(_element("listitem", [], value=value), tag)
        elif tag == "a":
            url = str(attributes.get("href") or "").strip()
            parsed = urlsplit(url)
            safe = parsed.scheme in {"http", "https", "mailto"} or (not parsed.scheme and not parsed.netloc and url.startswith(("/", "#")))
            if safe and url:
                external = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
                node = _element("link", [], version=3, fields={
                    "url": url,
                    "newTab": external,
                    "rel": "noopener noreferrer" if external else None,
                    "title": attributes.get("title"),
                })
                self._append_target(node, tag)
        elif tag in self._format_bits:
            self.formats.append((tag, self.format))
            self.format |= self._format_bits[tag]
        elif tag == "br":
            self._append_text("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._format_bits:
            for index in range(len(self.formats) - 1, -1, -1):
                format_tag, previous = self.formats[index]
                if format_tag == tag:
                    self.format = previous
                    del self.formats[index:]
                    return
        for index in range(len(self.targets) - 1, -1, -1):
            target_tag, previous_target = self.targets[index]
            if target_tag == tag:
                self.target = previous_target
                del self.targets[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.isspace() and not any(tag in self._block_tags or tag == "li" for tag, _ in self.targets):
            return
        self._append_text(data)

    def document(self) -> dict[str, Any]:
        return {
            "root": {
                "type": "root",
                "version": 1,
                "format": "",
                "indent": 0,
                "direction": None,
                "children": self.children,
            }
        }


def markdown_to_lexical(source: str) -> dict[str, Any]:
    """Serialize Markdown into the shared Payload Lexical body contract."""
    html = markdown.markdown(
        str(source or ""),
        extensions=["extra", "sane_lists", "fenced_code"],
        output_format="html5",
    )
    parser = _LexicalParser()
    parser.feed(html)
    parser.close()
    document = parser.document()
    if not lexical_text(document):
        raise ValueError("article body must contain readable text")
    return document


def lexical_text(value: Any) -> str:
    """Extract readable text from a Payload Lexical document without HTML."""
    parts: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            text = node.get("text")
            if isinstance(text, str):
                parts.append(text)
            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    visit(child)
                if node.get("type") in {"paragraph", "heading", "listitem", "quote"}:
                    parts.append(" ")
            if isinstance(node.get("root"), dict):
                visit(node["root"])
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return " ".join("".join(parts).split())
