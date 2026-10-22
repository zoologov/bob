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
# Каталог юнитов systemd; переопределяет только тест (tests/deploy/test_bootstrap.py).
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

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

# 6a. Конфиг прода (BOB-116): config/bob.yaml = трекаемый config/bob.vps.yaml, байт в байт,
# ровно как делает выкатка (deploy-bob.yml, шаг 3/4). Идентификаторов и секретов в нём нет —
# они в .env (RUNBOOK §9); проверку сборки с настоящим .env owner запускает перед стартом
# (RUNBOOK §4), потому что на этом шаге .env может ещё не быть.
ensure_config() {
  local tracked="$BOB_HOME/config/bob.vps.yaml" live="$BOB_HOME/config/bob.yaml"
  log "ставлю конфиг прода: config/bob.vps.yaml -> config/bob.yaml"
  install -o "$BOB_USER" -g "$BOB_USER" -m 0640 "$tracked" "$live"
  sha256sum "$tracked" "$live"
  [ "$(sha256sum < "$tracked")" = "$(sha256sum < "$live")" ] || {
    echo "❌ sha256 config/bob.yaml не равен config/bob.vps.yaml" >&2
    exit 1
  }
}

# 6b. keep-alive Ollama (BOB-126): drop-in deploy/ollama-keep-alive.conf — модели не
# выгружаются после простоя и их не больше двух на этой RAM. Тот же шаг, что в выкатке
# (deploy-bob.yml), и до модели дублёра: рестарт Ollama после pull выгрузил бы её.
# Ставится только при отличии (idempotent), иначе Ollama не трогаем. Ollama ещё нет —
# drop-in ждёт в ollama.service.d и вступит в силу с её собственным юнитом.
# systemctl возвращается, когда процесс запущен, а не когда он слушает порт: модель дублёра,
# которую тянет следующий шаг, ушла бы в закрытый порт.
OLLAMA_READY_TRIES=30  # секунд ждать Ollama после её рестарта
wait_for_ollama() {
  local tries=0
  until ollama ps >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -ge "$OLLAMA_READY_TRIES" ]; then
      echo "❌ Ollama не ответила за ${OLLAMA_READY_TRIES} с после рестарта" >&2
      exit 1
    fi
    sleep 1
  done
}

ensure_ollama_keep_alive() {
  local src="$DEPLOY_DIR/ollama-keep-alive.conf"
  local dst="$SYSTEMD_DIR/ollama.service.d/keep-alive.conf"
  if cmp -s "$src" "$dst"; then
    skip "keep-alive: без изменений"
    return
  fi
  log "ставлю keep-alive Ollama: $dst"
  install -D -m 0644 "$src" "$dst"
  # Отказ после install: drop-in убирается, иначе повторный bootstrap увидит «без изменений»,
  # а Ollama так и будет работать без него.
  if ! systemctl daemon-reload; then
    rm -f "$dst"
    echo "❌ daemon-reload после keep-alive не прошёл, drop-in убран" >&2
    exit 1
  fi
  if ! command -v ollama >/dev/null 2>&1; then
    log "ollama не установлен — drop-in вступит в силу при его установке"
    return
  fi
  if ! systemctl restart ollama; then
    rm -f "$dst"
    echo "❌ Ollama не перезапустилась с keep-alive, drop-in убран" >&2
    exit 1
  fi
  wait_for_ollama
}

# 6c. Модель дублёра Tier-0 (BOB-116) — по той же конфигурации и тем же решением, что
# выкатка (deploy-bob.yml, шаг 4/4): deploy/check_config.py спрашивает действующую
# конфигурацию (config/bob.vps.yaml + .env, если он уже лежит) через understudy_endpoint
# фабрики провайдеров. Дублёр выключен -> модель не тянем. Включён -> нужен Ollama и модель
# в `ollama list`; иначе bootstrap падает, а не оставляет Боба с дублёром без модели.
understudy_model_present() {
  ollama list | awk -v m="$1" \
    'NR > 1 && ($1 == m || $1 == m ":latest") { found = 1 } END { exit !found }'
}

ensure_understudy_model() {
  local env_args=()
  if [ -f "$BOB_HOME/.env" ]; then env_args=(--env-file "$BOB_HOME/.env"); fi
  local model
  model="$(sudo -u "$BOB_USER" "$BOB_HOME/.venv/bin/python" "$BOB_HOME/deploy/check_config.py" \
    understudy-model --config "$BOB_HOME/config/bob.vps.yaml" ${env_args[@]+"${env_args[@]}"})"
  if [ -z "$model" ]; then
    skip "дублёр выключен в конфиге — модель не тянем"
    return
  fi
  if ! command -v ollama >/dev/null 2>&1; then
    echo "❌ дублёр включён в config/bob.vps.yaml, а ollama не установлен:" >&2
    echo "   curl -fsSL https://ollama.com/install.sh | sh — и повтори bootstrap" >&2
    exit 1
  fi
  if understudy_model_present "$model"; then
    skip "модель дублёра $model уже в ollama list"
    return
  fi
  log "тяну модель дублёра $model"
  ollama pull "$model"
  understudy_model_present "$model" || {
    echo "❌ модели $model нет в ollama list после pull" >&2
    exit 1
  }
}

