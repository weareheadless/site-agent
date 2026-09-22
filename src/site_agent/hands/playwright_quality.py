"""Concrete Chromium inspection for immutable static design artifacts."""

from __future__ import annotations

import hashlib
import threading
import time
from contextlib import nullcontext
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections.abc import Callable, Sequence
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


def _is_allowed_url(value: str, origins: Sequence[str]) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme in {"about", "blob", "data"}:
        return True
    for origin in origins:
        if _is_local_url(value, origin):
            return True
        allowed = urlsplit(origin)
        if parsed.scheme == allowed.scheme and parsed.netloc == allowed.netloc:
            return True
    return False


class _OwnerFrameSurface:
    """Small page-like adapter for the sandboxed owner preview iframe.

    The iframe is the owner-visible viewport. Do not emulate a full-page
    screenshot by resizing it: that changes viewport units, responsive layout,
    and scroll-linked animation geometry before evidence is captured. Callers
    can scroll this surface and capture a sequence of ordinary viewport frames.
    """

    def __init__(self, shell: Any, frame: Any) -> None:
        self._shell = shell
        self._frame = frame

    def locator(self, selector: str) -> Any:
        return self._frame.locator(selector)

    def evaluate(self, expression: str, arg: Any = None) -> Any:
        return self._frame.evaluate(expression, arg)

    def wait_for_timeout(self, milliseconds: float) -> None:
        self._frame.wait_for_timeout(milliseconds)

    @property
    def keyboard(self) -> Any:
        return self._shell.keyboard

    def screenshot(self, *, path: str | Path, full_page: bool = False) -> None:
        # ``full_page`` is accepted for compatibility with the artifact-server
        # page adapter. The owner surface must never resize its iframe to
        # satisfy that request; the owner does not see an expanded document.
        iframe = self._shell.locator("#preview-iframe")
        # Playwright's Locator.screenshot captures the locator's viewport and
        # does not accept Page.screenshot's full_page option. The iframe itself
        # is the owner-visible surface, so omitting that option is the honest
        # equivalent of a viewport capture.
        iframe.screenshot(path=str(path))


def _page_metrics(page: Any, viewport: Mapping[str, int]) -> dict[str, Any]:
    return dict(page.evaluate(
        r"""
        (() => {
          const descendantFingerprint = (element) => Array.from(element.querySelectorAll('*')).slice(0, 80).map((node) => {
            const style = getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            return [
              node.tagName.toLowerCase(),
              Number(rect.width.toFixed(2)),
              Number(rect.height.toFixed(2)),
              style.transform,
              style.opacity,
              style.visibility,
              style.backgroundImage,
              style.filter,
              style.getPropertyValue('--lamp-x'),
              style.getPropertyValue('--lamp-y'),
              style.getPropertyValue('--lamp-r'),
              style.getPropertyValue('--light-budget'),
            ].join(':');
          }).join(';');
           const signatureFingerprint = (element) => {
             const style = getComputedStyle(element);
             return [
              style.transform,
              style.opacity,
              style.backgroundImage,
              style.filter,
              style.getPropertyValue('--lamp-x'),
              style.getPropertyValue('--lamp-y'),
              style.getPropertyValue('--lamp-r'),
              style.getPropertyValue('--light-budget'),
               descendantFingerprint(element),
             ].join('|');
           };
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
            const compositionElements = Array.from(new Set(Array.from(document.querySelectorAll(
              '[data-ada-asset-id], [data-asset-id], [data-ada-composition-role]'
            )))).map((element) => {
              const rect = element.getBoundingClientRect();
              const style = getComputedStyle(element);
              const assetId = element.getAttribute('data-ada-asset-id') || element.getAttribute('data-asset-id') || '';
              const assetHash = element.getAttribute('data-ada-asset-sha256') || element.getAttribute('data-asset-sha256') || '';
              const role = element.getAttribute('data-ada-composition-role') || element.getAttribute('data-role') || '';
              const focalCoverage = Number.parseFloat(element.getAttribute('data-ada-focal-coverage') || '');
              if (rect.width <= 0 || rect.height <= 0 || style.display === 'none' || style.visibility === 'hidden') return null;
             return {
               tag: element.tagName.toLowerCase(),
               role,
               asset_id: assetId,
               asset_sha256: assetHash,
               src: element.currentSrc || element.src || element.getAttribute('href') || '',
               intrinsic_width: Number(element.naturalWidth || 0),
               intrinsic_height: Number(element.naturalHeight || 0),
               object_fit: style.objectFit || '',
               object_position: style.objectPosition || '',
               container_box: (() => {
                 const container = element.closest('[data-ada-composition-container], section, main');
                 if (!container) return null;
                 const containerRect = container.getBoundingClientRect();
                 return {
                   x: Number(containerRect.x.toFixed(2)),
                   y: Number(containerRect.y.toFixed(2)),
                   width: Number(containerRect.width.toFixed(2)),
                   height: Number(containerRect.height.toFixed(2)),
                 };
               })(),
               ...(Number.isFinite(focalCoverage) ? { focal_coverage: focalCoverage } : {}),
               box: {
                  x: Number(rect.x.toFixed(2)),
                  y: Number(rect.y.toFixed(2)),
                  width: Number(rect.width.toFixed(2)),
                  height: Number(rect.height.toFixed(2)),
                },
              };
            }).filter(Boolean).slice(0, 100);
            const layoutShifts = (performance.getEntriesByType('layout-shift') || [])
              .filter((entry) => !entry.hadRecentInput)
              .map((entry) => ({ value: Number(Number(entry.value || 0).toFixed(4)) }))
              .filter((entry) => entry.value > 0)
              .slice(0, 30);
            const meaningfulContentBottom = Math.max(0, ...Array.from(document.querySelectorAll(
              'main h1, main h2, main h3, main p, main li, main a, main button, main input, main select, main textarea'
            )).map((element) => {
              const rect = element.getBoundingClientRect();
              return rect.bottom + window.scrollY;
            }).filter((value) => Number.isFinite(value)));
            const signatureBehaviors = Array.from(document.querySelectorAll('[data-ada-signature-behavior]')).map((element) => {
              const style = getComputedStyle(element);
              const inlineStyle = element.style || {};
              const svgProgress = Boolean(
                inlineStyle.strokeDashoffset || inlineStyle.strokeDasharray ||
                style.strokeDashoffset !== '0px' || style.strokeDasharray !== 'none'
              );
              return {
                id: element.getAttribute('data-ada-signature-behavior') || '',
                 // Candidate-authored state is not evidence. The host derives
                 // observation from rendered deltas collected by the probes.
                 state: style.transform !== 'none' || svgProgress ? 'rendered' : 'unobserved',
                trigger: element.getAttribute('data-ada-behavior-trigger') || 'page-load',
                fingerprint: signatureFingerprint(element),
              };
            }).filter((item) => item.id).slice(0, 20);
            const journeyConditions = Array.from(document.querySelectorAll('[data-ada-journey-condition]')).map((element) => {
              const visualNode = [element, ...Array.from(element.querySelectorAll('*'))].find((candidate) => {
                const rect = candidate.getBoundingClientRect();
                const style = getComputedStyle(candidate);
                return rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
                  style.visibility !== 'hidden' && Number.parseFloat(style.opacity || '1') > 0;
              });
              const style = getComputedStyle(element);
              // Journey markers may live on decorative wrappers or SVGs that
              // are aria-hidden from assistive technology. Visibility here is
              // a visual contract, so inspect the marker or a rendered child
              // rather than applying the accessibility-only filter used by
              // text and landmark checks.
               const visible = Boolean(visualNode);
               const rect = element.getBoundingClientRect();
               return {
                condition_id: element.getAttribute('data-ada-journey-condition') || '',
                scene_id: element.getAttribute('data-ada-journey-scene') || '',
                trigger: element.getAttribute('data-ada-journey-trigger') || '',
                 // State and completion claims from the candidate are never
                 // copied into host evidence.
                 state: visible ? 'rendered' : 'not-rendered',
                 completion: '',
                 visible,
                 interactive: Boolean(element.matches('a, button, input, select, textarea, [tabindex]')),
                 opacity: style.opacity,
                 rendered_fingerprint: {
                   box: {
                     x: Number(rect.x.toFixed(2)),
                     y: Number(rect.y.toFixed(2)),
                     width: Number(rect.width.toFixed(2)),
                     height: Number(rect.height.toFixed(2)),
                   },
                   transform: style.transform,
                   opacity: style.opacity,
                   visibility: style.visibility,
                   filter: style.filter,
                   text: (element.innerText || element.textContent || '').trim().slice(0, 400),
                 },
               };
            }).filter((item) => item.condition_id).slice(0, 100);
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
           };
          return {
           overflow: document.documentElement.scrollWidth > window.innerWidth + 1 || document.body.scrollWidth > window.innerWidth + 1,
           document_height: Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0),
           meaningful_content_bottom: meaningfulContentBottom,
           viewport_height: window.innerHeight,
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
            composition_elements: compositionElements,
             layout_shifts: layoutShifts,
             signature_behaviors: signatureBehaviors,
             journey_conditions: journeyConditions,
             critical_content_visible: Boolean(document.querySelector('main') && document.querySelector('main').innerText.trim()),
            text_wrap_failures: textWrapFailures
           };
        })()
        """,
    ))


