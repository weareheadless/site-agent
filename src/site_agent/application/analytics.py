"""Provider-neutral, read-only analytics reporting for one tenant entity.

The owner dashboard uses this service for live GA4 and Search Console detail.
The Google service account remains the only credential involved; no browser
token or personal Google identity is ever sent to this module.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, Callable

from ..hands.google_platform import GooglePlatformClient, GooglePlatformError


class AnalyticsError(RuntimeError):
    """A safe, customer-readable analytics reporting failure."""


GA_OVERVIEW_METRICS = (
    "activeUsers",
    "newUsers",
    "sessions",
    "engagedSessions",
    "engagementRate",
    "screenPageViews",
    "eventCount",
    "averageSessionDuration",
)


def _parse_number(value: Any) -> int | float | str:
    raw = str(value if value is not None else "")
    if raw in {"", "(not set)"}:
        return "—"
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return raw
    return int(number) if number.is_integer() else round(number, 4)


def _delta(current: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for key, value in current.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        old = previous.get(key)
        if not isinstance(old, (int, float)) or isinstance(old, bool) or old == 0:
            result[key] = None
        else:
            result[key] = round((value - old) / old * 100, 1)
    return result


def _ga_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    dimensions = [str(item.get("name") or "") for item in payload.get("dimensionHeaders") or [] if isinstance(item, Mapping)]
    metrics = [str(item.get("name") or "") for item in payload.get("metricHeaders") or [] if isinstance(item, Mapping)]
    rows: list[dict[str, Any]] = []
    for row in payload.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        values: dict[str, Any] = {}
        for index, item in enumerate(row.get("dimensionValues") or []):
            if index < len(dimensions) and isinstance(item, Mapping):
                values[dimensions[index]] = str(item.get("value") or "")
        for index, item in enumerate(row.get("metricValues") or []):
            if index < len(metrics) and isinstance(item, Mapping):
                values[metrics[index]] = _parse_number(item.get("value"))
        rows.append(values)
    return rows


def _gsc_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in payload.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        keys = row.get("keys") or []
        values = {
            "clicks": round(float(row.get("clicks") or 0), 2),
            "impressions": int(float(row.get("impressions") or 0)),
            "ctr": round(float(row.get("ctr") or 0), 4),
            "position": round(float(row.get("position") or 0), 1),
        }
        if keys:
            values["key"] = str(keys[0])
        rows.append(values)
    return rows


class GoogleAnalyticsService:
    """Read the full reporting surface for one provisioned tenant entity."""

    def __init__(
        self,
        config: Mapping[str, Any],
        google: GooglePlatformClient,
        state: Mapping[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.google = google
        self.state = state if isinstance(state, Mapping) else {}

    def _value(self, key: str, fallback: str = "") -> str:
        state_value = str(self.state.get(key) or "").strip()
        if state_value:
            return state_value
        seo = self.config.get("seo") if isinstance(self.config.get("seo"), Mapping) else {}
        if key == "site_url":
            return str(seo.get("site_url") or fallback).strip()
        if key == "ga4_property_id":
            ga = self.config.get("ga") if isinstance(self.config.get("ga"), Mapping) else {}
            return str(ga.get("property_id") or fallback).strip()
        return fallback

    @staticmethod
    def _window(days: int) -> dict[str, str | int]:
        # Google Search Console exposes up to roughly 16 months of Search
        # Analytics history. Keep the owner workspace within that window and
        # let the UI request the same long-range history for GA4.
        bounded = max(7, min(int(days), 540))
        end = datetime.date.today() - datetime.timedelta(days=1)
        start = end - datetime.timedelta(days=bounded - 1)
        previous_end = start - datetime.timedelta(days=1)
        previous_start = previous_end - datetime.timedelta(days=bounded - 1)
        return {
            "days": bounded,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "previousStartDate": previous_start.isoformat(),
            "previousEndDate": previous_end.isoformat(),
        }

    def _ga_report(
        self,
        property_id: str,
        *,
        start: str,
        end: str,
        metrics: tuple[str, ...],
        dimensions: tuple[str, ...] = (),
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "dateRanges": [{"startDate": start, "endDate": end}],
            "metrics": [{"name": name} for name in metrics],
            "limit": limit,
        }
        if dimensions:
            body["dimensions"] = [{"name": name} for name in dimensions]
        if dimensions and metrics:
            body["orderBys"] = [{"metric": {"metricName": metrics[0]}, "desc": True}]
        return _ga_rows(self.google.run_analytics_report(property_id, body))

    def _gsc_report(
        self,
        property_url: str,
        *,
        start: str,
        end: str,
        dimensions: tuple[str, ...] = (),
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "startDate": start,
            "endDate": end,
            "type": "web",
            "rowLimit": limit,
        }
        if dimensions:
            body["dimensions"] = list(dimensions)
        return _gsc_rows(self.google.run_search_console_report(property_url, body))

    @staticmethod
    def _attempt(
        errors: dict[str, str],
        name: str,
        fn: Callable[[], Any],
        fallback: Any,
    ) -> Any:
        try:
            return fn()
        except (GooglePlatformError, OSError, ValueError, TypeError) as exc:
            errors[name] = str(exc)[:300]
            return fallback

    def report(self, days: int = 28) -> dict[str, Any]:
        window = self._window(days)
        property_id = self._value("ga4_property_id")
        property_url = self._value("gsc_property") or self._value("site_url")
        if not property_id and not property_url:
            raise AnalyticsError("analytics properties are not configured")

        errors: dict[str, str] = {}
        ga4: dict[str, Any] = {"available": bool(property_id), "overview": {}, "trend": [], "channels": [], "pages": [], "events": [], "devices": [], "countries": []}
        gsc: dict[str, Any] = {"available": bool(property_url), "overview": {}, "trend": [], "queries": [], "pages": [], "devices": [], "countries": []}

        trend_limit = max(100, min(int(window["days"]) + 7, 600))

        if property_id:
            current = self._attempt(
                errors,
                "ga4.overview",
                lambda: (self._ga_report(property_id, start=str(window["startDate"]), end=str(window["endDate"]), metrics=GA_OVERVIEW_METRICS, limit=1) or [{}])[0],
                {},
            )
            previous = self._attempt(
                errors,
                "ga4.previous",
                lambda: (self._ga_report(property_id, start=str(window["previousStartDate"]), end=str(window["previousEndDate"]), metrics=GA_OVERVIEW_METRICS, limit=1) or [{}])[0],
                {},
            )
            ga4["overview"] = {"current": current, "previous": previous, "deltaPct": _delta(current, previous)}
            ga4["trend"] = self._attempt(
                errors,
                "ga4.trend",
                lambda: self._ga_report(property_id, start=str(window["startDate"]), end=str(window["endDate"]), metrics=("sessions", "activeUsers", "screenPageViews"), dimensions=("date",), limit=trend_limit),
                [],
            )
            ga4["channels"] = self._attempt(
                errors,
                "ga4.channels",
                lambda: self._ga_report(property_id, start=str(window["startDate"]), end=str(window["endDate"]), metrics=("sessions", "activeUsers", "engagementRate"), dimensions=("sessionDefaultChannelGroup",), limit=12),
                [],
            )
            ga4["pages"] = self._attempt(
                errors,
                "ga4.pages",
                lambda: self._ga_report(property_id, start=str(window["startDate"]), end=str(window["endDate"]), metrics=("screenPageViews", "sessions"), dimensions=("landingPagePlusQueryString",), limit=12),
                [],
            )
            ga4["events"] = self._attempt(
                errors,
                "ga4.events",
                lambda: self._ga_report(property_id, start=str(window["startDate"]), end=str(window["endDate"]), metrics=("eventCount",), dimensions=("eventName",), limit=12),
                [],
            )
            ga4["devices"] = self._attempt(
                errors,
                "ga4.devices",
                lambda: self._ga_report(property_id, start=str(window["startDate"]), end=str(window["endDate"]), metrics=("sessions", "activeUsers"), dimensions=("deviceCategory",), limit=8),
                [],
            )
            ga4["countries"] = self._attempt(
                errors,
                "ga4.countries",
                lambda: self._ga_report(property_id, start=str(window["startDate"]), end=str(window["endDate"]), metrics=("sessions", "activeUsers"), dimensions=("country",), limit=12),
                [],
            )

        if property_url:
            current = self._attempt(
                errors,
                "gsc.overview",
                lambda: (self._gsc_report(property_url, start=str(window["startDate"]), end=str(window["endDate"]), limit=1) or [{}])[0],
                {},
            )
            previous = self._attempt(
                errors,
                "gsc.previous",
                lambda: (self._gsc_report(property_url, start=str(window["previousStartDate"]), end=str(window["previousEndDate"]), limit=1) or [{}])[0],
                {},
            )
            gsc["overview"] = {"current": current, "previous": previous, "deltaPct": _delta(current, previous)}
            gsc["trend"] = self._attempt(
                errors,
                "gsc.trend",
                lambda: self._gsc_report(property_url, start=str(window["startDate"]), end=str(window["endDate"]), dimensions=("date",), limit=trend_limit),
                [],
            )
            for key, dimension in (("queries", "query"), ("pages", "page"), ("devices", "device"), ("countries", "country")):
                gsc[key] = self._attempt(
                    errors,
                    f"gsc.{key}",
                    lambda dimension=dimension: self._gsc_report(property_url, start=str(window["startDate"]), end=str(window["endDate"]), dimensions=(dimension,), limit=12),
                    [],
                )

        return {
            "capturedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "window": window,
            "entity": {
                "siteUrl": self._value("site_url"),
                "gscProperty": property_url,
                "ga4PropertyId": property_id,
                "ga4MeasurementId": self._value("ga4_measurement_id"),
                "displayName": self._value("project_name"),
            },
            "ga4": ga4,
            "gsc": gsc,
            "errors": errors,
        }


__all__ = ["AnalyticsError", "GoogleAnalyticsService"]
