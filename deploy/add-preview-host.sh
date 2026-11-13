#!/usr/bin/env bash
# Serve one site's previews at preview.<site domain>.
#
# Run on the API host as root:
#
#   sudo deploy/add-preview-host.sh preview.astridrincon.com
#
# Prerequisites, in this order:
#   1. The tenant config names the same host under `preview.host`. The API
#      creates the proxied DNS record on its next start; this script does not
#      touch DNS.
#   2. The record already resolves to this host (Cloudflare proxied), so the
#      ACME challenge below reaches nginx.
#
# The script is idempotent: an existing certificate is kept until it expires.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: sudo $0 preview.<site-domain>" >&2
  exit 2
fi
host=$1
if ! [[ "$host" =~ ^preview\.[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]]; then
  echo "not a bare preview hostname: $host" >&2
  exit 2
fi

template="$(cd "$(dirname "$0")" && pwd)/nginx-preview-site.conf.template"
available="/etc/nginx/sites-available/$host.conf"
enabled="/etc/nginx/sites-enabled/$host.conf"
webroot=/var/www/certbot

install -d -m 0755 "$webroot/.well-known/acme-challenge"

# The 443 block needs the certificate, so serve plain HTTP first: the challenge
# file has to be reachable before there is anything to terminate TLS with.
cat >"$available" <<EOF
# Bootstrap for $host: ACME only, replaced below once the certificate exists.
server {
    listen 80;
    listen [::]:80;
    server_name $host;

    location /.well-known/acme-challenge/ {
        root $webroot;
        try_files \$uri =404;
    }

    location / {
        return 503;
    }
}
EOF
ln -sfn "$available" "$enabled"
nginx -t
systemctl reload nginx

certbot certonly --webroot -w "$webroot" -d "$host" \
  --non-interactive --agree-tos --keep-until-expiring --key-type ecdsa

sed "s/__PREVIEW_HOST__/$host/g" "$template" >"$available"
nginx -t
systemctl reload nginx

echo "preview host ready: https://$host"