def _keyboard_metrics(page: Any) -> dict[str, Any]:
    focusable = page.locator("a, button, input, select, textarea, [tabindex]")
    focusable_count = int(focusable.count())
    if focusable_count:
        # Send the key through the document's locator rather than the owner
        # shell's keyboard.  The browser preview is an iframe; shell-level Tab
        # can focus the iframe element itself and leave the rendered document's
        # activeElement at body, producing a false focus-visibility failure.
        focusable.first.press("Tab")
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
    """Capture rendered state for scroll/interaction comparisons.

    This intentionally does not inspect GSAP, ScrollTrigger, WAAPI, or browser
    animation counts. Those are implementation details and are not evidence
    that a visitor saw a behavior.
    """
    return dict(page.evaluate(
        """
        (() => {
          const descendantFingerprint = (element) => Array.from(element.querySelectorAll('*')).slice(0, 80).map((node) => {
            const style = getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            return [
              node.tagName.toLowerCase(),
              Number(rect.width.toFixed(2)),
              Number(rect.height.toFixed(2)),
              style.transform,
              style.opacity,
              style.visibility,
              style.backgroundImage,
              style.filter,
              style.getPropertyValue('--lamp-x'),
              style.getPropertyValue('--lamp-y'),
              style.getPropertyValue('--lamp-r'),
              style.getPropertyValue('--light-budget'),
            ].join(':');
          }).join(';');
          const signatureFingerprint = (element) => {
            const style = getComputedStyle(element);
            return [
              style.transform,
              style.opacity,
              style.backgroundImage,
              style.filter,
              style.getPropertyValue('--lamp-x'),
              style.getPropertyValue('--lamp-y'),
              style.getPropertyValue('--lamp-r'),
              style.getPropertyValue('--light-budget'),
              descendantFingerprint(element),
            ].join('|');
          };
          const motionNodes = Array.from(document.querySelectorAll(
            '[data-motion], [data-animate], [data-reveal], [data-scroll], main *'
          )).filter((element) => {
            const style = getComputedStyle(element);
            return style.transform !== 'none' || style.opacity !== '1' || style.animationName !== 'none' || style.transitionProperty !== 'all';
          }).slice(0, 120);
           const nodeState = motionNodes.map((element, index) => {
             const style = getComputedStyle(element);
             const rect = element.getBoundingClientRect();
             const visible = style.display !== 'none' && style.visibility !== 'hidden' &&
               Number.parseFloat(style.opacity || '1') > 0 && rect.width > 0 && rect.height > 0 &&
               rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth;
             return {
               index,
               tag: element.tagName.toLowerCase(),
               transform: style.transform,
               opacity: style.opacity,
               top: Math.round(rect.top),
               left: Math.round(rect.left),
               visible,
             };
           });
           return {
            scroll_y: Math.round(window.scrollY),
            scroll_height: document.documentElement.scrollHeight,
            motion_nodes: nodeState,
             signature_behaviors: Array.from(document.querySelectorAll('[data-ada-signature-behavior]')).map((element) => {
               const style = getComputedStyle(element);
               const rect = element.getBoundingClientRect();
               const svgProgress = Boolean(
                 style.strokeDashoffset !== '0px' || style.strokeDasharray !== 'none'
               );
               return {
                 id: element.getAttribute('data-ada-signature-behavior') || '',
                 state: style.transform !== 'none' || svgProgress ? 'rendered' : 'unobserved',
                 trigger: element.getAttribute('data-ada-behavior-trigger') || 'scroll',
                 visible: style.display !== 'none' && style.visibility !== 'hidden' &&
                   Number.parseFloat(style.opacity || '1') > 0 && rect.width > 0 && rect.height > 0 &&
                   rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth,
                 fingerprint: signatureFingerprint(element),
               };
             }).filter((item) => item.id),
          };
        })()
        """,
    ))


