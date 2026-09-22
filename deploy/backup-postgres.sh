#!/bin/sh
set -eu

cd /opt/evig
mkdir -p backups

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
temporary="backups/evig_messages-${timestamp}.sql.gz.tmp"
destination="backups/evig_messages-${timestamp}.sql.gz"

docker compose --env-file .env.production -f compose.production.yaml \
  exec -T postgres pg_dump -U evig -d evig_messages | gzip -9 > "$temporary"
mv "$temporary" "$destination"
find backups -type f -name 'evig_messages-*.sql.gz' -mtime +7 -delete
