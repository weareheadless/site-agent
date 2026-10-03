"""Small provider-neutral contracts for Ada's shared growth loop.

The first contract is deliberately boring: it describes policy and durable
state, but it cannot call a provider, publish a site, or infer an owner goal.
That keeps the scheduler, application service and owner projection honest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class GrowthContractError(ValueError):
    """Raised when a growth policy cannot be safely interpreted."""


DEFAULT_GROWTH_TIMEZONE = "UTC"
DEFAULT_GROWTH_GOAL_KEY = "relevant_visitors"
DEFAULT_GROWTH_OBJECTIVE = "Bring relevant visitors to my website"
DEFAULT_GROWTH_METRICS = ("gsc_clicks", "ga4_engaged_sessions", "qualified_events")


def _origin_revision(config: Mapping[str, Any]) -> str:
    site = config.get("site") if isinstance(config.get("site"), Mapping) else {}
    seo = config.get("seo") if isinstance(config.get("seo"), Mapping) else {}
    raw = str(site.get("public_url") or site.get("custom_domain") or seo.get("site_url") or seo.get("url") or seo.get("preview_url") or "").strip().rstrip("/")
    if not raw:
        return "unconfigured"
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    origin = f"{parsed.scheme.lower()}://{(parsed.netloc or '').lower()}".rstrip("/")
    return "unconfigured" if not origin or origin == "://" else "origin-" + hashlib.sha256(origin.encode("utf-8")).hexdigest()[:16]


def growth_timezone(config: Mapping[str, Any] | None) -> str:
    """Resolve one explicit IANA timezone for product growth cadence.

    Existing tenants may have the timezone under one of the historical SEO
    blocks. New configuration should use ``growth.timezone``. An invalid value
    is an error; the scheduler must not silently move a tenant to server time.
    """

    config = config or {}
    growth = config.get("growth") if isinstance(config.get("growth"), Mapping) else {}
    seo = config.get("seo") if isinstance(config.get("seo"), Mapping) else {}
    research = seo.get("research") if isinstance(seo.get("research"), Mapping) else {}
    site_report = seo.get("site_report") if isinstance(seo.get("site_report"), Mapping) else {}
    value = str(
        growth.get("timezone")
        or research.get("timezone")
        or site_report.get("timezone")
        or DEFAULT_GROWTH_TIMEZONE
    ).strip()
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise GrowthContractError("growth timezone must be a valid IANA timezone") from exc
    return value


@dataclass(frozen=True)
class GrowthPolicy:
    policy_version: int
    timezone: str
    origin_revision: str
    audience: str = ""
    language: str = ""
    market: str = ""
    freshness_hours: dict[str, int] = field(default_factory=dict)
    research_allowance_micros: int = 500_000
    approval_required: bool = True
    default_goal_key: str = DEFAULT_GROWTH_GOAL_KEY
    review_cadence: str = "weekly"
    research_cadence: str = "monthly"
    max_recommendations: int = 3
    max_active_candidates: int = 2

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> "GrowthPolicy":
        config = config or {}
        block = config.get("growth") if isinstance(config.get("growth"), Mapping) else {}
        try:
            policy_version = int(block.get("policy_version", 1))
            max_recommendations = int(block.get("max_recommendations", 3))
            max_active_candidates = int(block.get("max_active_candidates", 2))
        except (TypeError, ValueError) as exc:
            raise GrowthContractError("growth policy version and recommendation limits must be integers") from exc
        if policy_version < 1:
            raise GrowthContractError("growth.policy_version must be positive")
        if not 1 <= max_recommendations <= 10:
            raise GrowthContractError("growth.max_recommendations must be between 1 and 10")
        if not 1 <= max_active_candidates <= 10:
            raise GrowthContractError("growth.max_active_candidates must be between 1 and 10")
        freshness = block.get("freshness_hours", {})
        try:
            freshness_hours = {str(key): int(value) for key, value in freshness.items()} if isinstance(freshness, Mapping) else {"default": int(freshness)}
        except (TypeError, ValueError) as exc:
            raise GrowthContractError("growth freshness hours must be integers") from exc
        if any(value < 1 for value in freshness_hours.values()):
            raise GrowthContractError("growth freshness hours must be positive")
        try:
            allowance = int(block.get("monthly_research_cap_micros", 500_000))
        except (TypeError, ValueError) as exc:
            raise GrowthContractError("growth.monthly_research_cap_micros must be an integer") from exc
        if allowance < 0:
            raise GrowthContractError("growth.monthly_research_cap_micros cannot be negative")
        research = config.get("seo") if isinstance(config.get("seo"), Mapping) else {}
        research = research.get("research") if isinstance(research.get("research"), Mapping) else {}
        profile = config.get("customer_profile") if isinstance(config.get("customer_profile"), Mapping) else {}
        persona = config.get("persona") if isinstance(config.get("persona"), Mapping) else {}
        locales = research.get("languages") if isinstance(research.get("languages"), list) else []
        primary_locale = locales[0] if locales and isinstance(locales[0], Mapping) else {}
        markets = primary_locale.get("markets") if isinstance(primary_locale.get("markets"), list) else []
        return cls(
            policy_version=policy_version,
            timezone=growth_timezone(config),
            origin_revision=str(block.get("origin_revision") or _origin_revision(config)).strip(),
            audience=str(profile.get("audience") or persona.get("audience") or "").strip(),
            language=str(research.get("language") or primary_locale.get("code") or "").strip(),
            market=str(research.get("market") or (markets[0] if markets else "") or "").strip(),
            freshness_hours=freshness_hours,
            research_allowance_micros=allowance,
            approval_required=bool(block.get("approval_required", True)),
            default_goal_key=str(block.get("default_goal_key") or DEFAULT_GROWTH_GOAL_KEY).strip(),
            review_cadence=str(block.get("review_cadence") or "weekly").strip(),
            research_cadence=str(block.get("research_cadence") or "monthly").strip(),
            max_recommendations=max_recommendations,
            max_active_candidates=max_active_candidates,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GrowthGoalRevision:
    revision: int
    goal_key: str
    objective: str
    metrics: tuple[str, ...]
    confirmed_by: str
    confirmed_ts: str
    source: str

    @classmethod
    def default(cls, *, confirmed_ts: str | None = None) -> "GrowthGoalRevision":
        return cls(
            revision=0,
            goal_key=DEFAULT_GROWTH_GOAL_KEY,
            objective=DEFAULT_GROWTH_OBJECTIVE,
            metrics=DEFAULT_GROWTH_METRICS,
            confirmed_by="new_site_provisioning",
            confirmed_ts=confirmed_ts or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source="new_site_default",
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["metrics"] = list(self.metrics)
        return result


def decode_goal(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    result = dict(row)
    metrics = result.get("metrics")
    if not isinstance(metrics, list):
        result["metrics"] = []
    return result