def _journey_snapshot(page: Any) -> list[dict[str, Any]]:
    """Read host-owned journey evidence after a browser interaction probe."""
    return list(page.evaluate(
        """
        (() => Array.from(document.querySelectorAll('[data-ada-journey-condition]')).map((element) => {
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
           const visible = !element.closest('[aria-hidden="true"], [hidden]') &&
             style.display !== 'none' && style.visibility !== 'hidden' &&
             Number.parseFloat(style.opacity || '1') > 0 && rect.width > 0 && rect.height > 0 &&
             rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth;
          return {
            condition_id: element.getAttribute('data-ada-journey-condition') || '',
            scene_id: element.getAttribute('data-ada-journey-scene') || '',
            trigger: element.getAttribute('data-ada-journey-trigger') || '',
            state: visible ? 'rendered' : 'not-rendered',
            completion: '',
            visible,
            interactive: Boolean(element.matches('a, button, input, select, textarea, [tabindex]')),
            rendered_fingerprint: {
              box: {
                x: Number(rect.x.toFixed(2)),
                y: Number(rect.y.toFixed(2)),
                width: Number(rect.width.toFixed(2)),
                height: Number(rect.height.toFixed(2)),
              },
              transform: style.transform,
              opacity: style.opacity,
              visibility: style.visibility,
              filter: style.filter,
              text: (element.innerText || element.textContent || '').trim().slice(0, 400),
            },
          };
        }).filter((item) => item.condition_id).slice(0, 100))()
        """,
    ))


def _mark_observed_journey_transitions(
    before: Any,
    after: Any,
) -> list[dict[str, Any]]:
    """Mark only host-observed rendered changes, never candidate state claims."""

    def normalized_fingerprint(value: Any) -> Any:
        """Ignore viewport-relative position while retaining rendered change."""
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        box = normalized.get("box")
        if isinstance(box, Mapping):
            normalized["box"] = {
                key: item for key, item in box.items() if key not in {"x", "y"}
            }
        return normalized

    initial = {
        str(item.get("condition_id") or ""): item
        for item in (before or ())
        if isinstance(item, Mapping) and str(item.get("condition_id") or "").strip()
    }
    observed: list[dict[str, Any]] = []
    for raw in after or ():
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        condition_id = str(item.get("condition_id") or "").strip()
        previous = initial.get(condition_id)
        changed = previous is None and item.get("visible") is True
        if previous is not None:
            # A condition entering the viewport is not, by itself, an authored
            # transition.  Scroll changes the element's viewport-relative y/x;
            # only a rendered style/content/size change is evidence here.
            changed = normalized_fingerprint(previous.get("rendered_fingerprint")) != normalized_fingerprint(
                item.get("rendered_fingerprint")
            )
        item["observed_transition"] = bool(changed)
        observed.append(item)
    return observed


def _progressive_scroll(page: Any, target: int) -> None:
    """Move through a scroll trigger progressively instead of teleporting."""
    page.evaluate(
        """
        (target) => new Promise((resolve) => {
          const destination = Math.max(0, Number(target) || 0);
          const start = window.scrollY;
          const distance = destination - start;
          const duration = Math.min(900, Math.max(180, Math.abs(distance) * 1.2));
          const started = performance.now();
          const tick = (now) => {
            const progress = Math.min(1, (now - started) / duration);
            const eased = progress * (2 - progress);
            window.scrollTo(0, start + distance * eased);
            if (progress < 1) requestAnimationFrame(tick); else resolve();
          };
          requestAnimationFrame(tick);
        })
        """,
        int(target),
    )


def _observed_signature_behaviors(
    initial: Any,
    snapshots: Any,
) -> list[dict[str, Any]]:
    """Detect a locked signature behavior that changed across the scroll probe.

    A scroll- or pointer-driven behavior (for example a CSS-variable lamp) has
    no WAAPI animation or transform at rest, so the initial-load and button
    probes alone cannot observe it. When the element's rendered fingerprint
    changes after the harness scrolls, the locked trigger has genuinely fired
    and the behavior is observed. A behavior that never changes is still not
    observed, so the gate remains honest.
    """
    initial_fingerprints: dict[str, str] = {}
    if isinstance(initial, (list, tuple)):
        for item in initial:
            if isinstance(item, Mapping) and str(item.get("id") or "").strip():
                initial_fingerprints[str(item["id"]).strip()] = str(item.get("fingerprint") or "")
    observed: list[dict[str, Any]] = []
    seen: set[str] = set()
    if not isinstance(snapshots, (list, tuple)):
        return observed
    for snapshot in snapshots:
        if not isinstance(snapshot, Mapping):
            continue
        for item in snapshot.get("signature_behaviors") or ():
            if not isinstance(item, Mapping):
                continue
            behavior_id = str(item.get("id") or "").strip()
            if not behavior_id or behavior_id in seen:
                continue
            # This helper is fed by the progressive-scroll probe.  Do not let
            # an unrelated pointer/focus loop, or a behavior that is still
            # outside the viewport, satisfy a scroll-declared signature.
            trigger = str(item.get("trigger") or "").strip().lower()
            if trigger and not any(token in trigger for token in ("scroll", "viewport", "progress")):
                continue
            if item.get("visible") is False:
                continue
            changed = bool(initial_fingerprints.get(behavior_id)) and (
                str(item.get("fingerprint") or "") != initial_fingerprints.get(behavior_id)
            )
            if changed:
                observed.append({**dict(item), "state": "observed", "observed_via": "scroll"})
                seen.add(behavior_id)
    return observed


