#!/usr/bin/env python3
"""Provision GA4 + Search Console + CrawlSEO for one public site.

This is the standalone path for sites that are not full HelloAda/Payload
tenants: it runs the same provisioning service the workspace bootstrap uses,
but stops before runtime binding delivery. The credentials are written next to
the site's data directory, and the receipt is printed without the one-time
tokens.

Usage:
  provision-seo-site.py \
    --tenant alaguillotine \
    --domain alaguillotine.com \
    --project-name "A LA GUILLOTINE" \
    --ga4-property-id 547709189
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from site_agent.application.seo_provisioning import (  # noqa: E402
    SeoProvisioningService,
    write_connector_runtime_token,
    write_token_env,
)
from site_agent.credentials import credential_environment  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--site-url", default="")
    parser.add_argument("--ga4-property-id", default="")
    parser.add_argument("--gsc-property", default="")
    parser.add_argument("--verification-method", default="dns_txt", choices=("dns_txt", "meta"))
    parser.add_argument("--organization-id", default="helloada")
    parser.add_argument("--time-zone", default="UTC")
    parser.add_argument("--currency", default="USD")
    parser.add_argument(
        "--credentials-profile",
        default="/SOCIAL/configs/host-credentials.yaml",
    )
    parser.add_argument(
        "--websites-root",
        default="/SOCIAL/site-agent-api/websites",
    )
    parser.add_argument("--idempotency-key", default="")
    args = parser.parse_args()

    tenant = args.tenant.strip().lower()
    domain = args.domain.strip().lower().rstrip(".")
    site_url = args.site_url.strip() or f"https://{domain}/"
    if not site_url.endswith("/"):
        site_url += "/"

    website_dir = Path(args.websites_root).expanduser().resolve() / tenant
    data_dir = website_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "data_dir": str(data_dir),
        "credentials": {"profile_file": args.credentials_profile},
        "site": {"public_url": site_url},
        "seo": {
            "enabled": True,
            "site_url": site_url,
            "provisioning": {
                "auto": True,
                "verification_method": args.verification_method,
                "project_name": args.project_name,
                "organization_id": args.organization_id,
                "time_zone": args.time_zone,
                "currency_code": args.currency,
                "idempotency_key": args.idempotency_key or f"site-agent:{tenant}:v1",
            },
        },
    }

    env = credential_environment(config, os.environ)
    service = SeoProvisioningService(config, env)
    receipt = service.provision(
        tenant_id=tenant,
        domain=domain,
        project_name=args.project_name,
        organization_id=args.organization_id,
        site_url=site_url,
        gsc_property=args.gsc_property or f"sc-domain:{domain}",
        ga4_property_id=args.ga4_property_id,
        time_zone=args.time_zone,
        currency_code=args.currency,
        verification_method=args.verification_method,
        domain_verification_method="verified_gsc",
        idempotency_key=args.idempotency_key or f"site-agent:{tenant}:v1",
    )

    token = str(receipt.get("credential_token") or "").strip()
    if token:
        token_env = str(receipt.get("token_env") or "").strip()
        if not token_env:
            raise SystemExit("CrawlSEO returned a token without an environment name")
        write_token_env(website_dir, token_env, token)
        env[token_env] = token
    connector = str(receipt.get("connector_credential_token") or "").strip()
    if connector:
        write_connector_runtime_token(website_dir, connector)

    safe = dict(receipt)
    safe.pop("credential_token", None)
    safe.pop("connector_credential_token", None)
    receipt_path = website_dir / "seo-receipt.json"
    receipt_path.write_text(json.dumps(safe, indent=2, default=str) + "\n", encoding="utf-8")
    os.chmod(receipt_path, 0o600)

    print(json.dumps(safe, indent=2, default=str))
    print(f"\ncredentials: {website_dir / 'crawlseo.env'}")
    print(f"connector:   {website_dir / 'crawlseo-connector-runtime.env'}")
    print(f"receipt:     {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
