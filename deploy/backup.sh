#!/usr/bin/env bash
# backup.sh — консистентный бэкап SQLite-БД Боба (BOB-094, срез 3).
#
# 🔴 НЕ cp на живой БД: при активной записи (WAL) простой cp даёт битую копию.
# Используем `sqlite3 ".backup"` — она берёт консистентный снимок даже под
# нагрузкой. Ротация по числу копий. Запускается bob-backup.timer раз в сутки
# от пользователя bob.
#
# Восстановление (руками owner'а, на КОПИИ — не поверх живой):
#   sqlite3 /opt/bob/data/bob.db.restored ".restore /opt/bob/backups/bob-<ts>.db"
#   # проверить целостность, затем при остановленном Бобе заменить data/bob.db.
#
# Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
# SPDX-License-Identifier: BUSL-1.1
set -euo pipefail

BOB_HOME="${BOB_HOME:-/opt/bob}"
DB="${BOB_DB:-$BOB_HOME/data/bob.db}"
BACKUP_DIR="${BOB_BACKUP_DIR:-$BOB_HOME/backups}"
KEEP="${BOB_BACKUP_KEEP:-14}"   # сколько последних копий держать

log() { printf '[backup] %s\n' "$*"; }

if [ ! -f "$DB" ]; then
  echo "❌ Нет БД: $DB — бэкапить нечего." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

ts="$(date +%Y%m%d-%H%M%S)"
dest="$BACKUP_DIR/bob-$ts.db"

log "консистентный снимок $DB -> $dest"
# .backup работает и на живой БД (WAL), в отличие от cp.
sqlite3 "$DB" ".backup '$dest'"

# Быстрая проверка, что копия открывается и целостна.
if ! sqlite3 "$dest" "PRAGMA integrity_check;" | grep -q '^ok$'; then
  echo "❌ integrity_check не прошёл на $dest — копия подозрительна." >&2
  exit 1
fi
log "integrity_check: ok"

# Ротация: оставляем KEEP самых свежих bob-*.db, остальное удаляем.
# ls -1t — по времени (свежие сверху), tail -n +N — всё после первых KEEP.
# Без mapfile (нет в bash 3.2) — построчный цикл, устойчивый к отсутствию файлов.
removed=0
while IFS= read -r old; do
  [ -n "$old" ] || continue
  rm -f "$old"
  removed=$((removed + 1))
done < <(ls -1t "$BACKUP_DIR"/bob-*.db 2>/dev/null | tail -n +"$((KEEP + 1))")
if [ "$removed" -gt 0 ]; then
  log "ротация: удалено $removed старых копий (держим $KEEP)"
fi

log "готово: $dest"
