"""Platform-managed SEO provisioning for a tenant.

One call turns a domain into working SEO plumbing:

1. a GA4 property and web stream under the platform Analytics account;
2. Search Console ownership, verified through a DNS record we control;
3. a CrawlSEO project bound to both, returning the project credential.

Everything is idempotent: properties are reused by display name, verification
re-runs safely, and CrawlSEO converges on the external project id. A failure in
one step never deletes work already done; the caller decides whether to retry.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..credentials import credential_environment, credential_profile
from ..hands.cloudflare_dns import CloudflareDNSClient, CloudflareDNSError
from ..hands.crawlseo_provisioning import CrawlSEOProvisioningClient, CrawlSEOProvisioningError
from ..hands.google_platform import GooglePlatformClient, GooglePlatformError

_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class SeoProvisioningError(RuntimeError):
    """A safe, customer-readable provisioning failure."""


def tenant_token_env(tenant_id: str) -> str:
    """A per-tenant environment variable name for the CrawlSEO token."""
    name = str(tenant_id or "").strip().lower()
    if not _SAFE_NAME.fullmatch(name):
        raise SeoProvisioningError("tenant id must be a lowercase slug")
    return "CRAWLSEO_TOKEN_" + name.replace("-", "_").upper()


def write_token_env(directory: str | Path, token_env: str, token: str) -> Path:
    """Persist one tenant credential in a 0600 env file next to its config."""
    target = Path(directory).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    path = target / "crawlseo.env"
    body = (
        "# Written by Ada SEO provisioning. The CrawlSEO project credential is\n"
        "# shown once by the provisioning endpoint and cannot be retrieved later.\n"
        f"{token_env}={token}\n"
    )
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(body, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return path


class SeoProvisioningService:
    """Reads the host credential profiles and provisions one tenant's SEO."""

    def __init__(
        self,
        config: Mapping[str, Any],
        env: Mapping[str, str] | None = None,
        *,
        google: GooglePlatformClient | None = None,
        dns: CloudflareDNSClient | None = None,
        crawlseo: CrawlSEOProvisioningClient | None = None,
    ) -> None:
        self.config = config
        self.env = credential_environment(config, os.environ if env is None else env)
        self._google = google
        self._dns = dns
        self._crawlseo = crawlseo

    # -- profile helpers --------------------------------------------------

    def _google_profile(self) -> Mapping[str, Any]:
        return credential_profile(self.config, "google")

    def google_client(self) -> GooglePlatformClient:
        if self._google is not None:
            return self._google
        profile = self._google_profile()
        path = str(profile.get("service_account_file") or "").strip()
        scopes = profile.get("scopes") if isinstance(profile.get("scopes"), list) else ()
        if not path:
            raise SeoProvisioningError("credentials.google.service_account_file is not configured")
        self._google = GooglePlatformClient(path, scopes=scopes or ())
        return self._google

    def dns_client(self) -> CloudflareDNSClient:
        if self._dns is not None:
            return self._dns
        profile = credential_profile(self.config, "cloudflare_dns")
        variable = str(profile.get("api_token_env") or "CLOUDFLARE_DNS_API_TOKEN")
        token = str(self.env.get(variable) or "")
        if not token:
            raise SeoProvisioningError(f"{variable} is not set")
        self._dns = CloudflareDNSClient(token)
        return self._dns

    def crawlseo_client(self) -> CrawlSEOProvisioningClient:
        if self._crawlseo is not None:
            return self._crawlseo
        profile = credential_profile(self.config, "crawlseo")
        url = str(profile.get("provisioning_url") or "").strip()
        variable = str(profile.get("provisioning_token_env") or "HELLOADA_PROVISIONING_TOKEN")
        token = str(self.env.get(variable) or "")
        if not url:
            raise SeoProvisioningError("credentials.crawlseo.provisioning_url is not configured")
        if not token:
            raise SeoProvisioningError(f"{variable} is not set")
        self._crawlseo = CrawlSEOProvisioningClient(url, token)
        return self._crawlseo

    def crawlseo_mcp_url(self) -> str:
        return str(credential_profile(self.config, "crawlseo").get("mcp_url") or "").strip()

    @staticmethod
    def _zone_id_for_hostname(dns: CloudflareDNSClient, hostname: str) -> str:
        resolver = getattr(dns, "zone_id_for_hostname", None)
        if callable(resolver):
            return str(resolver(hostname))
        # Compatibility seam for small test doubles and older adapters.
        labels = str(hostname).strip().rstrip(".").split(".")
        return str(dns.zone_id(".".join(labels[-2:]) if len(labels) > 1 else labels[0]))

    @property
    def platform_available(self) -> bool:
        """True when the host has both the Google and CrawlSEO wiring."""
        google = self._google_profile()
        crawlseo = credential_profile(self.config, "crawlseo")
        return bool(google.get("service_account_file") and crawlseo.get("provisioning_url"))

    # -- the provisioning call -------------------------------------------

    def verify_gsc(
        self,
        *,
        identifier: str,
        property_url: str,
        method: str = "META",
        site_type: str = "SITE",
    ) -> dict[str, Any]:
        """Complete a deferred Search Console verification.

        Used after the site has rendered a previously issued meta tag; safe to
        re-run because verification is idempotent.
        """
        self.google_client().verify_domain(identifier, method=method, site_type=site_type)
        self.google_client().add_search_console_site(property_url)
        return {
            "identifier": identifier,
            "property": property_url,
            "method": method,
            "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        }

    def provision(
        self,
        *,
        tenant_id: str,
        domain: str,
        project_name: str,
        organization_id: str = "helloada",
        site_url: str = "",
        gsc_property: str = "",
        ga4_property_id: str = "",
        time_zone: str = "UTC",
        currency_code: str = "EUR",
        verify_gsc: bool = True,
        verification_method: str = "dns_txt",
        domain_verification_method: str = "verified_gsc",
        ensure_host_resolves: bool = False,
        idempotency_key: str = "",
        recover_service_credential: bool = False,
    ) -> dict[str, Any]:
        clean_domain = str(domain or "").strip().lower().rstrip(".")
        if not clean_domain or "/" in clean_domain:
            raise SeoProvisioningError("a bare domain is required")
        project_id = str(tenant_id or "").strip().lower()
        if not _SAFE_NAME.fullmatch(project_id):
            raise SeoProvisioningError("tenant id must be a lowercase slug")
        token_env = tenant_token_env(project_id)

        receipt: dict[str, Any] = {
            "tenant_id": project_id,
            "domain": clean_domain,
            "site_url": str(site_url or f"https://{clean_domain}/").strip(),
            "project_name": str(project_name or "").strip()[:200],
            "token_env": token_env,
            "provisioned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        }

        # 1. GA4 -----------------------------------------------------------
        account = str(self._google_profile().get("platform_analytics_account") or "").strip()
        if ga4_property_id:
            receipt["ga4_property_id"] = str(ga4_property_id)
            receipt["ga4_created"] = False
        else:
            if not account:
                raise SeoProvisioningError("credentials.google.platform_analytics_account is not configured")
            property_info = self.google_client().create_property(
                account, project_name, time_zone=time_zone, currency_code=currency_code
            )
            receipt["ga4_property_id"] = property_info["property_id"]
            receipt["ga4_created"] = bool(property_info.get("created"))
        stream = self.google_client().ensure_web_stream(
            receipt["ga4_property_id"],
            site_url or f"https://{clean_domain}",
            display_name=project_name,
        )
        rename = getattr(self.google_client(), "ensure_property_display_name", None)
        if callable(rename):
            receipt["ga4_display_name"] = rename(receipt["ga4_property_id"], project_name)
        receipt["ga4_measurement_id"] = stream.get("measurement_id")
        receipt["ga4_stream_created"] = bool(stream.get("created"))

        # 2. Search Console ------------------------------------------------
        verification_method = str(verification_method or "dns_txt").strip().lower()
        if verification_method not in {"meta", "dns_txt"}:
            raise SeoProvisioningError("verification_method must be meta or dns_txt")
        if verification_method == "meta":
            # Platform-hosted pages (e.g. a workers.dev site) cannot be
            # DNS-verified; the meta tag we control the <head> for is the
            # portable path. The property is the URL, not the domain.
            identifier = str(site_url or f"https://{clean_domain}/").strip().rstrip("/")
            if not identifier.startswith(("http://", "https://")):
                identifier = f"https://{identifier}"
            property_url = str(gsc_property or site_url or identifier).strip()
        else:
            identifier = clean_domain
            property_url = gsc_property or f"sc-domain:{clean_domain}"
        receipt["gsc_property"] = property_url
        receipt["gsc_verification_method"] = verification_method
        if verify_gsc:
            if verification_method == "meta":
                tag = self.google_client().verification_token(identifier, method="META", site_type="SITE")
                receipt["gsc_meta_tag"] = tag
                receipt["gsc_meta_identifier"] = identifier
                try:
                    self.google_client().verify_domain(identifier, method="META", site_type="SITE")
                except GooglePlatformError:
                    receipt["gsc_verified"] = False
                    receipt["gsc_pending"] = "the meta tag is not live on the site yet"
                else:
                    self.google_client().add_search_console_site(property_url)
                    receipt["gsc_verified"] = True
                    receipt["gsc_verified_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
            else:
                dns = self.dns_client()
                if ensure_host_resolves:
                    zone = clean_domain
                    try:
                        zone_id = self._zone_id_for_hostname(dns, zone)
                        dns.ensure_public_host(zone_id, clean_domain)
                    except CloudflareDNSError:
                        pass
                token = self.google_client().verification_token(clean_domain)
                zone_id = self._zone_id_for_hostname(dns, clean_domain)
                dns.upsert_txt(zone_id, clean_domain, token)
                self.google_client().verify_domain(clean_domain)
                self.google_client().add_search_console_site(property_url)
                receipt["gsc_verified"] = True
                receipt["gsc_verified_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

        # Do not create a CrawlSEO project or queue doomed Google jobs while a
        # platform-hosted Worker is still waiting for its verification tag. The
        # bootstrapper installs the tag and calls this method again.
        if verify_gsc and receipt.get("gsc_verified") is False:
            receipt["provisioning_state"] = "awaiting_gsc_verification"
            receipt["crawlseo_pending"] = True
            return receipt

        # 3. CrawlSEO project ---------------------------------------------
        google_profile = self._google_profile()
        service_account_file = Path(str(google_profile.get("service_account_file"))).expanduser()
        try:
            credentials_document = json.loads(service_account_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SeoProvisioningError("google service-account file is unreadable") from exc

        response = self.crawlseo_client().provision(
            {
                "externalOrganizationId": organization_id,
                "workspaceName": organization_id,
                "externalProjectId": project_id,
                "projectName": project_name,
                "domain": clean_domain,
                "gscProperty": property_url,
                "ga4PropertyId": str(receipt["ga4_property_id"]),
                "serviceAccountCredentials": credentials_document,
                "serviceCredentialIdempotencyKey": idempotency_key or f"site-agent:{project_id}:v1",
                "reissueCredential": bool(recover_service_credential),
                "domainVerificationMethod": domain_verification_method,
            }
        )
        receipt["crawlseo"] = {
            "workspace_id": response.get("workspace_id"),
            "project_id": response.get("project_id"),
            "site_id": response.get("site_id"),
            "credential_id": response.get("credential_id"),
            "credential_reused": response.get("credential_reused"),
            "dataforseo_grant_source": response.get("dataforseo_grant_source"),
            "jobs": response.get("jobs"),
        }
        token = response.get("credential_token")
        receipt["credential_token"] = str(token) if token else ""
        receipt["credential_issued"] = bool(token)
        receipt["provisioning_state"] = "ready"
        return receipt


__all__ = [
    "SeoProvisioningError",
    "SeoProvisioningService",
    "tenant_token_env",
    "write_token_env",
]