def _observable_snapshot(page: Any) -> dict[str, Any]:
    """Capture rendered geometry/style that a visitor can actually see."""
    return dict(page.evaluate(
        """
        (() => {
          const visible = (element) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              Number.parseFloat(style.opacity || '1') > 0 && rect.width > 0 && rect.height > 0;
          };
          const descendantFingerprint = (element) => Array.from(element.querySelectorAll('*')).slice(0, 80).map((node) => {
            const style = getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            return {
              tag: node.tagName.toLowerCase(),
              box: {
                width: Number(rect.width.toFixed(2)),
                height: Number(rect.height.toFixed(2)),
              },
              transform: style.transform,
              opacity: style.opacity,
              visibility: style.visibility,
              backgroundImage: style.backgroundImage,
              filter: style.filter,
              lampX: style.getPropertyValue('--lamp-x'),
              lampY: style.getPropertyValue('--lamp-y'),
              lampR: style.getPropertyValue('--lamp-r'),
              lightBudget: style.getPropertyValue('--light-budget'),
            };
          });
          const fingerprint = (element) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return {
              box: {
                x: Number(rect.x.toFixed(2)), y: Number(rect.y.toFixed(2)),
                width: Number(rect.width.toFixed(2)), height: Number(rect.height.toFixed(2)),
              },
              transform: style.transform,
              opacity: style.opacity,
              visibility: style.visibility,
              clipPath: style.clipPath,
              filter: style.filter,
            };
          };
          const signatureFingerprint = (element) => ({
            ...fingerprint(element),
            descendants: descendantFingerprint(element),
          });
          const selector = '[data-ada-motion-target], [data-motion], [data-animate], [data-reveal], [data-scroll], main h1, main h2, main h3, main img, main section';
          const nodes = Array.from(new Set(Array.from(document.querySelectorAll(selector))))
            .slice(0, 80)
            .map((element, index) => ({
              key: element.getAttribute('data-ada-motion-target') ||
                element.getAttribute('data-motion') || element.id || `${element.tagName.toLowerCase()}-${index}`,
              tag: element.tagName.toLowerCase(),
              visible: visible(element),
              fingerprint: fingerprint(element),
            }));
          const signature = Array.from(document.querySelectorAll('[data-ada-signature-behavior]')).map((element) => ({
            id: element.getAttribute('data-ada-signature-behavior') || '',
            fingerprint: signatureFingerprint(element),
          })).filter((item) => item.id);
          return {
            nodes,
            signature_behaviors: signature,
            critical_content_visible: Boolean(document.querySelector('main') && document.querySelector('main').innerText.trim()),
          };
        })()
        """,
    ))


def _observable_delta(
    samples: Sequence[Mapping[str, Any]],
    *,
    ignore_scroll_position: bool = False,
) -> dict[str, Any]:
    """Report meaningful rendered deltas without inspecting an animation engine."""
    if len(samples) < 2:
        return {"observed": False, "changed_nodes": [], "signature_behaviors": [], "sample_count": len(samples)}

    def signature_fingerprint(value: Any) -> Any:
        """Compare signature styling without treating viewport scroll as motion."""
        if not ignore_scroll_position or not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        box = normalized.get("box")
        if isinstance(box, Mapping):
            normalized["box"] = {**dict(box), "x": None, "y": None}
        return normalized

    first_nodes = {
        str(item.get("key") or ""): item
        for item in (samples[0].get("nodes") or ())
        if isinstance(item, Mapping) and str(item.get("key") or "")
    }
    changed: dict[str, dict[str, Any]] = {}
    for sample in samples[1:]:
        for item in sample.get("nodes") or ():
            if not isinstance(item, Mapping):
                continue
            key = str(item.get("key") or "")
            if not key or key not in first_nodes:
                continue
            initial = first_nodes[key]
            current_fingerprint = item.get("fingerprint") or {}
            initial_fingerprint = initial.get("fingerprint") or {}
            if ignore_scroll_position:
                current_fingerprint = {
                    **dict(current_fingerprint),
                    "box": {
                        **dict(current_fingerprint.get("box") or {}),
                        "x": None,
                        "y": None,
                    },
                }
                initial_fingerprint = {
                    **dict(initial_fingerprint),
                    "box": {
                        **dict(initial_fingerprint.get("box") or {}),
                        "x": None,
                        "y": None,
                    },
                }
                for fingerprint in (current_fingerprint, initial_fingerprint):
                    if str(fingerprint.get("transform") or "").replace(" ", "") in {
                        "none",
                        "matrix(1,0,0,1,0,0)",
                        "matrix3d(1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1)",
                    }:
                        fingerprint["transform"] = "__identity__"
            if current_fingerprint == initial_fingerprint:
                continue
            initial_visible = bool(initial.get("visible"))
            current_visible = bool(item.get("visible"))
            if not (initial_visible or current_visible):
                continue
            changed[key] = {
                "key": key,
                "tag": item.get("tag") or initial.get("tag") or "",
                "from": initial.get("fingerprint") or {},
                "to": item.get("fingerprint") or {},
            }
    signature_initial = {
        str(item.get("id") or ""): signature_fingerprint(item.get("fingerprint"))
        for item in (samples[0].get("signature_behaviors") or ())
        if isinstance(item, Mapping) and str(item.get("id") or "")
    }
    signatures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in samples[1:]:
        for item in sample.get("signature_behaviors") or ():
            if not isinstance(item, Mapping):
                continue
            behavior_id = str(item.get("id") or "")
            if not behavior_id or behavior_id in seen or behavior_id not in signature_initial:
                continue
            if signature_fingerprint(item.get("fingerprint")) != signature_initial[behavior_id]:
                signatures.append({"id": behavior_id, "state": "observed", "observed_via": "rendered_delta"})
                seen.add(behavior_id)
    return {
        "observed": bool(changed or signatures),
        "changed_nodes": list(changed.values())[:20],
        "signature_behaviors": signatures[:20],
        "sample_count": len(samples),
    }


