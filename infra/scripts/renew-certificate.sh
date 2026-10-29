#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
docker run --rm -v "$PWD/shared/letsencrypt:/etc/letsencrypt" -v "$PWD/shared/acme:/var/www/acme" certbot/certbot:v5.8.0 renew --webroot --webroot-path /var/www/acme --quiet --no-random-sleep-on-renew
docker compose -p cyber-digest -f compose.yml -f compose.server.yml exec -T nginx nginx -t
docker compose -p cyber-digest -f compose.yml -f compose.server.yml exec -T nginx nginx -s reload
