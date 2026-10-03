"""Small provider-neutral contracts for Ada's shared growth loop.

The first contract is deliberately boring: it describes policy and durable
state, but it cannot call a provider, publish a site, or infer an owner goal.
That keeps the scheduler, application service and owner projection honest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class GrowthContractError(ValueError):
    """Raised when a growth policy cannot be safely interpreted."""


DEFAULT_GROWTH_TIMEZONE = "UTC"
DEFAULT_GROWTH_GOAL_KEY = "relevant_visitors"
DEFAULT_GROWTH_OBJECTIVE = "Bring relevant visitors to my website"
DEFAULT_GROWTH_METRICS = ("gsc_clicks", "ga4_engaged_sessions", "qualified_events")


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
    timezone: str
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
            max_recommendations = int(block.get("max_recommendations", 3))
            max_active_candidates = int(block.get("max_active_candidates", 2))
        except (TypeError, ValueError) as exc:
            raise GrowthContractError("growth recommendation limits must be integers") from exc
        if not 1 <= max_recommendations <= 10:
            raise GrowthContractError("growth.max_recommendations must be between 1 and 10")
        if not 1 <= max_active_candidates <= 10:
            raise GrowthContractError("growth.max_active_candidates must be between 1 and 10")
        return cls(
            timezone=growth_timezone(config),
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

