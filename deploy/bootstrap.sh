#!/usr/bin/env bash
# bootstrap.sh — идемпотентная первичная установка Боба на VPS (BOB-094, срез 3).
#
# Цель: Ubuntu/Debian (apt), systemd. Отдельный системный пользователь bob,
# дом /opt/bob. Запускать от root (sudo). Каждый шаг проверяет, не сделан ли
# уже, поэтому повторный прогон НЕ ломается и не откатывает состояние.
#
# 🔴 Секретов НЕ касается: .env кладёт owner отдельно (см. RUNBOOK.md).
# 🔴 Боба не запускает: enable --now делает owner после переноса data/bob.db.
#
# Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
# SPDX-License-Identifier: BUSL-1.1
set -euo pipefail

# --- Параметры (можно переопределить окружением) ------------------------------
BOB_USER="${BOB_USER:-bob}"
BOB_HOME="${BOB_HOME:-/opt/bob}"
BOB_REPO="${BOB_REPO:-https://github.com/zoologov/bob.git}"
APT_PACKAGES="${APT_PACKAGES:-python3.12 python3.12-venv git curl sqlite3 ca-certificates}"

# Каталог самого этого скрипта (deploy/ внутри клона) — источник юнит-файлов.
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '\033[1;32m[bootstrap]\033[0m %s\n' "$*"; }
skip() { printf '\033[1;34m[bootstrap]\033[0m (уже сделано) %s\n' "$*"; }

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Запусти от root: sudo bash deploy/bootstrap.sh" >&2
    exit 1
  fi
}

# 1. Системный пользователь bob (idempotent: getent проверяет наличие).
ensure_user() {
  if getent passwd "$BOB_USER" >/dev/null; then
    skip "пользователь $BOB_USER существует"
  else
    log "создаю системного пользователя $BOB_USER (дом $BOB_HOME)"
    useradd -r -m -d "$BOB_HOME" -s /usr/sbin/nologin "$BOB_USER"
  fi
}

# 2. apt-пакеты (idempotent: apt install не переустанавливает свежие).
ensure_packages() {
  log "обновляю индекс apt и ставлю пакеты: $APT_PACKAGES"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  # shellcheck disable=SC2086
  apt-get install -y $APT_PACKAGES
}

# 3. Клон репозитория в /opt/bob (idempotent: если .git есть — только fetch).
ensure_repo() {
  if [ -d "$BOB_HOME/.git" ]; then
    skip "репозиторий уже склонирован в $BOB_HOME"
  else
    log "клонирую $BOB_REPO -> $BOB_HOME"
    # -m у useradd уже создал $BOB_HOME; git clone требует пустой/несуществующий,
    # поэтому клонируем во временный и переносим содержимое.
    local tmp="${BOB_HOME}.clone.$$"
    git clone "$BOB_REPO" "$tmp"
    # переносим включая .git, не трогая уже созданные data/logs, если есть
    cp -rfT "$tmp" "$BOB_HOME"
    rm -rf "$tmp"
  fi
  chown -R "$BOB_USER:$BOB_USER" "$BOB_HOME"
}

# 4. uv (менеджер venv/зависимостей) — СИСТЕМНО в /usr/local/bin (idempotent).
# 🔴 Ровно тот путь, что зовёт CD-workflow (deploy-bob.yml) и что стоит на живом VPS.
# Раньше ставился в $BOB_HOME/.local/bin — рассинхрон с workflow ронял бы деплой (ревью Major-1).
ensure_uv() {
  if [ -x /usr/local/bin/uv ]; then
    skip "uv уже установлен (/usr/local/bin/uv)"
  else
    log "устанавливаю uv системно в /usr/local/bin"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
  fi
}

# 5. bd (beads CLI) — ставим пользователю bob (idempotent).
ensure_bd() {
  if sudo -u "$BOB_USER" bash -lc 'command -v bd >/dev/null 2>&1'; then
    skip "bd уже установлен у $BOB_USER"
  else
    log "устанавливаю bd (beads) для $BOB_USER"
    sudo -u "$BOB_USER" bash -c 'curl -LsSf https://raw.githubusercontent.com/steveyegge/beads/main/install.sh | sh' \
      || echo "⚠️ установка bd не удалась — bd опционален на VPS, продолжаю"
  fi
}

# 6. uv sync — материализуем .venv в /opt/bob (idempotent: uv sync — no-op при свежем lock).
ensure_venv() {
  log "uv sync в $BOB_HOME (от имени $BOB_USER)"
  sudo -u "$BOB_USER" bash -lc "cd '$BOB_HOME' && /usr/local/bin/uv sync"
}

# 7. Рабочие каталоги data/ logs/ backups/ (idempotent: mkdir -p).
ensure_dirs() {
  log "создаю data/ logs/ backups/ в $BOB_HOME"
  sudo -u "$BOB_USER" mkdir -p "$BOB_HOME/data" "$BOB_HOME/logs" "$BOB_HOME/backups"
}

