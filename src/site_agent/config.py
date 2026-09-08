from __future__ import annotations

import copy
import math
import os
import fnmatch
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

_SECRET_MARKERS = ("key", "token", "password", "secret")


class ConfigError(ValueError):
    """A configuration file or value cannot be used safely."""


@dataclass(frozen=True)
class IntakeAdaSettings:
    """Validated host-owned settings for the persistent Intake Ada process."""

    data_dir: Path
    incubation_root: Path
    scaffold: Path
    customer_root: Path
    research_enabled: bool = True
    abandoned_ttl_days: int = 30
    rejected_ttl_hours: int = 24
    max_sources_per_pass: int = 8
    max_items_per_source: int = 15
    max_passes_before_owner_turn: int = 1

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "IntakeAdaSettings":
        validate_intake_config(config)
        section = config.get("incubation") or {}
        research = config.get("research") or {}
        root = Path(str(config.get("data_dir") or "data")).expanduser().resolve()
        incubation_root = Path(str(section.get("root") or (root.parent / "incubations"))).expanduser().resolve()
        scaffold = Path(str(section.get("scaffold") or (root.parent / "neutral-scaffold"))).expanduser().resolve()
        provisioning = config.get("provisioning") or {}
        customer_root = Path(str(provisioning.get("customer_root") or (root.parent / "customers"))).expanduser().resolve()
        return cls(
            data_dir=root,
            incubation_root=incubation_root,
            scaffold=scaffold,
            customer_root=customer_root,
            research_enabled=bool(research.get("enabled", True)),
            abandoned_ttl_days=int(section.get("abandoned_ttl_days", 30)),
            rejected_ttl_hours=int(section.get("rejected_ttl_hours", 24)),
            max_sources_per_pass=int(research.get("max_sources_per_pass", 8)),
            max_items_per_source=int(research.get("max_items_per_source", 15)),
            max_passes_before_owner_turn=int(research.get("max_passes_before_owner_turn", 1)),
        )


@dataclass(frozen=True)
class InfusionSettings:
    """Validated settings for the durable background knowledge-infusion loop."""

    enabled: bool = True
    mode: str = "auto"
    idle_seconds: int = 90
    cooldown_seconds: int = 60
    max_tokens_per_pass: int = 1_200
    max_passes_per_day: int = 120
    opencode_pass_interval_seconds: int = 1_800
    include_pipeworx: bool = True

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "InfusionSettings":
        section = config.get("infusion") or {}
        if not isinstance(section, dict):
            raise ConfigError("infusion must be an object")
        mode = str(section.get("mode") or "auto").strip().lower()
        if mode not in {"opencode", "native", "auto"}:
            raise ConfigError("infusion.mode must be opencode, native, or auto")
        values: dict[str, int] = {}
        for name, default, minimum, maximum in (
            ("idle_seconds", 90, 1, 3600),
            ("cooldown_seconds", 60, 1, 3600),
            ("max_tokens_per_pass", 1_200, 64, 100_000),
            ("max_passes_per_day", 120, 1, 10_000),
            ("opencode_pass_interval_seconds", 1_800, 60, 86_400),
        ):
            raw = section.get(name, default)
            if isinstance(raw, bool):
                raise ConfigError(f"infusion.{name} must be a positive integer")
            try:
                value = int(raw)
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"infusion.{name} must be a positive integer") from exc
            if not minimum <= value <= maximum:
                raise ConfigError(f"infusion.{name} must be between {minimum} and {maximum}")
            values[name] = value
        return cls(
            enabled=bool(section.get("enabled", True)),
            mode=mode,
            idle_seconds=values["idle_seconds"],
            cooldown_seconds=values["cooldown_seconds"],
            max_tokens_per_pass=values["max_tokens_per_pass"],
            max_passes_per_day=values["max_passes_per_day"],
            opencode_pass_interval_seconds=values["opencode_pass_interval_seconds"],
            include_pipeworx=bool(section.get("include_pipeworx", True)),
        )