def _hidden_resting_text(page: Any) -> list[dict[str, Any]]:
    """Return meaningful page text that is still invisible after settling.

    A reveal animation must not leave content permanently hidden. This walks
    each text-bearing element and its ancestors for display, visibility, and
    opacity, and reports anything unreadable at rest. It is objective and
    independent of any locked plan, so it runs in every orchestration mode.
    """
    try:
        return list(page.evaluate(
            """
            (() => {
              const effectivelyHidden = (element) => {
                for (let node = element; node; node = node.parentElement) {
                  const style = getComputedStyle(node);
                  if (style.display === 'none' || style.visibility === 'hidden') return true;
                  if (Number.parseFloat(style.opacity || '1') === 0) return true;
                }
                return false;
              };
              const isClosedDisclosure = (element) => {
                for (let node = element; node; node = node.parentElement) {
                  if (!node.hasAttribute('hidden')) continue;
                  const id = node.id;
                  if (!id) continue;
                  const controller = Array.from(document.querySelectorAll('[aria-controls]'))
                    .find((item) => item.getAttribute('aria-controls') === id);
                  if (controller && controller.getAttribute('aria-expanded') !== 'true') return true;
                }
                return false;
              };
              const selector = 'main h1, main h2, main h3, main p, main li, main a, main button, main dd, main dt';
              return Array.from(document.querySelectorAll(selector))
                .filter((element) => {
                  const text = (element.innerText || element.textContent || '').trim();
                  if (text.length < 3) return false;
                  if (element.closest('[aria-hidden="true"]')) return false;
                  if (isClosedDisclosure(element)) return false;
                  return effectivelyHidden(element);
                })
                .slice(0, 12)
                .map((element) => ({
                  tag: element.tagName.toLowerCase(),
                  text: (element.innerText || element.textContent || '').trim().slice(0, 80),
                }));
            })()
            """,
        ))
    except Exception:  # noqa: BLE001 - a probe failure is reported as absent evidence
        return []