# 8. systemd-юниты: копируем из deploy/, daemon-reload (idempotent: cp -f + reload).
ensure_units() {
  log "устанавливаю systemd-юниты из $DEPLOY_DIR"
  install -m 0644 "$DEPLOY_DIR/bob.service"        /etc/systemd/system/bob.service
  install -m 0644 "$DEPLOY_DIR/bob-backup.service" /etc/systemd/system/bob-backup.service
  install -m 0644 "$DEPLOY_DIR/bob-backup.timer"   /etc/systemd/system/bob-backup.timer
  systemctl daemon-reload
  # Таймер бэкапа можно включить сразу — он не запускает самого Боба.
  systemctl enable --now bob-backup.timer || true
}

# 5b. beadloom — ВНЕШНИЙ бинарь, без которого немеет вся read-only интроспекция
# (BOB-091: схема архитектуры, влияние, состояние проекта). BOB-110: его на VPS не было,
# и на «покажи архитектуру» Боб пять раз подряд получил ENOENT.
#
# 🔴 Три условия, и каждое проверяется ОТ ЛИЦА bob, а не root — под root все три давали бы
# ложное «готово»:
#   * UV_TOOL_DIR общесистемный: установка по умолчанию кладёт симлинк в /root/.local/share,
#     куда пользователю bob не пройти — `which beadloom` у него молча пуст;
#   * `tree-sitter<0.26`: грамматики собраны под ABI 0.25, со свежим ядром beadloom падает
#     НАТИВНО и без вывода (BOB-108) — то есть ENOENT сменился бы на сегфолт;
#   * индекс `.beadloom/beadloom.db` в .gitignore и с кодом НЕ приезжает — без reindex
#     `beadloom graph` отвечает «database not found».
ensure_beadloom() {
  if [ -x /usr/local/bin/beadloom ] && sudo -u "$BOB_USER" test -r /usr/local/bin/beadloom; then
    skip "beadloom уже доступен пользователю $BOB_USER"
  else
    log "ставлю beadloom системно (пин tree-sitter<0.26)"
    UV_TOOL_DIR=/usr/local/share/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin \
      /usr/local/bin/uv tool install --force beadloom --with 'tree-sitter<0.26'
    chmod -R a+rX /usr/local/share/uv-tools
  fi
  log "собираю индекс beadloom от имени $BOB_USER"
  sudo -u "$BOB_USER" bash -lc "cd '$BOB_HOME' && beadloom reindex" || \
    log "ВНИМАНИЕ: reindex не прошёл — интроспекция ответит «database not found»"
}

# 5c. Рендерер диаграмм: mermaid-cli + браузер для puppeteer.
# BOB-110: в проде mmdc_bin указывал на путь С МАКБУКА владельца
# (/Users/…/.nvm/…/mmdc) — конфиг ноутбука уехал на сервер, потому что config/bob.yaml
# не трекается git. Боб схему ВИДЕЛ, а картинку сделать не мог.
#
# 🔴 Браузер берём .deb от Google, а НЕ snap: snap-сборка отказывается стартовать из
# сервисного контекста («is not a snap cgroup for tag snap.chromium.chromium») — проверено
# на этом же хосте. Node ставим 22.x: puppeteer-CLI не работает на node 18 из Ubuntu
# («Invalid regular expression flags»). Скачивание chrome-headless-shell самим puppeteer
# на этом VPS не проходит («all providers failed»), поэтому системный Chrome — не роскошь,
# а единственный работающий путь.
ensure_renderer() {
  if ! command -v node >/dev/null 2>&1 || [ "$(node --version | cut -c2-3)" -lt 20 ] 2>/dev/null; then
    log "ставлю Node.js 22.x (для mermaid-cli и puppeteer)"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
  else
    skip "node $(node --version) уже подходит"
  fi
  if command -v mmdc >/dev/null 2>&1; then
    skip "mermaid-cli (mmdc) уже установлен"
  else
    log "ставлю mermaid-cli"
    npm install -g @mermaid-js/mermaid-cli
  fi
  if [ -x /usr/bin/google-chrome ]; then
    skip "google-chrome уже установлен"
  else
    log "ставлю google-chrome (.deb, не snap)"
    curl -sSL -o /tmp/chrome.deb \
      https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/chrome.deb
    rm -f /tmp/chrome.deb
  fi
  log "🔴 owner: в config/bob.yaml задать mmdc_bin: /usr/local/bin/mmdc (НЕ путь ноутбука),"
  log "   и в .env — PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome (см. RUNBOOK.md)"
}

main() {
  require_root
  ensure_user
  ensure_packages
  ensure_repo
  ensure_uv
  ensure_bd
  ensure_beadloom
  ensure_renderer
  ensure_venv
  ensure_dirs
  ensure_units
  log "готово. Дальше — по RUNBOOK.md: owner кладёт .env (600) и data/bob.db,"
  log "затем: systemctl enable --now bob"
}

main "$@"
