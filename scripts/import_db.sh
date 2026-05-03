#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_DIR="$PROJECT_DIR/dump"

if docker compose version >/dev/null 2>&1; then
	DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
	DC=(docker-compose)
else
	echo "Error: neither 'docker compose' nor 'docker-compose' is available."
	exit 1
fi

IN_FILE="${1:-}"

if [[ -z "$IN_FILE" ]]; then
	if [[ -d "$DUMP_DIR" ]]; then
		IN_FILE="$(ls -1t "$DUMP_DIR"/odoo_backup_*.dump 2>/dev/null | head -n 1 || true)"
	fi
	if [[ -z "$IN_FILE" ]]; then
		echo "No backup provided and no dump found in $DUMP_DIR"
		exit 1
	fi
fi

if [[ ! -f "$IN_FILE" ]]; then
	echo "File not found: $IN_FILE"
	exit 1
fi

FS_FILE="${IN_FILE%.dump}_filestore.tar.gz"

cd "$PROJECT_DIR"

echo "Stopping web container..."
"${DC[@]}" stop web

echo "Starting db container..."
"${DC[@]}" up -d db

echo "Waiting for db to be ready..."
until "${DC[@]}" exec -T db pg_isready -U odoo >/dev/null 2>&1; do
	sleep 1
done

echo "Recreating database..."
"${DC[@]}" exec -T db dropdb -U odoo --if-exists postgres
"${DC[@]}" exec -T db createdb -U odoo postgres

echo "Restoring database from: $IN_FILE"
"${DC[@]}" exec -T db pg_restore -U odoo -d postgres --no-owner < "$IN_FILE"

if [[ -f "$FS_FILE" ]]; then
	echo "Restoring filestore from: $FS_FILE"
	"${DC[@]}" run --rm -T -v odoo-web-data:/filestore alpine sh -c "rm -rf /filestore/* && tar xzf - -C /filestore" < "$FS_FILE"
else
	echo "Warning: No filestore backup found at $FS_FILE, skipping."
fi

echo "Starting full stack..."
"${DC[@]}" up -d

echo "Done. Database imported."
