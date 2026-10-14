#!/usr/bin/env bash
set -euo pipefail
umask 077
if [[ "${1:-}" != "--owner-authorized" ]]; then echo 'Use --owner-authorized after owner deploy command'; exit 2; fi
cd -- "$(dirname -- "$0")/../.."
if [[ ! -f .env ]]; then echo 'Provision .env separately with mode 600'; exit 1; fi
chmod 600 .env
compose=(docker compose -p cyber-digest -f compose.yml -f compose.server.yml)
if ss -H -ltn 'sport = :6752' | grep -q .; then
    existing=$("${compose[@]}" ps -q nginx)
    if [[ -z "$existing" ]]; then echo 'Port 6752 belongs to another service'; exit 1; fi
fi
mkdir -p work/backups shared/acme shared/letsencrypt
chmod 755 shared/acme
if [[ -n "$("${compose[@]}" ps -q postgres)" ]]; then
    "${compose[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "work/backups/pre-deploy-$(date -u +%Y%m%dT%H%M%SZ).sql"
fi
"${compose[@]}" config --quiet
if [[ ! -f shared/letsencrypt/live/94.232.42.94/fullchain.pem ]]; then
    if ss -H -ltn 'sport = :80' | grep -q .; then
        if [[ -z "$("${compose[@]}" ps -q acme)" ]]; then echo 'Port 80 belongs to another service'; exit 1; fi
    fi
    "${compose[@]}" up -d acme
    docker run --rm -v "$PWD/shared/letsencrypt:/etc/letsencrypt" -v "$PWD/shared/acme:/var/www/acme" certbot/certbot:v5.8.0 certonly --non-interactive --agree-tos --register-unsafely-without-email --preferred-profile shortlived --webroot --webroot-path /var/www/acme --ip-address 94.232.42.94
fi
"${compose[@]}" up --build -d
for attempt in $(seq 1 90); do
    if curl --fail --silent https://94.232.42.94:6752/api/v1/health/ready; then printf '\nHTTPS and PostgreSQL ready\n'; exit 0; fi
    sleep 2
done
echo 'Readiness failed; inspect project logs'; exit 1