CRAWLSEO_DEFAULT_TOKEN_ENV = "CRAWLSEO_SERVICE_TOKEN"
CRAWLSEO_DEFAULT_TIMEOUT_SECONDS = 30.0
CRAWLSEO_DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
CRAWLSEO_MAX_TIMEOUT_SECONDS = 120.0
CRAWLSEO_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
R2_MAX_SIGNED_URL_TTL_SECONDS = 3600
R2_MAX_IMAGE_BYTES = 100 * 1024 * 1024
R2_MAX_PDF_BYTES = 200 * 1024 * 1024
R2_MAX_IMAGE_PIXELS = 200_000_000
R2_MAX_PDF_PAGES = 200


@dataclass(frozen=True)
class CrawlSEOSettings:
    """Validated, process-local settings for the project-scoped provider."""

    enabled: bool
    url: str
    token_env: str
    timeout_seconds: float = CRAWLSEO_DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = CRAWLSEO_DEFAULT_MAX_RESPONSE_BYTES
    token: str = field(default="", repr=False)

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        env: dict[str, str] | None = None,
    ) -> "CrawlSEOSettings":
        env = os.environ if env is None else env
        provider = (config.get("providers") or {}).get("crawlseo") or {}
        enabled = bool(provider.get("enabled", False))
        token_env = str(provider.get("token_env") or CRAWLSEO_DEFAULT_TOKEN_ENV).strip()
        if not enabled:
            return cls(
                enabled=False,
                url=str(provider.get("url") or ""),
                token_env=token_env,
                timeout_seconds=CRAWLSEO_DEFAULT_TIMEOUT_SECONDS,
                max_response_bytes=CRAWLSEO_DEFAULT_MAX_RESPONSE_BYTES,
            )

        url = str(provider.get("url") or "").strip()
        parsed = urlsplit(url)
        if (
            not url
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigError("providers.crawlseo.url must be an HTTP(S) URL without credentials or query data")

        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env):
            raise ConfigError("providers.crawlseo.token_env must be a valid environment variable name")

        raw_timeout = provider.get("timeout_seconds", CRAWLSEO_DEFAULT_TIMEOUT_SECONDS)
        if isinstance(raw_timeout, bool):
            raise ConfigError("providers.crawlseo.timeout_seconds must be a positive number")
        try:
            timeout_seconds = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise ConfigError("providers.crawlseo.timeout_seconds must be a positive number") from exc
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= CRAWLSEO_MAX_TIMEOUT_SECONDS:
            raise ConfigError(
                f"providers.crawlseo.timeout_seconds must be between 0 and {CRAWLSEO_MAX_TIMEOUT_SECONDS:g}"
            )

        raw_limit = provider.get("max_response_bytes", CRAWLSEO_DEFAULT_MAX_RESPONSE_BYTES)
        if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
            raise ConfigError("providers.crawlseo.max_response_bytes must be a positive integer")
        if not 0 < raw_limit <= CRAWLSEO_MAX_RESPONSE_BYTES:
            raise ConfigError(
                f"providers.crawlseo.max_response_bytes must be between 1 and {CRAWLSEO_MAX_RESPONSE_BYTES}"
            )

        mapped_env = str((config.get("env") or {}).get("crawlseo_service_token") or "").strip()
        if mapped_env and token_env == CRAWLSEO_DEFAULT_TOKEN_ENV:
            token_env = mapped_env
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env):
            raise ConfigError("providers.crawlseo.token_env must be a valid environment variable name")
        token = str(env.get(token_env, "") or "")
        if not token:
            raise ConfigError(f"CrawlSEO provider is enabled but {token_env} is not set")

        return cls(
            enabled=True,
            url=url,
            token_env=token_env,
            timeout_seconds=timeout_seconds,
            max_response_bytes=raw_limit,
            token=token,
        )


def crawlseo_configured(config: dict[str, Any]) -> bool:
    """Return whether the instance opted into the CrawlSEO provider."""
    return bool(((config.get("providers") or {}).get("crawlseo") or {}).get("enabled", False))