def _interaction_metrics(
    page: Any,
    *,
    before_screenshot: Path | None = None,
    intermediate_screenshot: Path | None = None,
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
        () => {
          const signatureFingerprint = (element) => {
            const style = getComputedStyle(element);
            return [
              style.transform,
              style.opacity,
              style.backgroundImage,
              style.filter,
              style.getPropertyValue('--lamp-x'),
              style.getPropertyValue('--lamp-y'),
              style.getPropertyValue('--lamp-r'),
              style.getPropertyValue('--light-budget'),
            ].join('|');
          };
          return {
            expanded: Array.from(document.querySelectorAll('[aria-expanded]')).map((item) => item.getAttribute('aria-expanded')),
            dialogs: document.querySelectorAll('[role="dialog"], dialog[open]').length,
            details: Array.from(document.querySelectorAll('details')).map((item) => item.open),
            active: document.activeElement ? document.activeElement.tagName.toLowerCase() : '',
            signature_behaviors: Array.from(document.querySelectorAll('[data-ada-signature-behavior]')).map((element) => ({
              id: element.getAttribute('data-ada-signature-behavior') || '',
              fingerprint: signatureFingerprint(element),
            })).filter((item) => item.id),
          };
        }
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
            if attempted == 1 and intermediate_screenshot is not None:
                try:
                    page.screenshot(path=str(intermediate_screenshot), full_page=True)
                    visual["intermediate_screenshot_path"] = str(intermediate_screenshot)
                    visual["intermediate_screenshot_hash"] = _hash_file(intermediate_screenshot)
                except Exception as exc:  # noqa: BLE001 - retain interaction diagnostics
                    visual["error"] = f"intermediate screenshot: {str(exc)[:240]}"
        except Exception as exc:  # noqa: BLE001 - retain per-control evidence
            errors.append(str(exc)[:240])
    after = dict(page.evaluate(
        """
        () => {
          const signatureFingerprint = (element) => {
            const style = getComputedStyle(element);
            return [
              style.transform,
              style.opacity,
              style.backgroundImage,
              style.filter,
              style.getPropertyValue('--lamp-x'),
              style.getPropertyValue('--lamp-y'),
              style.getPropertyValue('--lamp-r'),
              style.getPropertyValue('--light-budget'),
            ].join('|');
          };
          return {
            expanded: Array.from(document.querySelectorAll('[aria-expanded]')).map((item) => item.getAttribute('aria-expanded')),
            dialogs: document.querySelectorAll('[role="dialog"], dialog[open]').length,
            details: Array.from(document.querySelectorAll('details')).map((item) => item.open),
            active: document.activeElement ? document.activeElement.tagName.toLowerCase() : '',
            signature_behaviors: Array.from(document.querySelectorAll('[data-ada-signature-behavior]')).map((element) => ({
              id: element.getAttribute('data-ada-signature-behavior') || '',
              fingerprint: signatureFingerprint(element),
            })).filter((item) => item.id),
          };
        }
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
    before_signatures = {
        str(item.get("id") or ""): item
        for item in (before.get("signature_behaviors") or ())
        if isinstance(item, Mapping) and str(item.get("id") or "").strip()
    }
    animation_observations: list[dict[str, Any]] = []
    for raw in after.get("signature_behaviors") or ():
        if not isinstance(raw, Mapping):
            continue
        behavior_id = str(raw.get("id") or "").strip()
        if not behavior_id:
            continue
        previous = before_signatures.get(behavior_id)
        if previous is None or previous.get("fingerprint") != raw.get("fingerprint"):
            animation_observations.append({
                **dict(raw),
                "state": "observed",
                "observed_via": "interaction",
            })
    return {
        "controls_found": count,
        "attempted": attempted,
        "state_changed": before != after,
        "before": before,
        "after": after,
        "errors": errors,
        "visual": visual,
        "animation_observations": animation_observations,
    }


class PlaywrightQualityAdapter:
    """Inspect every static route at one viewport and save screenshots externally."""

    @staticmethod
    def _select_owner_viewport(page: Any, viewport_name: str) -> None:
        """Select the matching size control in the real owner preview surface."""
        control_name = {
            "desktop": "desktop",
            "tablet": "ipad",
            "mobile": "mobile",
        }.get(str(viewport_name or "").strip().lower())
        if not control_name:
            return
        control = page.locator(f'#viewport-controls button[data-viewport="{control_name}"]')
        control.wait_for(state="visible", timeout=30_000)
        control.click()
        page.wait_for_timeout(100)

    def __init__(
        self,
        screenshot_root: str | Path,
        *,
        variant: str = "candidate",
        routes: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        owner_surface_url_factory: Callable[[str], str] | None = None,
        owner_surface_origin: str = "",
    ) -> None:
        self.screenshot_root = Path(screenshot_root).expanduser().resolve()
        self.variant = str(variant or "candidate")
        self.routes = tuple(str(route) for route in routes) if routes is not None else None
        self.env = dict(env) if env is not None else None
        self.owner_surface_url_factory = owner_surface_url_factory
        self.owner_surface_origin = str(owner_surface_origin or "").strip().rstrip("/")
        self._output_artifact: dict[str, Any] = {}

    def bind_output_artifact(self, artifact: Mapping[str, Any]) -> None:
        """Bind the host-retained output identity before browser inspection."""
        self._output_artifact = {
            key: value
            for key, value in dict(artifact).items()
            if key not in {"path"}
        }

    @staticmethod
    def _owner_frame(page: Any) -> _OwnerFrameSurface:
        iframe = page.locator("#preview-iframe")
        iframe.wait_for(state="visible", timeout=30_000)
        for _ in range(120):
            handle = iframe.element_handle()
            content_frame = getattr(handle, "content_frame", None) if handle is not None else None
            frame = content_frame() if callable(content_frame) else content_frame
            if frame is None:
                frames = [item for item in page.frames if item is not page.main_frame]
                frame = frames[-1] if frames else None
            if frame is not None:
                try:
                    if str(getattr(frame, "url", "") or "").strip() in {"", "about:blank"}:
                        page.wait_for_timeout(100)
                        continue
                    frame.wait_for_selector("body", state="attached", timeout=500)
                    frame.wait_for_load_state("domcontentloaded", timeout=500)
                    # Next/React client boundaries (and equivalent runtimes) can
                    # hydrate after the document load event.  The owner surface
                    # is intentionally sandboxed, so probing a form or control
                    # before its delegated listeners exist produces a false
                    # native-submit error.  Network idle is a framework-neutral
                    # readiness boundary for the module graph; if a candidate
                    # keeps a legitimate request open, retain the DOM-ready
                    # fallback rather than treating that as a navigation error.
                    try:
                        frame.wait_for_load_state("networkidle", timeout=3_000)
                    except Exception:
                        pass
                    return _OwnerFrameSurface(page, frame)
                except Exception:
                    pass
            page.wait_for_timeout(100)
        raise PlaywrightQualityError("owner preview iframe did not hydrate")

    def inspect(self, output_dir: Path, viewport: Mapping[str, int]) -> Mapping[str, Any]:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise PlaywrightQualityError("Playwright is not installed; install the design-lab browser extra") from exc

        output = Path(output_dir).expanduser().resolve()
        owner_surface = self.owner_surface_url_factory is not None
        routes = list(self.routes or ()) if owner_surface else _routes(output)
        if self.routes is not None:
            routes = []
            for route_name in self.routes:
                relative = str(route_name or "").replace("\\", "/").lstrip("/")
                target = (output / relative).resolve()
                invalid = not relative or any(part in {"", ".", ".."} for part in relative.split("/")) or Path(relative).suffix.lower() not in {".html", ".htm"}
                if not owner_surface:
                    invalid = invalid or output not in target.parents or target.is_symlink() or not target.is_file()
                if invalid:
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

        def artifact_path(path: Path | None) -> str:
            if path is None:
                return ""
            try:
                return path.resolve().relative_to(self.screenshot_root).as_posix()
            except ValueError:
                return path.name

        all_console_errors: list[dict[str, str]] = []
        all_failed_requests: list[dict[str, str]] = []
        external_requests: list[dict[str, str]] = []
        route_results: list[dict[str, Any]] = []

        artifact_server = nullcontext(None) if owner_surface else _ArtifactServer(output)
        with artifact_server as server, sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True, env=self.env)
            except Exception as exc:  # noqa: BLE001 - expose browser setup as incomplete evidence
                raise PlaywrightQualityError(f"Chromium could not launch: {str(exc)[:300]}") from exc
            try:
                # The owner surface is an iframe inside Ada's responsive shell.
                # Keep that shell at its stable workspace size and select the
                # actual candidate viewport through the shell controls below;
                # emulating 768px on the shell itself makes its flex layout
                # expand the iframe and falsifies the candidate's geometry.
                shell_viewport = {"width": 1440, "height": 1000} if owner_surface else {"width": width, "height": height}
                context = browser.new_context(viewport=shell_viewport, reduced_motion="no-preference")

                allowed_origins = [self.owner_surface_origin] if self.owner_surface_origin else []
                if server is not None:
                    allowed_origins.append(server.origin)

                def route_handler(route: Any) -> None:
                    request_url = route.request.url
                    if _is_allowed_url(request_url, allowed_origins):
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
                        if _is_allowed_url(response.url, allowed_origins) and response.status >= 400:
                            if not any(item["url"] == response.url[:500] for item in failed_requests):
                                failed_requests.append({"url": response.url[:500], "error": f"HTTP {response.status}"})

                    def on_request_failed(request: Any) -> None:
                        item = {"url": request.url[:500], "error": str(request.failure or "request failed")[:300]}
                        if _is_allowed_url(request.url, allowed_origins):
                            if not any(existing["url"] == item["url"] for existing in failed_requests):
                                failed_requests.append(item)
                        else:
                            item["error"] = "external request blocked"
                            external_requests.append(item)

                    page.on("console", on_console)
                    page.on("pageerror", lambda error: console_errors.append({"type": "pageerror", "text": str(error)[:500]}))
                    page.on("response", on_response)
                    page.on("requestfailed", on_request_failed)
                    page_url = (
                        self.owner_surface_url_factory(route_name)
                        if self.owner_surface_url_factory is not None
                        else f"{server.origin}/{route_name}"
                    )
                    parsed_page_url = urlsplit(page_url)
                    if parsed_page_url.scheme and parsed_page_url.netloc:
                        owner_origin = f"{parsed_page_url.scheme}://{parsed_page_url.netloc}"
                        if owner_origin not in allowed_origins:
                            allowed_origins.append(owner_origin)
                    result: dict[str, Any] = {
                        "route": route_name,
                        "url": urlsplit(page_url).path or f"/{route_name}",
                        "review_surface": "owner_iframe" if owner_surface else "artifact_server",
                        "artifact_identity": dict(self._output_artifact),
                    }
                    motion_results: dict[str, Any] = {}
                    try:
                        for preference in ("no-preference", "reduce"):
                            page.emulate_media(reduced_motion=preference)
                            page.goto(page_url, wait_until="domcontentloaded", timeout=30_000)
                            if owner_surface:
                                self._select_owner_viewport(page, viewport_name)
                            surface = self._owner_frame(page) if owner_surface else page
                            surface.evaluate(
                                """
                                async () => {
                                  const wait = (promise, timeout) => Promise.race([
                                    promise,
                                    new Promise((resolve) => setTimeout(resolve, timeout)),
                                  ]);
                                  const stylesReady = () => Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
                                    .every((link) => Boolean(link.sheet));
                                  const layoutSignature = () => {
                                    const main = document.querySelector('main');
                                    const marker = document.querySelector('[data-ada-signature-behavior]');
                                    const mainRect = main ? main.getBoundingClientRect() : null;
                                    const markerRect = marker ? marker.getBoundingClientRect() : null;
                                    return JSON.stringify({
                                      ready: document.readyState,
                                      width: window.innerWidth,
                                      height: window.innerHeight,
                                      sheets: document.styleSheets.length,
                                      main: mainRect ? [mainRect.width, mainRect.height] : null,
                                      marker: markerRect ? [markerRect.width, markerRect.height] : null,
                                    });
                                  };
                                  if (document.fonts && document.fonts.ready) await wait(document.fonts.ready, 2500);
                                  await wait(Promise.all(Array.from(document.images).map((image) => {
                                    if (image.complete && image.naturalWidth) return Promise.resolve();
                                    return typeof image.decode === 'function' ? image.decode().catch(() => {}) : Promise.resolve();
                                  })), 2500);
                                  // The owner shell can resize/reload its iframe after the
                                  // frame navigation becomes ready. Do not measure the
                                  // intrinsic, pre-stylesheet geometry during that window.
                                  let previous = '';
                                  let stableFrames = 0;
                                  for (let attempt = 0; attempt < 40 && stableFrames < 3; attempt += 1) {
                                    await new Promise((resolve) => requestAnimationFrame(() => resolve()));
                                    const current = layoutSignature();
                                    if (document.readyState === 'complete' && stylesReady() && current === previous) {
                                      stableFrames += 1;
                                    } else {
                                      stableFrames = 0;
                                    }
                                    previous = current;
                                    if (stableFrames < 3) await new Promise((resolve) => setTimeout(resolve, 50));
                                  }
                                  await new Promise((resolve) => requestAnimationFrame(() => resolve()));
                                }
                                """,
                            )
                            motion_before: Path | None = None
                            motion_intermediate: Path | None = None
                            motion_scroll: Path | None = None
                            if preference == "no-preference":
                                stem = route_name.removesuffix(".html").replace("/", "__") or "index"
                                motion_before = screenshot_dir / f"{stem}-motion-before.png"
                                motion_intermediate = screenshot_dir / f"{stem}-motion-intermediate.png"
                                surface.screenshot(path=str(motion_before), full_page=True)
                            observable_samples: list[dict[str, Any]] = [_observable_snapshot(surface)]
                            sample_schedule = (100, 250, 500, 900, 1500)
                            started = time.monotonic()
                            for target_ms in sample_schedule:
                                remaining = target_ms - int((time.monotonic() - started) * 1000)
                                if remaining > 0:
                                    surface.wait_for_timeout(remaining)
                                observable_samples.append(_observable_snapshot(surface))
                                if preference == "no-preference" and target_ms == 500 and motion_intermediate is not None:
                                    surface.screenshot(path=str(motion_intermediate), full_page=True)
                            observable_delta = _observable_delta(observable_samples)
                            metrics = _page_metrics(surface, viewport)
                            motion_results[preference] = {
                                **metrics.pop("reduced_motion", {}),
                                "runtime": _motion_snapshot(surface),
                                "observable_samples": observable_samples,
                                "observable_delta": observable_delta,
                                "motion_observed": bool(observable_delta.get("observed")),
                                "journey_conditions": list(metrics.get("journey_conditions") or ()),
                            }
                            if preference == "no-preference":
                                screenshot = screenshot_dir / (route_name.removesuffix(".html").replace("/", "__") + ".png")
                                # Capture the resting composition before the
                                # keyboard and interaction probes change focus,
                                # open menus, or otherwise alter the page state.
                                surface.wait_for_timeout(300)
                                surface.screenshot(path=str(screenshot), full_page=True)
                                result["screenshot_path"] = str(screenshot)
                                result["screenshot_hash"] = _hash_file(screenshot)
                                result["motion_frames"] = {
                                    "before": {
                                        "path": str(motion_before),
                                        "hash": _hash_file(motion_before) if motion_before else "",
                                    },
                                    "intermediate": {
                                        "path": str(motion_intermediate),
                                        "hash": _hash_file(motion_intermediate) if motion_intermediate else "",
                                    },
                                    "after": {"path": str(screenshot), "hash": _hash_file(screenshot)},
                                }
                                # After the animations have had time to settle,
                                # capture any meaningful text still hidden at
                                # rest. This is plan-independent: content that
                                # is invisible to the visitor is a defect.
                                hidden_resting = _hidden_resting_text(surface)
                                if hidden_resting:
                                    result["hidden_resting_text"] = hidden_resting
                            metrics["keyboard"] = _keyboard_metrics(surface)
                            scroll_states: list[dict[str, Any]] = []
                            scroll_height = int(surface.evaluate("() => document.documentElement.scrollHeight") or height)
                            max_scroll = max(0, scroll_height - height)
                            step = max(160, height // 3)
                            positions = tuple(dict.fromkeys([*range(0, max_scroll + 1, step), max_scroll]))[:12]
                            scroll_capture_position = positions[len(positions) // 2] if len(positions) > 1 else None
                            for position in positions:
                                _progressive_scroll(surface, position)
                                surface.wait_for_timeout(180)
                                current_journey = _journey_snapshot(surface)
                                previous_journey = (
                                    scroll_states[-1].get("journey_conditions")
                                    if scroll_states
                                    else metrics.get("journey_conditions") or ()
                                )
                                scroll_states.append({
                                    "position": position,
                                    **_motion_snapshot(surface),
                                    "journey_conditions": _mark_observed_journey_transitions(
                                        previous_journey,
                                        current_journey,
                                    ),
                                })
                                scroll_states[-1]["observable"] = _observable_snapshot(surface)
                                if (
                                    preference == "no-preference"
                                    and scroll_capture_position is not None
                                    and position == scroll_capture_position
                                ):
                                    motion_scroll = screenshot_dir / f"{stem}-motion-scroll.png"
                                    surface.screenshot(path=str(motion_scroll), full_page=True)
                            surface.evaluate("() => window.scrollTo(0, 0)")
                            surface.wait_for_timeout(80)
                            scroll_observable_delta = _observable_delta(
                                [observable_samples[0], *(item["observable"] for item in scroll_states)],
                                ignore_scroll_position=True,
                            )
                            motion_results[preference]["scroll_observable_delta"] = scroll_observable_delta
                            motion_results[preference]["scroll_states"] = scroll_states
                            motion_results[preference]["motion_observed"] = bool(
                                observable_delta.get("observed") or scroll_observable_delta.get("observed")
                            )
                            if preference == "no-preference":
                                if motion_scroll is not None:
                                    surface.screenshot(path=str(motion_intermediate), full_page=True)
                                if result.get("screenshot_path"):
                                    resting_screenshot = Path(str(result["screenshot_path"]))
                                    surface.screenshot(path=str(resting_screenshot), full_page=True)
                                    result["screenshot_hash"] = _hash_file(resting_screenshot)
                                result["motion_frames"] = {
                                    "before": {
                                        "path": str(motion_before),
                                        "hash": _hash_file(motion_before) if motion_before else "",
                                    },
                                    "intermediate": {
                                        "path": str(motion_intermediate),
                                        "hash": _hash_file(motion_intermediate) if motion_intermediate else "",
                                    },
                                    "after": {
                                        "path": str(result.get("screenshot_path") or ""),
                                        "hash": str(result.get("screenshot_hash") or ""),
                                    },
                                }
                            metrics["scroll_states"] = scroll_states
                            # A locked signature behavior may be scroll-driven,
                            # so the scroll probe above (not just the initial
                            # load and button clicks) must be able to observe it.
                            scroll_signature_observations = _observed_signature_behaviors(
                                metrics.get("signature_behaviors") or (),
                                scroll_states,
                            )
                            # The interaction probe deliberately clicks the menu
                            # toggle and other buttons. Keep the resting
                            # composition separate, then compare bounded visual
                            # evidence before and after the controls run.
                            interaction_before = None
                            interaction_after = None
                            if preference == "no-preference":
                                stem = route_name.removesuffix(".html").replace("/", "__") or "index"
                                interaction_before = screenshot_dir / f"{stem}-interaction-before.png"
                                interaction_intermediate = screenshot_dir / f"{stem}-interaction-intermediate.png"
                                interaction_after = screenshot_dir / f"{stem}-interaction-after.png"
                            else:
                                interaction_intermediate = None
                            interaction_state = _interaction_metrics(
                                surface,
                                before_screenshot=interaction_before,
                                intermediate_screenshot=interaction_intermediate,
                                after_screenshot=interaction_after,
                            )
                            journey_before = list(metrics.get("journey_conditions") or ())
                            journey_after = _mark_observed_journey_transitions(
                                journey_before,
                                _journey_snapshot(surface),
                            )
                            if preference == "no-preference":
                                result.update(metrics)
                                result["interaction_state"] = interaction_state
                                result["journey_conditions_before"] = journey_before
                                result["journey_conditions_after"] = journey_after
                                visual = interaction_state.get("visual") or {}
                                motion_frames = result.get("motion_frames") or {}
                                before_path = Path(str((motion_frames.get("before") or {}).get("path") or visual.get("before_screenshot_path") or result.get("screenshot_path") or ""))
                                intermediate_path = Path(str((motion_frames.get("intermediate") or {}).get("path") or visual.get("intermediate_screenshot_path") or result.get("screenshot_path") or ""))
                                after_path = Path(str((motion_frames.get("after") or {}).get("path") or visual.get("after_screenshot_path") or result.get("screenshot_path") or ""))
                                result["temporal_evidence"] = [{
                                    "schema_version": 1,
                                    "candidate_sha": "",
                                    "experience_plan_hash": "",
                                    "route": f"/{route_name}" if route_name else "/",
                                    "viewport": {"name": viewport_name, "width": width, "height": height},
                                    "reduced_motion": False,
                                    "interaction_script_id": "bounded-controls-v1",
                                    "frames": [
                                        {"phase": "before", "path": artifact_path(before_path)},
                                        {"phase": "intermediate", "path": artifact_path(intermediate_path)},
                                        {"phase": "after", "path": artifact_path(after_path)},
                                    ],
                                    "layout_shifts": list(metrics.get("layout_shifts") or []),
                                    "console_errors": list(console_errors),
                                    "network_errors": list(failed_requests),
                                     "animation_observations": [
                                          *list(metrics.get("signature_behaviors") or []),
                                           *list(
                                               (motion_results.get("no-preference") or {})
                                               .get("observable_delta", {})
                                               .get("signature_behaviors", [])
                                           ),
                                           *[
                                               {**dict(item), "observed_via": "progressive_scroll"}
                                               for item in (motion_results.get("no-preference") or {})
                                               .get("scroll_observable_delta", {})
                                               .get("changed_nodes", [])
                                           ],
                                           *list(interaction_state.get("animation_observations") or []),
                                          *list(scroll_signature_observations),
                                      ],
                                     "keyboard_path_observations": [
                                         str(item.get("role") or "")
                                         for item in (metrics.get("composition_elements") or ())
                                        if isinstance(item, Mapping) and str(item.get("role") or "")
                                    ],
                                    "resting_state_observations": {
                                        "critical_content_visible": bool(metrics.get("critical_content_visible")),
                                    },
                                }]
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
            "review_surface": "owner_iframe" if owner_surface else "artifact_server",
            "artifact_identity": dict(self._output_artifact),
            "routes": route_results,
            "console_errors": all_console_errors,
            "failed_requests": all_failed_requests,
            "external_requests": list({(item["url"], item["error"]): item for item in external_requests}.values()),
            "overflow": [item["route"] for item in route_results if item.get("overflow")],
            "clipping": [item["route"] for item in route_results if item.get("clipping")],
            "fixed_header_overlap": [item["route"] for item in route_results if item.get("fixed_header_overlap")],
            "hidden_resting_text": [
                {"route": item["route"], "details": item.get("hidden_resting_text") or []}
                for item in route_results
                if item.get("hidden_resting_text")
            ],
            "scroll_states": [
                {"route": item["route"], "states": item.get("scroll_states") or []}
                for item in route_results if item.get("scroll_states")
            ],
            "interaction_states": [
                {"route": item["route"], "state": item.get("interaction_state") or {}}
                for item in route_results if item.get("interaction_state")
            ],
            "journey_conditions": [
                {
                    "route": item["route"],
                    "before": item.get("journey_conditions_before") or [],
                    "after": item.get("journey_conditions_after") or [],
                }
                for item in route_results
                if item.get("journey_conditions_before") or item.get("journey_conditions_after")
            ],
            "accessibility": [
                {"route": item["route"], "findings": item.get("accessibility")}
                for item in route_results if item.get("accessibility")
            ],
        }


__all__ = ["PlaywrightQualityAdapter", "PlaywrightQualityError"]
