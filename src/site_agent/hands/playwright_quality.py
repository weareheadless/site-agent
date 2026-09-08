"""Concrete Chromium inspection for immutable static design artifacts."""

from __future__ import annotations

import hashlib
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections.abc import Sequence
from typing import Any, Mapping
from urllib.parse import urlsplit


class PlaywrightQualityError(RuntimeError):
    """Playwright could not inspect a static artifact."""


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return


class _ArtifactServer:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> "_ArtifactServer":
        if not self.root.is_dir():
            raise PlaywrightQualityError(f"browser artifact directory is missing: {self.root}")
        handler = partial(_QuietHandler, directory=str(self.root))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="design-lab-artifact-server", daemon=True)
        self.thread.start()
        return self

    @property
    def origin(self) -> str:
        if self.server is None:
            raise PlaywrightQualityError("artifact server is not running")
        return f"http://127.0.0.1:{self.server.server_port}"

    def __exit__(self, *_args: Any) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)


def _routes(output_dir: Path) -> list[str]:
    routes = [
        str(path.relative_to(output_dir)).replace("\\", "/")
        for path in output_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".html", ".htm"}
    ]
    return sorted(routes, key=lambda route: (route not in {"index.html", "index.htm"}, route))


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_local_url(value: str, origin: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme in {"about", "blob", "data"}:
        return True
    local = urlsplit(origin)
    return parsed.scheme == local.scheme and parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == local.port


def _page_metrics(page: Any, viewport: Mapping[str, int]) -> dict[str, Any]:
    return dict(page.evaluate(
        r"""
        (() => {
          const parseColor = (value) => {
            const match = String(value || '').match(/rgba?\(([^)]+)\)/i);
            if (!match) return null;
            const parts = match[1].split(',').map((part) => Number.parseFloat(part.trim()));
            if (parts.length < 3 || parts.some((part, index) => index < 3 && !Number.isFinite(part))) return null;
            return { r: parts[0], g: parts[1], b: parts[2], a: Number.isFinite(parts[3]) ? parts[3] : 1 };
          };
          const blend = (foreground, background) => {
            const alpha = Math.max(0, Math.min(1, foreground.a));
            return {
              r: foreground.r * alpha + background.r * (1 - alpha),
              g: foreground.g * alpha + background.g * (1 - alpha),
              b: foreground.b * alpha + background.b * (1 - alpha),
              a: 1,
            };
          };
          const backgroundFor = (element) => {
            let result = { r: 255, g: 255, b: 255, a: 1 };
            const chain = [];
            for (let current = element; current && current !== document.documentElement; current = current.parentElement) chain.push(current);
            for (const current of chain.reverse()) {
              const color = parseColor(getComputedStyle(current).backgroundColor);
              if (color) result = blend(color, result);
            }
            return result;
          };
          const channel = (value) => {
            const normalized = value / 255;
            return normalized <= 0.03928 ? normalized / 12.92 : Math.pow((normalized + 0.055) / 1.055, 2.4);
          };
          const luminance = (color) => 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
           const contrast = (foreground, background) => {
             const light = Math.max(luminance(foreground), luminance(background));
             const dark = Math.min(luminance(foreground), luminance(background));
             return (light + 0.05) / (dark + 0.05);
           };
          const hiddenForQuality = (element) => {
            const style = getComputedStyle(element);
            return Boolean(element.closest('[aria-hidden="true"], [hidden]')) ||
              style.display === 'none' || style.visibility === 'hidden' ||
              (style.position === 'absolute' && style.width === '1px' && style.height === '1px' && style.overflow === 'hidden');
          };
           const visibleText = Array.from(document.querySelectorAll('body *')).filter((element) => {
             const rect = element.getBoundingClientRect();
             return !hiddenForQuality(element) && rect.width > 0 && rect.height > 0 && Array.from(element.childNodes).some((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
           });
          const contrastFailures = visibleText.map((element) => {
            const style = getComputedStyle(element);
            const foreground = parseColor(style.color);
            if (!foreground) return null;
            const background = backgroundFor(element);
            const ratio = contrast(foreground, background);
            const size = Number.parseFloat(style.fontSize) || 16;
            const large = size >= 24 || (size >= 18.66 && Number.parseInt(style.fontWeight, 10) >= 700);
            const minimum = large ? 3 : 4.5;
            if (ratio >= minimum) return null;
            return {
              tag: element.tagName.toLowerCase(),
              text: element.textContent.trim().slice(0, 120),
              ratio: Number(ratio.toFixed(2)),
              minimum,
              color: style.color,
              background: `rgb(${Math.round(background.r)}, ${Math.round(background.g)}, ${Math.round(background.b)})`,
            };
          }).filter(Boolean).slice(0, 30);
           const fontChecks = Array.from(new Set(visibleText.map((element) => getComputedStyle(element).fontFamily).filter(Boolean))).map((family) => ({
             family,
             loaded: document.fonts ? document.fonts.check(`16px ${family}`) : true,
           }));
           const fontLoadFailures = fontChecks.filter((item) => !item.loaded);
           const lowResolutionImages = Array.from(document.images).map((image) => {
             const rect = image.getBoundingClientRect();
             if (!image.naturalWidth || !rect.width || image.naturalWidth >= rect.width * 1.1) return null;
             return { src: image.currentSrc || image.src || '', natural_width: image.naturalWidth, rendered_width: Math.round(rect.width) };
           }).filter(Boolean).slice(0, 30);
           const textWrapFailures = Array.from(document.querySelectorAll('main p, main li, main blockquote')).map((element) => {
             if (hiddenForQuality(element)) return null;
             const text = element.textContent.trim();
             const words = text.match(/\S+/g) || [];
             if (words.length < 8) return null;
             const lines = new Map();
             const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
             let node;
             while ((node = walker.nextNode())) {
               const source = node.textContent || '';
               const matcher = /\S+/g;
               let match;
               while ((match = matcher.exec(source))) {
                 const range = document.createRange();
                 range.setStart(node, match.index);
                 range.setEnd(node, match.index + match[0].length);
                 const rect = range.getBoundingClientRect();
                 if (rect.width <= 0 || rect.height <= 0) continue;
                 const key = Math.round(rect.top);
                 lines.set(key, (lines.get(key) || 0) + 1);
               }
             }
             const counts = Array.from(lines.values());
             const rect = element.getBoundingClientRect();
             const style = getComputedStyle(element);
             if (counts.length < 4 || Math.max(...counts) > 1) return null;
             return {
               tag: element.tagName.toLowerCase(),
               text: text.slice(0, 160),
               lines: counts.length,
               max_words_per_line: Math.max(...counts),
               width: Math.round(rect.width),
               font_size: style.fontSize,
             };
           }).filter(Boolean).slice(0, 20);
           const motion = {
            preference: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'reduce' : 'no-preference',
            active_animations: Array.from(document.getAnimations()).filter((animation) => animation.playState === 'running').length,
          };
          return {
          overflow: document.documentElement.scrollWidth > window.innerWidth + 1 || document.body.scrollWidth > window.innerWidth + 1,
           clipping: Array.from(document.querySelectorAll('main img, main a, main button, main h1, main h2, main h3')).filter((element) => {
             if (element.tagName === 'IMG') {
               let current = element.parentElement;
               while (current) {
                 const style = getComputedStyle(current);
                 if (style.overflowX === 'hidden' || style.overflowY === 'hidden' || style.overflow === 'clip') return false;
                 current = current.parentElement;
               }
             }
             const rect = element.getBoundingClientRect();
             return rect.width > 0 && (rect.left < -1 || rect.right > window.innerWidth + 1);
           }).slice(0, 20).map((element) => element.tagName.toLowerCase()),
           fixed_header_overlap: (() => {
             const header = document.querySelector('header');
             const main = document.querySelector('main');
             if (!header || !main) return false;
             const headerStyle = getComputedStyle(header);
             if (!['fixed', 'sticky'].includes(headerStyle.position)) return false;
             const headerRect = header.getBoundingClientRect();
              const first = Array.from(main.querySelectorAll('h1, h2, h3, p, a, button')).find((element) => {
                if (hiddenForQuality(element)) return false;
                const rect = element.getBoundingClientRect();
                const style = getComputedStyle(element);
               return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
             });
             if (!first) return false;
             const rect = first.getBoundingClientRect();
             if (headerRect.bottom <= rect.top || headerRect.bottom >= window.innerHeight) return false;
             return {
               header_position: headerStyle.position,
               header_rect: {top: Math.round(headerRect.top), bottom: Math.round(headerRect.bottom), left: Math.round(headerRect.left), right: Math.round(headerRect.right)},
               target_selector: first.tagName.toLowerCase() + (first.id ? `#${first.id}` : first.className ? `.${String(first.className).split(/\s+/)[0]}` : ''),
               target_rect: {top: Math.round(rect.top), bottom: Math.round(rect.bottom), left: Math.round(rect.left), right: Math.round(rect.right)}
             };
           })(),
          heading_count: document.querySelectorAll('h1').length,
          landmarks: {
            header: Boolean(document.querySelector('header')),
            main: Boolean(document.querySelector('main')),
            footer: Boolean(document.querySelector('footer'))
          },
           accessibility: [
             ...Array.from(document.querySelectorAll('img')).filter((element) => !element.hasAttribute('alt') && !element.closest('[aria-hidden="true"]') && !['presentation', 'none'].includes(element.getAttribute('role'))).map(() => 'image_missing_alt'),
            ...Array.from(document.querySelectorAll('a')).filter((element) => !element.textContent.trim() && !element.getAttribute('aria-label')).map(() => 'link_missing_name'),
            ...Array.from(document.querySelectorAll('button')).filter((element) => !element.textContent.trim() && !element.getAttribute('aria-label')).map(() => 'button_missing_name')
          ],
           reduced_motion: motion,
           contrast_failures: contrastFailures,
            font_load_failures: fontLoadFailures,
            font_checks: fontChecks,
           low_resolution_images: lowResolutionImages,
           text_wrap_failures: textWrapFailures
           };
        })()
        """,
    ))


def _keyboard_metrics(page: Any) -> dict[str, Any]:
    focusable_count = int(page.locator("a, button, input, select, textarea, [tabindex]").count())
    if focusable_count:
        page.keyboard.press("Tab")
    return dict(page.evaluate(
        """
        (() => {
          const active = document.activeElement;
          if (!active || active === document.body) return { focusable_count: document.querySelectorAll('a, button, input, select, textarea, [tabindex]').length, focus_visible: false };
          const style = getComputedStyle(active);
          return {
            focusable_count: document.querySelectorAll('a, button, input, select, textarea, [tabindex]').length,
            focus_visible: style.outlineStyle !== 'none' || style.outlineWidth !== '0px' || style.boxShadow !== 'none',
            active_tag: active.tagName.toLowerCase()
          };
        })()
        """,
    ))


def _motion_snapshot(page: Any) -> dict[str, Any]:
    """Capture observable runtime motion state without treating WAAPI as GSAP."""
    return dict(page.evaluate(
        """
        (() => {
          const engine = window.gsap || window.GSAP || null;
          const triggerApi = window.ScrollTrigger || (engine && engine.plugins && engine.plugins.scrollTrigger) || null;
          let activeTweens = null;
          let totalTweens = null;
          try {
            const children = engine && engine.globalTimeline && engine.globalTimeline.getChildren
              ? engine.globalTimeline.getChildren(true, true, true) : null;
            if (children) {
              totalTweens = children.length;
              activeTweens = children.filter((item) => item && item.isActive && item.isActive()).length;
            }
          } catch (_error) {}
          let scrollTriggers = null;
          try {
            scrollTriggers = triggerApi && triggerApi.getAll ? triggerApi.getAll().length : null;
          } catch (_error) {}
          const motionNodes = Array.from(document.querySelectorAll(
            '[data-motion], [data-animate], [data-reveal], [data-scroll], main *'
          )).filter((element) => {
            const style = getComputedStyle(element);
            return style.transform !== 'none' || style.opacity !== '1' || style.animationName !== 'none' || style.transitionProperty !== 'all';
          }).slice(0, 120);
          const nodeState = motionNodes.map((element, index) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return {
              index,
              tag: element.tagName.toLowerCase(),
              transform: style.transform,
              opacity: style.opacity,
              top: Math.round(rect.top),
              left: Math.round(rect.left),
            };
          });
          return {
            scroll_y: Math.round(window.scrollY),
            scroll_height: document.documentElement.scrollHeight,
            gsap_present: Boolean(engine),
            gsap_active_tweens: activeTweens,
            gsap_total_tweens: totalTweens,
            scroll_trigger_count: scrollTriggers,
            css_waapi_running: Array.from(document.getAnimations()).filter((animation) => animation.playState === 'running').length,
            motion_nodes: nodeState,
          };
        })()
        """,
    ))


def _interaction_metrics(
    page: Any,
    *,
    before_screenshot: Path | None = None,
    after_screenshot: Path | None = None,
) -> dict[str, Any]:
    """Exercise bounded local controls and record DOM and visual state deltas."""
    controls = page.locator("button, [role='button'], summary")
    try:
        count = min(int(controls.count()), 6)
    except Exception:  # noqa: BLE001 - browser adapters should return evidence
        count = 0
    before = dict(page.evaluate(
        """
        () => ({
          expanded: Array.from(document.querySelectorAll('[aria-expanded]')).map((item) => item.getAttribute('aria-expanded')),
          dialogs: document.querySelectorAll('[role="dialog"], dialog[open]').length,
          details: Array.from(document.querySelectorAll('details')).map((item) => item.open),
          active: document.activeElement ? document.activeElement.tagName.toLowerCase() : '',
        })
        """,
    ))
    visual: dict[str, Any] = {}
    if before_screenshot is not None:
        try:
            page.screenshot(path=str(before_screenshot), full_page=True)
            visual["before_screenshot_path"] = str(before_screenshot)
            visual["before_screenshot_hash"] = _hash_file(before_screenshot)
        except Exception as exc:  # noqa: BLE001 - retain interaction diagnostics
            visual["error"] = f"before screenshot: {str(exc)[:240]}"
    attempted = 0
    errors: list[str] = []
    for index in range(count):
        try:
            controls.nth(index).click(timeout=2_000)
            page.wait_for_timeout(120)
            attempted += 1
        except Exception as exc:  # noqa: BLE001 - retain per-control evidence
            errors.append(str(exc)[:240])
    after = dict(page.evaluate(
        """
        () => ({
          expanded: Array.from(document.querySelectorAll('[aria-expanded]')).map((item) => item.getAttribute('aria-expanded')),
          dialogs: document.querySelectorAll('[role="dialog"], dialog[open]').length,
          details: Array.from(document.querySelectorAll('details')).map((item) => item.open),
          active: document.activeElement ? document.activeElement.tagName.toLowerCase() : '',
        })
        """,
    ))
    if after_screenshot is not None:
        try:
            page.screenshot(path=str(after_screenshot), full_page=True)
            visual["after_screenshot_path"] = str(after_screenshot)
            visual["after_screenshot_hash"] = _hash_file(after_screenshot)
        except Exception as exc:  # noqa: BLE001 - retain interaction diagnostics
            visual["error"] = f"after screenshot: {str(exc)[:240]}"
    if visual.get("before_screenshot_hash") and visual.get("after_screenshot_hash"):
        visual["changed"] = visual["before_screenshot_hash"] != visual["after_screenshot_hash"]
    return {
        "controls_found": count,
        "attempted": attempted,
        "state_changed": before != after,
        "before": before,
        "after": after,
        "errors": errors,
        "visual": visual,
    }


class PlaywrightQualityAdapter:
    """Inspect every static route at one viewport and save screenshots externally."""

    def __init__(
        self,
        screenshot_root: str | Path,
        *,
        variant: str = "candidate",
        routes: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.screenshot_root = Path(screenshot_root).expanduser().resolve()
        self.variant = str(variant or "candidate")
        self.routes = tuple(str(route) for route in routes) if routes is not None else None
        self.env = dict(env) if env is not None else None

    def inspect(self, output_dir: Path, viewport: Mapping[str, int]) -> Mapping[str, Any]:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise PlaywrightQualityError("Playwright is not installed; install the design-lab browser extra") from exc

        output = Path(output_dir).expanduser().resolve()
        routes = _routes(output)
        if self.routes is not None:
            routes = []
            for route_name in self.routes:
                relative = str(route_name or "").replace("\\", "/").lstrip("/")
                target = (output / relative).resolve()
                if not relative or any(part in {"", ".", ".."} for part in relative.split("/")) or output not in target.parents or target.is_symlink() or not target.is_file() or target.suffix.lower() not in {".html", ".htm"}:
                    raise PlaywrightQualityError(f"browser route is not a safe HTML artifact: {route_name}")
                routes.append(relative)
            routes = list(dict.fromkeys(routes))
        if not routes:
            raise PlaywrightQualityError("browser artifact has no HTML routes")
        viewport_name = str(viewport.get("name") or f"{viewport.get('width')}x{viewport.get('height')}")
        width = max(1, int(viewport.get("width", 1440)))
        height = max(1, int(viewport.get("height", 1000)))
        screenshot_dir = self.screenshot_root / self.variant / viewport_name
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        all_console_errors: list[dict[str, str]] = []
        all_failed_requests: list[dict[str, str]] = []
        external_requests: list[dict[str, str]] = []
        route_results: list[dict[str, Any]] = []

        with _ArtifactServer(output) as server, sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True, env=self.env)
            except Exception as exc:  # noqa: BLE001 - expose browser setup as incomplete evidence
                raise PlaywrightQualityError(f"Chromium could not launch: {str(exc)[:300]}") from exc
            try:
                context = browser.new_context(viewport={"width": width, "height": height}, reduced_motion="no-preference")

                def route_handler(route: Any) -> None:
                    request_url = route.request.url
                    if _is_local_url(request_url, server.origin):
                        route.continue_()
                        return
                    external_requests.append({"url": request_url[:500], "error": "external request blocked"})
                    route.abort()

                context.route("**/*", route_handler)
                for route_name in routes:
                    page = context.new_page()
                    console_errors: list[dict[str, str]] = []
                    failed_requests: list[dict[str, str]] = []
                    def on_console(message: Any) -> None:
                        if message.type == "error" and not message.text.startswith("Failed to load resource:"):
                            console_errors.append({"type": message.type, "text": message.text[:500]})

                    def on_response(response: Any) -> None:
                        if _is_local_url(response.url, server.origin) and response.status >= 400:
                            if not any(item["url"] == response.url[:500] for item in failed_requests):
                                failed_requests.append({"url": response.url[:500], "error": f"HTTP {response.status}"})

                    def on_request_failed(request: Any) -> None:
                        item = {"url": request.url[:500], "error": str(request.failure or "request failed")[:300]}
                        if _is_local_url(request.url, server.origin):
                            if not any(existing["url"] == item["url"] for existing in failed_requests):
                                failed_requests.append(item)
                        else:
                            item["error"] = "external request blocked"
                            external_requests.append(item)

                    page.on("console", on_console)
                    page.on("pageerror", lambda error: console_errors.append({"type": "pageerror", "text": str(error)[:500]}))
                    page.on("response", on_response)
                    page.on("requestfailed", on_request_failed)
                    page_url = f"{server.origin}/{route_name}"
                    result: dict[str, Any] = {"route": route_name, "url": f"/{route_name}"}
                    motion_results: dict[str, Any] = {}
                    try:
                        for preference in ("no-preference", "reduce"):
                            page.emulate_media(reduced_motion=preference)
                            page.goto(page_url, wait_until="networkidle", timeout=30_000)
                            metrics = _page_metrics(page, viewport)
                            motion_results[preference] = {
                                **metrics.pop("reduced_motion", {}),
                                "runtime": _motion_snapshot(page),
                            }
                            if preference == "no-preference":
                                screenshot = screenshot_dir / (route_name.removesuffix(".html").replace("/", "__") + ".png")
                                # Capture the resting composition before the
                                # keyboard and interaction probes change focus,
                                # open menus, or otherwise alter the page state.
                                page.wait_for_timeout(1_800)
                                page.screenshot(path=str(screenshot), full_page=True)
                                result["screenshot_path"] = str(screenshot)
                                result["screenshot_hash"] = _hash_file(screenshot)
                            metrics["keyboard"] = _keyboard_metrics(page)
                            scroll_states: list[dict[str, Any]] = []
                            scroll_height = int(page.evaluate("() => document.documentElement.scrollHeight") or height)
                            positions = tuple(dict.fromkeys((0, max(0, scroll_height // 2 - height // 2), max(0, scroll_height - height))))
                            for position in positions:
                                page.evaluate("(value) => window.scrollTo(0, value)", position)
                                page.wait_for_timeout(180)
                                scroll_states.append({"position": position, **_motion_snapshot(page)})
                            page.evaluate("() => window.scrollTo(0, 0)")
                            page.wait_for_timeout(80)
                            metrics["scroll_states"] = scroll_states
                            # The interaction probe deliberately clicks the menu
                            # toggle and other buttons. Keep the resting
                            # composition separate, then compare bounded visual
                            # evidence before and after the controls run.
                            interaction_before = None
                            interaction_after = None
                            if preference == "no-preference":
                                stem = route_name.removesuffix(".html").replace("/", "__") or "index"
                                interaction_before = screenshot_dir / f"{stem}-interaction-before.png"
                                interaction_after = screenshot_dir / f"{stem}-interaction-after.png"
                            interaction_state = _interaction_metrics(
                                page,
                                before_screenshot=interaction_before,
                                after_screenshot=interaction_after,
                            )
                            if preference == "no-preference":
                                result.update(metrics)
                                result["interaction_state"] = interaction_state
                        result["motion_preferences"] = motion_results
                    except PlaywrightTimeoutError:
                        result.update({"console_errors": console_errors, "failed_requests": failed_requests, "error": "page load timed out"})
                    except Exception as exc:  # noqa: BLE001 - one route should leave diagnostic evidence
                        result.update({"console_errors": console_errors, "failed_requests": failed_requests, "error": str(exc)[:500]})
                    finally:
                        result["console_errors"] = console_errors
                        result["failed_requests"] = failed_requests
                        if motion_results:
                            result["motion_preferences"] = motion_results
                        all_console_errors.extend({"route": route_name, **item} for item in console_errors)
                        all_failed_requests.extend({"route": route_name, **item} for item in failed_requests)
                        page.close()
                    route_results.append(result)
                context.close()
            finally:
                browser.close()
        return {
            "status": "failed" if all_console_errors or all_failed_requests or any(item.get("error") for item in route_results) else "passed",
            "viewport": {"name": viewport_name, "width": width, "height": height},
            "routes": route_results,
            "console_errors": all_console_errors,
            "failed_requests": all_failed_requests,
            "external_requests": list({(item["url"], item["error"]): item for item in external_requests}.values()),
            "overflow": [item["route"] for item in route_results if item.get("overflow")],
            "clipping": [item["route"] for item in route_results if item.get("clipping")],
            "fixed_header_overlap": [item["route"] for item in route_results if item.get("fixed_header_overlap")],
            "scroll_states": [
                {"route": item["route"], "states": item.get("scroll_states") or []}
                for item in route_results if item.get("scroll_states")
            ],
            "interaction_states": [
                {"route": item["route"], "state": item.get("interaction_state") or {}}
                for item in route_results if item.get("interaction_state")
            ],
            "accessibility": [
                {"route": item["route"], "findings": item.get("accessibility")}
                for item in route_results if item.get("accessibility")
            ],
        }


__all__ = ["PlaywrightQualityAdapter", "PlaywrightQualityError"]