# 7. Рабочие каталоги data/ logs/ backups/ (idempotent: mkdir -p).
ensure_dirs() {
  log "создаю data/ logs/ backups/ в $BOB_HOME"
  sudo -u "$BOB_USER" mkdir -p "$BOB_HOME/data" "$BOB_HOME/logs" "$BOB_HOME/backups"
}

# 8. systemd-юниты из deploy/: ставится только изменившийся, daemon-reload — только если
# что-то поставлено (idempotent; тот же приём, что у юнита bob в выкатке, BOB-126).
# Отказ daemon-reload возвращает каждый поставленный юнит к прежнему виду (или убирает новый):
# на диске остаётся то, что systemd держит загруженным, и повтор снова увидит отличие.
ensure_units() {
  local unit changed=()
  for unit in bob.service bob-backup.service bob-backup.timer; do
    if cmp -s "$DEPLOY_DIR/$unit" "$SYSTEMD_DIR/$unit"; then
      skip "юнит $unit без изменений"
    else
      log "ставлю юнит $unit из $DEPLOY_DIR"
      rm -f "$SYSTEMD_DIR/$unit.before-bootstrap"
      if [ -f "$SYSTEMD_DIR/$unit" ]; then
        cp -pf "$SYSTEMD_DIR/$unit" "$SYSTEMD_DIR/$unit.before-bootstrap"
      fi
      install -D -m 0644 "$DEPLOY_DIR/$unit" "$SYSTEMD_DIR/$unit"
      changed+=("$unit")
    fi
  done
  if [ "${#changed[@]}" -gt 0 ] && ! systemctl daemon-reload; then
    for unit in "${changed[@]}"; do
      if [ -f "$SYSTEMD_DIR/$unit.before-bootstrap" ]; then
        mv -f "$SYSTEMD_DIR/$unit.before-bootstrap" "$SYSTEMD_DIR/$unit"
      else
        rm -f "$SYSTEMD_DIR/$unit"
      fi
    done
    echo "❌ daemon-reload после новых юнитов не прошёл, прежние юниты возвращены" >&2
    exit 1
  fi
  for unit in ${changed[@]+"${changed[@]}"}; do
    rm -f "$SYSTEMD_DIR/$unit.before-bootstrap"
  done
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
#   * версия пинится ТОЧНО, той же сборкой, что ставит выкатка (deploy-bob.yml) и CI:
#     метаданные beadloom 9.0.0 сами требуют tree-sitter>=0.25,<0.26 (BOB-108 — нативный
#     сегфолт без вывода на ядре 0.26; прежний ручной пин `tree-sitter<0.26` снят в BOB-112);
#   * индекс `.beadloom/beadloom.db` в .gitignore и с кодом НЕ приезжает — без reindex
#     `beadloom graph` отвечает «database not found».
ensure_beadloom() {
  if [ -x /usr/local/bin/beadloom ] && sudo -u "$BOB_USER" test -r /usr/local/bin/beadloom; then
    skip "beadloom уже доступен пользователю $BOB_USER"
  else
    log "ставлю beadloom==9.0.0 системно (та же сборка, что в deploy-bob.yml)"
    UV_TOOL_DIR=/usr/local/share/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin \
      /usr/local/bin/uv tool install --force beadloom==9.0.0
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
  # config/bob.yaml на сервере с BOB-116 перезаписывает выкатка из config/bob.vps.yaml:
  # mmdc_bin по умолчанию "mmdc" и находится по PATH сервиса; путь, если он нужен, — коммитом
  # в config/bob.vps.yaml, а не правкой на сервере.
  log "🔴 owner: в .env — PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome (см. RUNBOOK.md);"
  log "   mmdc_bin, если mmdc не на PATH сервиса, — коммитом в config/bob.vps.yaml"
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
  ensure_config
  ensure_ollama_keep_alive
  ensure_understudy_model
  ensure_dirs
  ensure_units
  log "готово. Дальше — по RUNBOOK.md: owner кладёт .env (600, переменные — §2 и §9)"
  log "и data/bob.db, проверяет конфиг (§4), затем: systemctl enable --now bob"
}

# Источник без запуска (`source deploy/bootstrap.sh`) — только для тестов функций шагов
# (tests/deploy/test_bootstrap.py); `bash deploy/bootstrap.sh` идёт в main как прежде.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