def validate_media_config(config: dict[str, Any], env: dict[str, str] | None = None) -> None:
    """Validate private, customer-scoped R2 settings without contacting Cloudflare."""
    env = os.environ if env is None else env
    media = ((config.get("site") or {}).get("media") or {})
    if not isinstance(media, dict):
        raise ConfigError("site.media must be an object")
    if not media.get("enabled", False):
        return
    account_id = str(media.get("account_id") or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32}", account_id):
        raise ConfigError("site.media.account_id must be a 32-character Cloudflare account ID")
    bucket = str(media.get("bucket") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}[a-z0-9]", bucket):
        raise ConfigError("site.media.bucket must contain 3-64 lowercase letters, numbers, or hyphens")
    if media.get("private", True) is not True:
        raise ConfigError("site.media.private must be true")

    def positive_int(name: str, default: int, maximum: int) -> None:
        value = media.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
            raise ConfigError(f"site.media.{name} must be between 1 and {maximum}")

    positive_int("signed_url_ttl_seconds", 900, R2_MAX_SIGNED_URL_TTL_SECONDS)
    positive_int("max_image_bytes", 25 * 1024 * 1024, R2_MAX_IMAGE_BYTES)
    positive_int("max_pdf_bytes", 50 * 1024 * 1024, R2_MAX_PDF_BYTES)
    positive_int("max_image_pixels", 80_000_000, R2_MAX_IMAGE_PIXELS)
    positive_int("max_pdf_pages", 30, R2_MAX_PDF_PAGES)
    positive_int("vision_pages_per_call", 12, 30)
    positive_int("pdf_render_dpi", 220, 600)
    positive_int("image_max_edge", 3200, 10_000)
    positive_int("webp_quality", 84, 100)
    positive_int("vision_image_max_edge", 1600, 10_000)
    positive_int("vision_image_quality", 70, 100)
    positive_int("max_chat_attachments", 12, 12)
    asset_dir = str(media.get("site_asset_dir") or "").strip()
    if asset_dir:
        path = Path(asset_dir)
        if path.is_absolute() or ".." in path.parts or any(ord(ch) < 32 for ch in asset_dir):
            raise ConfigError("site.media.site_asset_dir must be a safe relative path")
    if (config.get("builder") or {}).get("enabled") and asset_dir:
        patterns = [str(item) for item in ((config.get("site") or {}).get("writable_patterns") or [])]
        probe = asset_dir.rstrip("/") + "/ada-media.webp"
        if not any(fnmatch.fnmatch(probe, pattern) or fnmatch.fnmatch(asset_dir, pattern) for pattern in patterns):
            raise ConfigError("site.writable_patterns must permit site.media.site_asset_dir")
    for name in ("r2_access_key_id", "r2_secret_access_key"):
        mapped = str((config.get("env") or {}).get(name) or "").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", mapped):
            raise ConfigError(f"env.{name} must be a valid environment variable name")
        if not str(env.get(mapped, "") or "").strip():
            raise ConfigError(f"R2 media is enabled but {mapped} is not set")


