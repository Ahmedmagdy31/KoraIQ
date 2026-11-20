#!/usr/bin/env bash
# Nightly PostgreSQL backup, keeps 14 days locally, optional off-site copy with rclone.
# Install:  crontab -e   ->   15 3 * * * /home/deploy/koraiq/deploy/backup.sh >> /home/deploy/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p backups
docker compose -f docker-compose.prod.yml --env-file .env exec -T db \
  pg_dump -U koraiq -d koraiq --format=custom --no-owner > "backups/koraiq-$STAMP.dump"
find backups -name 'koraiq-*.dump' -mtime +14 -delete
# Off-site (a backup on the same disk is not a backup). Configure once with `rclone config`
# (e.g. Backblaze B2, Google Drive, or another provider) and set RCLONE_REMOTE=remote:bucket/path
if [[ -n "${RCLONE_REMOTE:-}" ]]; then
  rclone copy "backups/koraiq-$STAMP.dump" "$RCLONE_REMOTE"
fi
echo "backup ok: koraiq-$STAMP.dump"
