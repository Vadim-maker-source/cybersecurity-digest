#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "$0")/../.."
mkdir -p work/backups
docker compose -p cyber-digest -f compose.yml -f compose.server.yml exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "work/backups/daily-$(date -u +%Y%m%dT%H%M%SZ).sql"