def validate_design_config(config: dict[str, Any]) -> None:
    """Validate the opt-in design-engine controls without inspecting a site."""
    engine = config.get("design_engine") or {}
    if not isinstance(engine, dict):
        raise ConfigError("design_engine must be an object")
    version = engine.get("intake_schema_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise ConfigError("design_engine.intake_schema_version must be 1")
    manifest = str(engine.get("manifest_path") or "").strip().replace("\\", "/")
    if manifest and (Path(manifest).is_absolute() or ".." in Path(manifest).parts or "" in Path(manifest).parts):
        raise ConfigError("design_engine.manifest_path must be a safe relative path")
    attempts = engine.get("repair_attempts", 0)
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 0 <= attempts <= 10:
        raise ConfigError("design_engine.repair_attempts must be between 0 and 10")
    max_tokens = engine.get("max_tokens")
    if max_tokens is not None and (
        isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 32_768
    ):
        raise ConfigError("design_engine.max_tokens must be between 1 and 32768")
    viewports = engine.get("required_viewports") or []
    if not isinstance(viewports, list) or not viewports:
        raise ConfigError("design_engine.required_viewports must be a non-empty list")
    for index, viewport in enumerate(viewports):
        if not isinstance(viewport, dict):
            raise ConfigError(f"design_engine.required_viewports[{index}] must be an object")
        for dimension in ("width", "height"):
            value = viewport.get(dimension)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigError(f"design_engine.required_viewports[{index}].{dimension} must be positive")
    libraries = engine.get("libraries") or {}
    if not isinstance(libraries, dict):
        raise ConfigError("design_engine.libraries must be an object")
    for name, setting in libraries.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", name):
            raise ConfigError("design_engine.libraries names must be safe identifiers")
        if isinstance(setting, dict):
            enabled = setting.get("enabled", True)
            required = setting.get("required", False)
        elif isinstance(setting, bool):
            enabled = setting
            required = False
        else:
            raise ConfigError(f"design_engine.libraries.{name} must be a boolean or object")
        if not isinstance(enabled, bool):
            raise ConfigError(f"design_engine.libraries.{name}.enabled must be boolean")
        if not isinstance(required, bool):
            raise ConfigError(f"design_engine.libraries.{name}.required must be boolean")
        if required and not enabled:
            raise ConfigError(f"design_engine.libraries.{name}.required requires enabled=true")
    quality = engine.get("quality") or {}
    if not isinstance(quality, dict):
        raise ConfigError("design_engine.quality must be an object")
    for name in (
        "browser",
        "accessibility",
        "visual_critic",
        "native_source_required",
        "originality_required",
    ):
        if name in quality and not isinstance(quality[name], bool):
            raise ConfigError(f"design_engine.quality.{name} must be boolean")
    required_pages = quality.get("required_pages") or []
    if isinstance(required_pages, str) or not isinstance(required_pages, list):
        raise ConfigError("design_engine.quality.required_pages must be a list")
    for index, page in enumerate(required_pages):
        value = str(page or "").strip().replace("\\", "/")
        if not value or Path(value).is_absolute() or ".." in Path(value).parts or "" in Path(value).parts:
            raise ConfigError(f"design_engine.quality.required_pages[{index}] must be a safe relative path")
    required_content = quality.get("required_content") or []
    if isinstance(required_content, str) or not isinstance(required_content, list):
        raise ConfigError("design_engine.quality.required_content must be a list")
    for index, item in enumerate(required_content):
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 20_000:
            raise ConfigError(f"design_engine.quality.required_content[{index}] must be non-empty text")
        if any(ord(character) < 32 and character not in "\t\n\r" for character in item):
            raise ConfigError(f"design_engine.quality.required_content[{index}] must be non-empty text")
    output_dir = str(quality.get("output_dir") or "output").strip().replace("\\", "/")
    if Path(output_dir).is_absolute() or ".." in Path(output_dir).parts or "" in Path(output_dir).parts:
        raise ConfigError("design_engine.quality.output_dir must be a safe relative path")

    required_fonts = quality.get("required_font_families") or quality.get("required_fonts") or []
    if isinstance(required_fonts, str) or not isinstance(required_fonts, list):
        raise ConfigError("design_engine.quality.required_font_families must be a list")
    for index, family in enumerate(required_fonts):
        if not isinstance(family, str) or not family.strip() or len(family.strip()) > 200:
            raise ConfigError(f"design_engine.quality.required_font_families[{index}] must be non-empty text")

    approved_fonts = quality.get("approved_font_files") or quality.get("approved_fonts") or []
    if not isinstance(approved_fonts, list):
        raise ConfigError("design_engine.quality.approved_font_files must be a list")
    for index, item in enumerate(approved_fonts):
        if not isinstance(item, dict):
            raise ConfigError(f"design_engine.quality.approved_font_files[{index}] must be an object")
        relative = str(item.get("path") or item.get("destination") or "").strip().replace("\\", "/")
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts or not relative.lower().endswith(".woff2"):
            raise ConfigError(f"design_engine.quality.approved_font_files[{index}].path must be a safe WOFF2 path")
        digest = str(item.get("sha256") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ConfigError(f"design_engine.quality.approved_font_files[{index}].sha256 must be a SHA-256")

    configured_fonts = engine.get("fonts") or []
    if not isinstance(configured_fonts, list):
        raise ConfigError("design_engine.fonts must be a list")
    for index, item in enumerate(configured_fonts):
        if not isinstance(item, dict):
            raise ConfigError(f"design_engine.fonts[{index}] must be an object")
        source = str(item.get("source_path") or item.get("source") or "").strip()
        destination = str(item.get("destination") or item.get("path") or "").strip().replace("\\", "/")
        if not source:
            raise ConfigError(f"design_engine.fonts[{index}].source_path is required")
        if not destination or Path(destination).is_absolute() or ".." in Path(destination).parts or not destination.lower().endswith(".woff2"):
            raise ConfigError(f"design_engine.fonts[{index}].destination must be a safe WOFF2 path")
        if not destination.startswith("public/"):
            raise ConfigError(f"design_engine.fonts[{index}].destination must be under public/")
        digest = str(item.get("sha256") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ConfigError(f"design_engine.fonts[{index}].sha256 must be a SHA-256")
        family = item.get("family")
        if family is not None and (not isinstance(family, str) or not family.strip() or len(family.strip()) > 200):
            raise ConfigError(f"design_engine.fonts[{index}].family must be non-empty text")


def validate_research_config(config: dict[str, Any]) -> None:
    """Validate the small customer-owned language and market intake surface."""
    research = ((config.get("seo") or {}).get("research") or {})
    if not research.get("enabled", False):
        return

    timezone = str(research.get("timezone") or "UTC").strip()
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError("seo.research.timezone must be a valid IANA timezone")

    languages = research.get("languages")
    if not isinstance(languages, list) or not languages:
        raise ConfigError("seo.research.languages must contain at least one language")
    primary_count = 0
    language_codes: set[str] = set()
    for index, item in enumerate(languages):
        if not isinstance(item, dict):
            raise ConfigError(f"seo.research.languages[{index}] must be an object")
        code = str(item.get("code") or "").strip().lower()
        if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", code):
            raise ConfigError(f"seo.research.languages[{index}].code is invalid")
        if code in language_codes:
            raise ConfigError("seo.research.languages must not contain duplicate codes")
        language_codes.add(code)
        if item.get("primary", False):
            primary_count += 1
        markets = item.get("markets")
        if not isinstance(markets, list) or not markets:
            raise ConfigError(f"seo.research.languages[{index}].markets must contain at least one country")
        normalized_markets = [str(market).strip().upper() for market in markets]
        if any(not re.fullmatch(r"[A-Z]{2}", market) for market in normalized_markets):
            raise ConfigError(f"seo.research.languages[{index}].markets contains an invalid country")
        if len(set(normalized_markets)) != len(normalized_markets):
            raise ConfigError(f"seo.research.languages[{index}].markets must not contain duplicates")
    if primary_count != 1:
        raise ConfigError("seo.research.languages must contain exactly one primary language")

    existing_locales = research.get("existing_locales") or []
    if not isinstance(existing_locales, list):
        raise ConfigError("seo.research.existing_locales must be a list")
    normalized_existing = {str(locale).strip().lower() for locale in existing_locales if str(locale).strip()}
    if not normalized_existing or not normalized_existing.intersection(language_codes):
        raise ConfigError("seo.research.existing_locales must include a configured language")

    for field_name in ("business_goals", "priority_services", "anchor_topics"):
        value = research.get(field_name) or []
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ConfigError(f"seo.research.{field_name} must be a list of non-empty text")

    for field_name in ("competitors", "competitor_candidates"):
        candidates = research.get(field_name) or []
        if not isinstance(candidates, list):
            raise ConfigError(f"seo.research.{field_name} must be a list")
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict) or not str(candidate.get("domain") or candidate.get("url") or "").strip():
                raise ConfigError(f"seo.research.{field_name}[{index}] must include a domain")
            markets = candidate.get("markets")
            if markets is not None and (
                not isinstance(markets, list)
                or any(not isinstance(market, str) or not re.fullmatch(r"[A-Z]{2}", market.strip().upper()) for market in markets)
            ):
                raise ConfigError(f"seo.research.{field_name}[{index}].markets contains an invalid country")


def validate_seo_workflow_config(config: dict[str, Any]) -> None:
    """Validate the small, separate monthly-report and article-research controls."""
    seo = config.get("seo") or {}
    site_report = seo.get("site_report") or {}
    if not isinstance(site_report, dict):
        raise ConfigError("seo.site_report must be an object")
    if site_report.get("enabled", False):
        timezone = str(site_report.get("timezone") or "UTC").strip()
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ConfigError("seo.site_report.timezone must be a valid IANA timezone")
        max_pages = site_report.get("max_crawl_pages", 200)
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= 2000:
            raise ConfigError("seo.site_report.max_crawl_pages must be between 1 and 2000")

    article_research = seo.get("article_research") or {}
    if not isinstance(article_research, dict):
        raise ConfigError("seo.article_research must be an object")
    if article_research.get("enabled", False):
        timezone = str(article_research.get("timezone") or site_report.get("timezone") or "UTC").strip()
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ConfigError("seo.article_research.timezone must be a valid IANA timezone")
        language = str(article_research.get("language") or "").strip().lower()
        if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", language):
            raise ConfigError("seo.article_research.language is invalid")
        market = str(article_research.get("market") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", market):
            raise ConfigError("seo.article_research.market is invalid")


def _resolved_config_path(value: Any, name: str) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    if path == Path(path.anchor):
        raise ConfigError(f"{name} must not be the filesystem root")
    return path


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def validate_intake_config(config: dict[str, Any]) -> None:
    """Reject customer configuration from the host-owned Intake Ada process."""
    if not isinstance(config, dict):
        raise ConfigError("Intake Ada configuration must be an object")
    if str(config.get("role") or "").strip().lower() != "intake":
        raise ConfigError("Intake Ada configuration must set role: intake")
    if str(config.get("instance_name") or "").strip() != "intake-ada":
        raise ConfigError("instance_name must be intake-ada for Intake Ada")

    persona = config.get("persona") or {}
    if not isinstance(persona, dict) or str(persona.get("name") or "").strip() != "Ada":
        raise ConfigError("persona.name must be Ada")
    if str(persona.get("mode") or "").strip() != "intake_creative_director":
        raise ConfigError("persona.mode must be intake_creative_director")
    for key in ("spirit", "voice", "audience", "directions", "taboo", "lures"):
        value = persona.get(key)
        if value not in (None, "", [], {}):
            raise ConfigError(f"persona.{key} is customer-specific")

    site = config.get("site") or {}
    if not isinstance(site, dict):
        raise ConfigError("site must be an object")
    if str(site.get("adapter") or "").strip() != "neutral_scaffold":
        raise ConfigError("site.adapter must be neutral_scaffold")
    for key in ("repository", "clone_path", "repository_path", "preview_url", "preview_branch", "url", "data_dir"):
        if str(site.get(key) or "").strip():
            raise ConfigError(f"site.{key} is customer-specific")
    brand = site.get("brand") or {}
    if not isinstance(brand, dict):
        raise ConfigError("site.brand must be an object")
    for key in ("font_body", "font_display", "fonts_url", "logo"):
        if str(brand.get(key) or "").strip():
            raise ConfigError(f"site.brand.{key} is customer-specific")
    media = site.get("media") or {}
    if not isinstance(media, dict) or media.get("enabled", False):
        raise ConfigError("site.media must be disabled for Intake Ada")
    cloudflare = site.get("cloudflare") or {}
    if not isinstance(cloudflare, dict):
        raise ConfigError("site.cloudflare must be an object")
    for key in ("account_id", "project_name"):
        if str(cloudflare.get(key) or "").strip():
            raise ConfigError(f"site.cloudflare.{key} is customer-specific")
    if str(cloudflare.get("mode") or "none").strip() not in {"", "none"}:
        raise ConfigError("site.cloudflare.mode is customer-specific")

    sources = config.get("sources") or {}
    if not isinstance(sources, dict):
        raise ConfigError("sources must be an object")
    for key in ("subreddits", "rss_feeds", "keywords"):
        if sources.get(key) not in (None, []):
            raise ConfigError(f"sources.{key} is customer-specific")
    for key, value in (("ga", config.get("ga") or {}), ("seo", config.get("seo") or {})):
        if not isinstance(value, dict):
            raise ConfigError(f"{key} must be an object")
        if value.get("enabled", False):
            raise ConfigError(f"{key}.enabled is customer-specific")
        for field_name in ("property_id", "key_path", "site_url"):
            if str(value.get(field_name) or "").strip():
                raise ConfigError(f"{key}.{field_name} is customer-specific")
    providers = config.get("providers") or {}
    if not isinstance(providers, dict):
        raise ConfigError("providers must be an object")
    for name, provider in providers.items():
        if isinstance(provider, dict) and provider.get("enabled", False):
            raise ConfigError(f"providers.{name}.enabled is customer-specific")

    for key in ("repository_path", "published_repository", "domain", "customer_instance_id"):
        if str(config.get(key) or "").strip():
            raise ConfigError(f"{key} is customer-specific")
    if (config.get("schedule") or {}):
        raise ConfigError("schedule is not allowed for Intake Ada")
    if str(config.get("publish_mode") or "disabled").strip() not in {"", "disabled"}:
        raise ConfigError("publish_mode must be disabled for Intake Ada")

    env_config = config.get("env") or {}
    if not isinstance(env_config, dict):
        raise ConfigError("env must be an object")
    for key, value in env_config.items():
        if key not in {"llm_api_key", "vision_api_key", "design_api_key", "visual_review_api_key"} and str(value or "").strip():
            raise ConfigError(f"env.{key} is not allowed for Intake Ada")

    section = config.get("incubation") or {}
    if not isinstance(section, dict):
        raise ConfigError("incubation must be an object")
    for name, default, maximum in (
        ("abandoned_ttl_days", 30, 3650),
        ("rejected_ttl_hours", 24, 8760),
    ):
        value = section.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise ConfigError(f"incubation.{name} is invalid")
    research = config.get("research") or {}
    if not isinstance(research, dict):
        raise ConfigError("research must be an object")
    if not isinstance(research.get("enabled", True), bool):
        raise ConfigError("research.enabled must be boolean")
    for name, default, maximum in (
        ("max_sources_per_pass", 8, 50),
        ("max_items_per_source", 15, 100),
        ("max_passes_before_owner_turn", 1, 5),
    ):
        value = research.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
            raise ConfigError(f"research.{name} is invalid")

    data_root = _resolved_config_path(config.get("data_dir"), "data_dir")
    incubation_root = _resolved_config_path(section.get("root"), "incubation.root")
    scaffold_root = _resolved_config_path(section.get("scaffold"), "incubation.scaffold")
    provisioning = config.get("provisioning") or {}
    if not isinstance(provisioning, dict):
        raise ConfigError("provisioning must be an object")
    customer_root = _resolved_config_path(provisioning.get("customer_root"), "provisioning.customer_root")
    if data_root is None or incubation_root is None or scaffold_root is None or customer_root is None:
        raise ConfigError("Intake Ada data_dir, incubation.root, incubation.scaffold, and provisioning.customer_root are required")
    roots = (
        ("data_dir", data_root),
        ("incubation.root", incubation_root),
        ("incubation.scaffold", scaffold_root),
        ("provisioning.customer_root", customer_root),
    )
    for index, (left_name, left) in enumerate(roots):
        for right_name, right in roots[index + 1:]:
            if _paths_overlap(left, right):
                raise ConfigError(f"{left_name} and {right_name} must be disjoint")


def _intake_defaults_path() -> Path:
    return Path(files("site_agent").joinpath("intake-ada.yaml"))


def load_intake_config(
    config_path: str | Path | None = None,
    env: dict[str, str] | None = None,
    *,
    validate_integrations: bool = True,
) -> tuple[dict[str, Any], list[Path]]:
    """Load the neutral Intake Ada defaults without consulting instance config."""
    env = os.environ if env is None else env
    defaults_path = _intake_defaults_path()
    defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8")) or {}
    path = Path(config_path) if config_path is not None else None
    if path is not None and not path.is_file():
        raise ConfigError(f"configuration file not found: {path}")
    override = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path else {}
    if not isinstance(override, dict):
        raise ConfigError(f"configuration root must be a mapping: {path}")
    merged = deep_merge(defaults, override)
    validate_intake_config(merged)
    validate_research_config(merged)
    validate_seo_workflow_config(merged)
    validate_design_config(merged)
    if validate_integrations:
        validate_media_config(merged, env)
    return merged, [Path("<package>/intake-ada.yaml"), path] if path else [Path("<package>/intake-ada.yaml")]


def _defaults_path() -> Path:
    return Path(files("site_agent").joinpath("defaults.yaml"))


def instance_path(env: dict[str, str] | None = None) -> Path | None:
    env = os.environ if env is None else env
    raw = env.get("SITE_AGENT_CONFIG", "")
    if raw:
        return Path(raw)
    local = Path.cwd() / "config.yaml"
    return local if local.exists() else None


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load(
    config_path: str | Path | None = None,
    env: dict[str, str] | None = None,
    *,
    validate_integrations: bool = True,
):
    env = os.environ if env is None else env
    defaults = yaml.safe_load(_defaults_path().read_text()) or {}
    if config_path is not None:
        path = Path(config_path)
        if not path.is_file():
            raise ConfigError(f"configuration file not found: {path}")
    else:
        path = instance_path(env)
        if env.get("SITE_AGENT_CONFIG") and (path is None or not path.is_file()):
            raise ConfigError(f"configuration file not found: {path}")
    sources = [Path("<package>/defaults.yaml"), path] if path else [Path("<package>/defaults.yaml")]
    override = (yaml.safe_load(path.read_text()) or {}) if path else {}
    if not isinstance(override, dict):
        raise ConfigError(f"configuration root must be a mapping: {path}")
    merged = deep_merge(defaults, override)
    validate_research_config(merged)
    validate_seo_workflow_config(merged)
    if validate_integrations:
        validate_media_config(merged, env)
    validate_design_config(merged)
    return merged, sources


def resolve_secret(
    config: dict[str, Any],
    name: str,
    env: dict[str, str] | None = None,
) -> str:
    """Resolve an instance secret without coupling core code to an adapter."""
    env = os.environ if env is None else env
    var = str((config.get("env") or {}).get(name, ""))
    return env.get(var, "") if var else ""


def load_env_file(path: str | Path, base: dict[str, str] | None = None) -> dict[str, str]:
    """Load a small dotenv file, keeping existing process values authoritative."""
    values = dict(base or {})
    env_path = Path(path)
    if not env_path.is_file():
        return values
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in values:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def resolve_env(config: dict[str, Any], env: dict[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if env is None else env
    mapping = config.get("env") or {}
    resolved = {}
    for name, var in mapping.items():
        value = env.get(str(var), "")
        resolved[name] = {"var": str(var), "set": bool(value)}
    return resolved


def data_dir(config: dict[str, Any], env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    raw = env.get("SITE_AGENT_DATA", "")
    if raw:
        return Path(raw)
    return Path(str(config.get("data_dir", "data")))


def mask_secrets(config: dict[str, Any]) -> dict[str, Any]:
    masked = copy.deepcopy(config)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and any(m in key.lower() for m in _SECRET_MARKERS) and value:
                    node[key] = "***"
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(masked)
    masked.pop("env", None)
    return masked
