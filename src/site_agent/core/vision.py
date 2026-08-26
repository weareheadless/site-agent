"""Optional OpenAI-compatible vision client for image art direction."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from urllib.parse import urljoin
from typing import Any

from .llm import LLMError, _http_post


class VisionClient:
    """Analyze public or data-URL images without changing the text LLM client."""

    def __init__(self, config: dict[str, Any], env: dict[str, str] | None = None):
        import os

        from ..config import resolve_secret

        cfg = config.get("vision") or {}
        self.base_url = str(cfg.get("base_url", "")).rstrip("/")
        self.model = str(cfg.get("model", ""))
        self.timeout = float(cfg.get("timeout_seconds", 90))
        self.max_tokens = int(cfg.get("max_tokens", 700))
        self.api_key = resolve_secret(config, "vision_api_key", os.environ if env is None else env)

    def analyze(self, image_url: str, instruction: str) -> str:
        """Return an image analysis from an OpenAI-compatible multimodal endpoint."""
        if not self.api_key:
            raise LLMError("vision_api_key not configured")
        if not self.base_url or not self.model:
            raise LLMError("vision provider is not configured")
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }],
            "max_tokens": self.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = _http_post(
            f"{self.base_url}/chat/completions", headers, payload, self.timeout
        )
        try:
            content = response["choices"][0]["message"].get("content")
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected vision response shape: {str(response)[:200]}") from exc
        if not (content or "").strip():
            raise LLMError("vision model returned an empty completion")
        return content


def site_image_context(config: dict[str, Any], clone, memory=None) -> str:
    """Analyze a small set of public site images for a builder brief.

    Vision is deliberately best-effort: a provider outage or unsupported model
    must never prevent an ordinary site build.
    """
    cfg = config.get("vision") or {}
    if not cfg.get("enabled"):
        return ""
    site = config.get("site") or {}
    base = str(site.get("preview_url") or "").strip()
    if not base:
        return ""
    try:
        from pathlib import Path

        html_files = sorted(Path(clone).glob("*.html"))[:8]
        html = "\n".join(p.read_text(errors="ignore") for p in html_files)
        sources = list(dict.fromkeys(re.findall(
            r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", html, re.I
        )))
        css_files = sorted(Path(clone).glob("*.css"))[:4]
        css = "\n".join(p.read_text(errors="ignore") for p in css_files)
        sources.extend(re.findall(r"url\([\"']?([^\"')]+)[\"']?\)", css, re.I))
        sources = list(dict.fromkeys(sources))
        urls = [urljoin(base, src) for src in sources
                if not src.startswith(("data:", "#", "mailto:"))
                and re.search(r"\.(?:avif|gif|jpe?g|png|webp)(?:[?#].*)?$", src, re.I)]
        urls = urls[:int(cfg.get("max_images", 6))]
        if not urls:
            return ""
        client = VisionClient(config)
        analyses_by_url = {}
        instruction = (
            "Analyze this website image for a visual designer. Return concise plain text "
            "covering subject, focal point, text-safe space, dominant colors, suitable "
            "crop, lighting direction, and one or two tasteful depth or motion treatments. "
            "Mention what to avoid on mobile. Do not invent context outside the image."
        )
        def analyze(url: str) -> tuple[str, str] | None:
            try:
                return url, client.analyze(url, instruction)
            except LLMError:
                return None

        configured_workers = int(cfg.get("parallelism", 4))
        workers = max(1, min(len(urls), configured_workers))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(analyze, url) for url in urls]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    analyses_by_url[result[0]] = result[1]
        if not analyses_by_url:
            return ""
        analyses = [f"{url}:\n{analyses_by_url[url]}" for url in urls if url in analyses_by_url]
        return "Image art direction (vision analysis; use as evidence, not a mandate):\n" + "\n\n".join(analyses)
    except (OSError, ValueError, TypeError):
        return ""
