# RUNBOOK — переезд Боба на VPS (BOB-094)

> Первичная установка руками owner'а — **один раз**. Дальше выкатки автоматические
> (по тегу `v*`, срез 4 / workflow `deploy-bob.yml`). Здесь — только cutover ноут → VPS.

Цель: Ubuntu/Debian (apt), systemd. Боб живёт под **отдельным** системным пользователем
`bob` в `/opt/bob` (структурная граница BOB-093 — процесс НЕ под owner'ом). VPS держит
только исходящие соединения (Telegram long-poll + Qwen MaaS).

🔴 Секреты через агента/скрипты **не проходят** — их кладёт owner напрямую. `bootstrap.sh`
и юниты `.env` не касаются.

---

## 0. Предусловия

- SSH-доступ на VPS с sudo.
- Ubuntu/Debian с systemd.
- На ноуте — рабочий Боб с актуальной `data/bob.db`.
- Значения секретов на руках: `BOB_LLM__TIER1_API_KEY`, `BOB_LLM__TIER0_API_KEY`,
  `BOB_TELEGRAM__TOKEN`, `GUPPI_TELEGRAM__TOKEN` (и для CD — `BOB_VPS_HOST`,
  `BOB_VPS_USER`, `BOB_VPS_SSH_KEY`, заводятся в GitHub Secrets, срез 4).

---

## 1. Bootstrap на VPS

```bash
# на VPS, от root
git clone https://github.com/zoologov/bob.git /tmp/bob-src
sudo bash /tmp/bob-src/deploy/bootstrap.sh
```

Что делает (идемпотентно — повторный прогон безопасен): создаёт пользователя `bob`
(дом `/opt/bob`), ставит apt-пакеты (python3.12, git, curl, sqlite3), клонирует
репозиторий в `/opt/bob`, ставит `uv` и `bd`, `uv sync`, создаёт `data/ logs/ backups/`,
устанавливает systemd-юниты (`bob.service`, `bob-backup.{service,timer}`),
`daemon-reload`, включает суточный таймер бэкапа.

🔴 Боба **не запускает** и `.env` **не создаёт** — это шаги 2–5 ниже.

---

## 2. Секреты: `.env` на VPS

Owner заводит GitHub Secrets (для будущего автодеплоя, срез 4) и **отдельно** кладёт
`.env` прямо на VPS для первого запуска:

```bash
# на VPS, от root
sudo -u bob tee /opt/bob/.env >/dev/null <<'EOF'
BOB_LLM__TIER1_API_KEY=...
BOB_LLM__TIER0_API_KEY=...
BOB_TELEGRAM__TOKEN=...
GUPPI_TELEGRAM__TOKEN=...
EOF
sudo chmod 600 /opt/bob/.env
sudo chown bob:bob /opt/bob/.env
```

🔴 Значения — только руками owner'а. Не эхать в общий лог, не коммитить.

Конфиг: `/opt/bob/config/bob.yaml` (на VPS — без локального дублёра Ollama, см. срез 5
`config/bob.vps.yaml`; скопировать его в `config/bob.yaml` на VPS).

---

## 3. Перенос свежей `data/bob.db` (cutover)

🔴 Сначала **остановить Боба на ноуте** — иначе БД разъедется (пишут обе машины).

```bash
# на НОУТЕ
./bob stop

# перенос свежей БД (owner, напрямую). Останавливать Боба на VPS не нужно —
# он ещё не запущен.
scp data/bob.db  <vps-user>@<vps-host>:/tmp/bob.db
```

```bash
# на VPS
sudo install -o bob -g bob -m 600 /tmp/bob.db /opt/bob/data/bob.db
sudo rm -f /tmp/bob.db
```

---

## 4. Запуск на VPS

```bash
# на VPS
sudo systemctl enable --now bob
sudo systemctl status bob --no-pager
```

`enable --now` = автозапуск при перезагрузке + старт сейчас.

---

## 5. Проверка ответа (smoke)

- `sudo journalctl -u bob -f` — видно «Bob GUPPI starting» и «AgentRuntime started»
  (тот же маркер, что ловит лаунчер `./bob`).
- Написать Бобу в Telegram → должен ответить.
- 🔴 Проверить, что claude code на VPS работает (owner проверял ранее — работает),
  если планируется dev-режим.

Если ответа нет: `sudo journalctl -u bob -n 50 --no-pager` и рабочий лог
`/opt/bob/logs/`.

---

## 6. Бэкапы

Суточный таймер уже включён bootstrap'ом:

```bash
sudo systemctl list-timers bob-backup.timer --no-pager
sudo systemctl start bob-backup.service   # ручной внеплановый бэкап
ls -1t /opt/bob/backups/                  # копии bob-<timestamp>.db, ротация по числу
```

Восстановление (на КОПИИ, не поверх живой БД):

```bash
sqlite3 /opt/bob/data/bob.db.restored ".restore /opt/bob/backups/bob-<ts>.db"
# проверить, затем при ОСТАНОВЛЕННОМ Бобе заменить data/bob.db
```

---

## 7. Откат (VPS → ноут)

Если на VPS что-то не так — возвращаемся на ноут:

```bash
# на VPS
sudo systemctl stop bob
# при необходимости перенести свежую data/bob.db обратно на ноут (scp), owner напрямую
```

```bash
# на НОУТЕ
./bob start
```

---

## 8. Что дальше (автоматизация)

После успешного cutover рутинных ручных шагов больше нет: выкатка идёт **по тегу `v*`**
через `.github/workflows/deploy-bob.yml` (срез 4) — SSH на VPS, `git checkout <tag>`,
`uv sync`, материализация `.env` из GitHub Secrets, быстрый гейт, `systemctl restart bob`.
Боб при рестарте объявляет обновление голосом (срез .1).

🔴 «Workflow есть» ≠ «деплой поехал»: критерий приёмки — **реальная** выкатка на VPS,
а не наличие yml (урок BOB-088).
