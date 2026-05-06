#!/usr/bin/env bash
# Cron-friendly SQLite backup. Schedule via /etc/cron.d/kairo-backup:
#   0 3 * * * kairo /opt/kairo-web/app/scripts/backup.sh

set -euo pipefail

DB_PATH="${KAIRO_DB_PATH:-/var/lib/kairo-web/kairo.db}"
BACKUP_DIR="${KAIRO_BACKUP_DIR:-/opt/kairo-web/backups}"
RETAIN_DAYS="${KAIRO_BACKUP_RETAIN_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

STAMP=$(date +%F_%H%M)
OUT="$BACKUP_DIR/kairo-$STAMP.db"

# Use SQLite's online backup API for a consistent snapshot.
sqlite3 "$DB_PATH" ".backup '$OUT'"
gzip -f "$OUT"

# Rotate
find "$BACKUP_DIR" -type f -name "kairo-*.db.gz" -mtime "+$RETAIN_DAYS" -delete

echo "backup written: ${OUT}.gz"
