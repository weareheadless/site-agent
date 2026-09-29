"""Platform-managed Google provisioning: GA4 properties and Search Console.

The platform owns one Google service account and uses it to create or reconcile
per-tenant analytics properties and to verify Search Console ownership through
the Site Verification API. Tenants never receive this credential; the service
only exposes the resulting property ids and status.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from typing import Any

ANALYTICS_ADMIN = "https://analyticsadmin.googleapis.com/v1beta"
ANALYTICS_ADMIN_ALPHA = "https://analyticsadmin.googleapis.com/v1alpha"
ANALYTICS_DATA = "https://analyticsdata.googleapis.com/v1beta"
SITE_VERIFICATION = "https://www.googleapis.com/siteVerification/v1"
WEBMASTERS = "https://www.googleapis.com/webmasters/v3"
USER_AGENT = "site-agent/0.1 (+https://helloada.app)"

ANALYTICS_EDIT = "https://www.googleapis.com/auth/analytics.edit"
ANALYTICS_READONLY = "https://www.googleapis.com/auth/analytics.readonly"
ANALYTICS_MANAGE_USERS = "https://www.googleapis.com/auth/analytics.manage.users"
WEBMASTERS_SCOPE = "https://www.googleapis.com/auth/webmasters"
WEBMASTERS_READONLY = "https://www.googleapis.com/auth/webmasters.readonly"
SITEVERIFICATION_SCOPE = "https://www.googleapis.com/auth/siteverification"


class GooglePlatformError(RuntimeError):
    """A safe, customer-readable Google provisioning failure."""


def _partial_error(payload: Mapping[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, Mapping):
        return str(error.get("message") or "Google API error")[:300]
    if isinstance(error, str):
        return error[:300]
    return "Google API error"


class GooglePlatformClient:
    """Service-account client for the two provisioning APIs.

    The optional ``google-auth`` dependency is imported lazily so ordinary
    installs keep working without it.
    """

    def __init__(
        self,
        service_account_file: str,
        *,
        scopes: Iterable[str] = (),
        timeout_seconds: float = 30.0,
    ) -> None:
        path = str(service_account_file or "").strip()
        if not path:
            raise GooglePlatformError("google service-account file is missing")
        self._path = path
        self._scopes = tuple(scopes) or (ANALYTICS_EDIT, ANALYTICS_READONLY, WEBMASTERS_SCOPE, SITEVERIFICATION_SCOPE)
        self._timeout = float(timeout_seconds)
        self._tokens: dict[tuple[str, ...], str] = {}

    # -- auth -------------------------------------------------------------

    def access_token(self, scopes: Iterable[str]) -> str:
        wanted = tuple(sorted({str(scope) for scope in scopes if str(scope).strip()}))
        if not wanted:
            raise GooglePlatformError("at least one Google scope is required")
        cached = self._tokens.get(wanted)
        if cached:
            return cached
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise GooglePlatformError("google-auth is not installed") from exc
        credentials = service_account.Credentials.from_service_account_file(self._path, scopes=list(wanted))
        credentials.refresh(Request())
        token = str(getattr(credentials, "token", "") or "")
        if not token:
            raise GooglePlatformError("Google did not return an access token")
        self._tokens[wanted] = token
        return token

    def _request(
        self,
        url: str,
        *,
        scopes: Iterable[str],
        method: str = "GET",
        body: Mapping[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        data = json.dumps(dict(body)).encode() if body is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.access_token(scopes)}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read().decode()
                return int(getattr(response, "status", 200)), (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode() or "{}")
            except (ValueError, UnicodeError):
                payload = {}
            return int(exc.code or 0), payload
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GooglePlatformError(f"Google request failed: {type(exc).__name__}") from exc

    # -- GA4 --------------------------------------------------------------

    def list_account_summaries(self) -> list[dict[str, Any]]:
        status, payload = self._request(
            f"{ANALYTICS_ADMIN}/accountSummaries?pageSize=200", scopes=(ANALYTICS_READONLY,)
        )
        if status != 200:
            raise GooglePlatformError(_partial_error(payload))
        return [dict(item) for item in (payload.get("accountSummaries") or []) if isinstance(item, Mapping)]

    def find_property(self, account_id: str, display_name: str) -> dict[str, Any] | None:
        """Return an existing property with this display name, if any.

        Property creation is not idempotent, so callers look first and reuse.
        """
        wanted = str(display_name or "").strip().casefold()
        for summary in self.list_account_summaries():
            if str(summary.get("account") or "").rstrip("/").split("/")[-1] != str(account_id):
                continue
            for prop in summary.get("propertySummaries") or []:
                if not isinstance(prop, Mapping):
                    continue
                if str(prop.get("displayName") or "").strip().casefold() == wanted:
                    name = str(prop.get("property") or "")
                    return {"property_id": name.split("/")[-1], "property": name, "display_name": prop.get("displayName")}
        return None

    def create_property(
        self,
        account_id: str,
        display_name: str,
        *,
        time_zone: str = "UTC",
        currency_code: str = "EUR",
    ) -> dict[str, Any]:
        existing = self.find_property(account_id, display_name)
        if existing is not None:
            return {**existing, "created": False}
        status, payload = self._request(
            f"{ANALYTICS_ADMIN}/properties",
            scopes=(ANALYTICS_EDIT,),
            method="POST",
            body={
                "parent": f"accounts/{account_id}",
                "displayName": display_name,
                "timeZone": time_zone,
                "currencyCode": currency_code,
            },
        )
        if status not in (200, 201):
            raise GooglePlatformError(_partial_error(payload))
        name = str(payload.get("name") or "")
        if not name:
            raise GooglePlatformError("Google did not return a property id")
        return {
            "property_id": name.split("/")[-1],
            "property": name,
            "display_name": display_name,
            "created": True,
        }

    def ensure_property_display_name(self, property_id: str, display_name: str) -> str:
        """Reconcile an existing property's label with the tenant site name."""
        property_id = str(property_id or "").strip().replace("properties/", "")
        wanted = str(display_name or "").strip()[:128]
        if not property_id or not wanted:
            raise GooglePlatformError("GA4 property id and display name are required")
        status, payload = self._request(
            f"{ANALYTICS_ADMIN}/properties/{urllib.parse.quote(property_id, safe='')}",
            scopes=(ANALYTICS_READONLY,),
        )
        if status != 200:
            raise GooglePlatformError(_partial_error(payload))
        current = str(payload.get("displayName") or "").strip()
        if current.casefold() == wanted.casefold():
            return current or wanted
        status, payload = self._request(
            f"{ANALYTICS_ADMIN}/properties/{urllib.parse.quote(property_id, safe='')}?updateMask=displayName",
            scopes=(ANALYTICS_EDIT,),
            method="PATCH",
            body={"displayName": wanted},
        )
        if status != 200:
            raise GooglePlatformError(_partial_error(payload))
        return str(payload.get("displayName") or wanted)

    def ensure_web_stream(self, property_id: str, site_url: str, *, display_name: str | None = None) -> dict[str, Any]:
        """Return the property's web stream, creating one when absent."""
        status, payload = self._request(
            f"{ANALYTICS_ADMIN}/properties/{property_id}/dataStreams",
            scopes=(ANALYTICS_EDIT,),
        )
        if status != 200:
            raise GooglePlatformError(_partial_error(payload))
        streams = [dict(item) for item in (payload.get("dataStreams") or []) if isinstance(item, Mapping)]
        wanted = str(site_url or "").strip().rstrip("/")
        for stream in streams:
            if str(stream.get("type") or "") != "WEB_DATA_STREAM":
                continue
            default_uri = str(((stream.get("webStreamData") or {}) if isinstance(stream.get("webStreamData"), Mapping) else {}).get("defaultUri") or "").rstrip("/")
            if default_uri == wanted:
                return {
                    "data_stream_id": str(stream.get("name") or "").split("/")[-1],
                    "measurement_id": (stream.get("webStreamData") or {}).get("measurementId"),
                    "created": False,
                }
        status, payload = self._request(
            f"{ANALYTICS_ADMIN}/properties/{property_id}/dataStreams",
            scopes=(ANALYTICS_EDIT,),
            method="POST",
            body={
                "type": "WEB_DATA_STREAM",
                "displayName": display_name or wanted,
                "webStreamData": {"defaultUri": wanted},
            },
        )
        if status not in (200, 201):
            raise GooglePlatformError(_partial_error(payload))
        return {
            "data_stream_id": str(payload.get("name") or "").split("/")[-1],
            "measurement_id": (payload.get("webStreamData") or {}).get("measurementId"),
            "created": True,
        }

    # -- analytics data and access ----------------------------------------

    @staticmethod
    def _property_path(property_id: str) -> str:
        value = str(property_id or "").strip().replace("properties/", "")
        if not value:
            raise GooglePlatformError("GA4 property id is missing")
        return urllib.parse.quote(value, safe="")

    def run_analytics_report(self, property_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """Run a read-only GA4 Data API report for one provisioned property."""
        status, payload = self._request(
            f"{ANALYTICS_DATA}/properties/{self._property_path(property_id)}:runReport",
            scopes=(ANALYTICS_READONLY,),
            method="POST",
            body=body,
        )
        if status != 200:
            raise GooglePlatformError(_partial_error(payload))
        return payload

    def run_search_console_report(self, site_url: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """Run a read-only Search Analytics query for one provisioned URL property."""
        site = str(site_url or "").strip()
        if not site:
            raise GooglePlatformError("Search Console property is missing")
        encoded = urllib.parse.quote(site, safe="")
        status, payload = self._request(
            f"{WEBMASTERS}/sites/{encoded}/searchAnalytics/query",
            scopes=(WEBMASTERS_READONLY,),
            method="POST",
            body=body,
        )
        if status != 200:
            raise GooglePlatformError(_partial_error(payload))
        return payload

    def list_ga4_access_bindings(self, property_id: str) -> list[dict[str, Any]]:
        """List direct GA4 property access grants."""
        status, payload = self._request(
            f"{ANALYTICS_ADMIN_ALPHA}/properties/{self._property_path(property_id)}/accessBindings?pageSize=100",
            scopes=(ANALYTICS_MANAGE_USERS,),
        )
        if status != 200:
            raise GooglePlatformError(_partial_error(payload))
        return [dict(item) for item in (payload.get("accessBindings") or []) if isinstance(item, Mapping)]

    def grant_ga4_access(self, property_id: str, email: str, role: str = "viewer") -> dict[str, Any]:
        """Grant a bounded, non-administrative GA4 role to one user."""
        roles = {
            "viewer": "predefinedRoles/viewer",
            "analyst": "predefinedRoles/analyst",
        }
        selected_role = roles.get(str(role or "").strip().lower())
        address = str(email or "").strip().lower()
        if selected_role is None:
            raise GooglePlatformError("GA4 access role must be viewer or analyst")
        if "@" not in address or len(address) > 254:
            raise GooglePlatformError("a valid Google account email is required")
        status, payload = self._request(
            f"{ANALYTICS_ADMIN_ALPHA}/properties/{self._property_path(property_id)}/accessBindings",
            scopes=(ANALYTICS_MANAGE_USERS,),
            method="POST",
            body={"user": address, "roles": [selected_role]},
        )
        if status not in (200, 201):
            raise GooglePlatformError(_partial_error(payload))
        return payload

    def delete_ga4_access_binding(self, binding_name: str) -> bool:
        """Remove one direct GA4 access binding."""
        name = str(binding_name or "").strip()
        if not name.startswith("properties/") or "/accessBindings/" not in name:
            raise GooglePlatformError("invalid GA4 access binding")
        status, payload = self._request(
            f"{ANALYTICS_ADMIN_ALPHA}/{urllib.parse.quote(name, safe='/')}",
            scopes=(ANALYTICS_MANAGE_USERS,),
            method="DELETE",
        )
        if status not in (200, 204):
            raise GooglePlatformError(_partial_error(payload))
        return True

    # -- Search Console ---------------------------------------------------

    def verification_token(
        self,
        identifier: str,
        *,
        method: str = "DNS_TXT",
        site_type: str = "INET_DOMAIN",
    ) -> str:
        """Request a verification token for a domain (DNS) or URL (META/FILE)."""
        status, payload = self._request(
            f"{SITE_VERIFICATION}/token",
            scopes=(SITEVERIFICATION_SCOPE,),
            method="POST",
            body={"site": {"type": site_type, "identifier": identifier}, "verificationMethod": method},
        )
        token = str(payload.get("token") or "")
        if status != 200 or not token:
            raise GooglePlatformError(_partial_error(payload))
        return token

    def verify_domain(
        self,
        identifier: str,
        *,
        method: str = "DNS_TXT",
        site_type: str = "INET_DOMAIN",
    ) -> bool:
        """Ask Google to verify ownership using the method already prepared."""
        status, payload = self._request(
            f"{SITE_VERIFICATION}/webResource?verificationMethod={urllib.parse.quote(method)}",
            scopes=(SITEVERIFICATION_SCOPE,),
            method="POST",
            body={"site": {"type": site_type, "identifier": identifier}},
        )
        if status == 200:
            return True
        if status == 409:  # already verified
            return True
        raise GooglePlatformError(_partial_error(payload))

    def add_search_console_site(self, site_url: str) -> None:
        encoded = urllib.parse.quote(str(site_url), safe="")
        status, payload = self._request(
            f"{WEBMASTERS}/sites/{encoded}", scopes=(WEBMASTERS_SCOPE,), method="PUT"
        )
        if status not in (200, 204):
            raise GooglePlatformError(_partial_error(payload))

    def delete_search_console_site(self, site_url: str) -> bool:
        encoded = urllib.parse.quote(str(site_url), safe="")
        status, _payload = self._request(
            f"{WEBMASTERS}/sites/{encoded}", scopes=(WEBMASTERS_SCOPE,), method="DELETE"
        )
        return status in (200, 204)

    def list_search_console_sites(self) -> list[str]:
        status, payload = self._request(f"{WEBMASTERS}/sites", scopes=(WEBMASTERS_SCOPE,))
        if status != 200:
            raise GooglePlatformError(_partial_error(payload))
        return [str(entry.get("siteUrl") or "") for entry in (payload.get("siteEntry") or []) if isinstance(entry, Mapping)]


__all__ = [
    "ANALYTICS_EDIT",
    "ANALYTICS_MANAGE_USERS",
    "ANALYTICS_READONLY",
    "SITEVERIFICATION_SCOPE",
    "WEBMASTERS_SCOPE",
    "GooglePlatformClient",
    "GooglePlatformError",
]
