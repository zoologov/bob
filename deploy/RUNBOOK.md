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
- Идентификаторы на руках (с BOB-116 они тоже живут только в `.env`): id группы, id
  владельца, список разрешённых чатов, топик Боба — полный список в §9.

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
`daemon-reload`, включает суточный таймер бэкапа. С BOB-116 ещё ставит конфиг прода
(`config/bob.vps.yaml` → `config/bob.yaml`, сверка sha256) и, если конфиг включает дублёра
Tier-0, тянет его модель в Ollama и проверяет её в `ollama list`. Дублёр включён, а Ollama
нет — bootstrap падает с подсказкой, а не оставляет Боба с дублёром без модели.

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
BOB_TELEGRAM__CHAT_ID=...
BOB_TELEGRAM__OWNER_ID=...
BOB_TELEGRAM__ALLOWED_CHAT_IDS=...
BOB_TELEGRAM__BOB__TOPIC_ID=...
EOF
sudo chmod 600 /opt/bob/.env
sudo chown bob:bob /opt/bob/.env
```

🔴 Значения — только руками owner'а. Не эхать в общий лог, не коммитить.

Конфиг: `/opt/bob/config/bob.yaml` — копия трекаемого `config/bob.vps.yaml` (BOB-116). Её
ставит bootstrap и каждая выкатка. Правка конфигурации прода — коммит в `config/bob.vps.yaml`,
а не правка на сервере: следующая выкатка перезапишет файл. Какие переменные обязательны и
откуда берутся значения — §9.

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

Сначала — проверка, что конфигурация собирается с этим `.env` (печатает только имена и
`config OK`, ни одного значения):

```bash
# на VPS
sudo -u bob /opt/bob/.venv/bin/python /opt/bob/deploy/check_config.py \
  require-env --env-file /opt/bob/.env
sudo -u bob /opt/bob/.venv/bin/python /opt/bob/deploy/check_config.py \
  validate --config /opt/bob/config/bob.yaml --env-file /opt/bob/.env
```

Обе команды обязаны закончиться кодом 0. Потом:

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
через `.github/workflows/deploy-bob.yml` (срез 4) — гейт `ruff`/`mypy`, затем по **SSH-ключу**
(`VPS_SSH_KEY` + `VPS_KNOWN_HOSTS`, вход по паролю на VPS отключён): `git checkout <tag>` и
`uv sync` от `bob`, затем четыре проверки BOB-116 и только потом `systemctl restart bob`
от root:

1. в `.env` есть все обязательные переменные (иначе красный деплой со ссылкой на §9);
2. `config/bob.vps.yaml` собирается лоадером Боба с настоящим `.env` и полон;
3. `config/bob.vps.yaml` копируется в `config/bob.yaml`, sha256 обоих печатается в лог и
   сравнивается;
4. если действующая конфигурация включает дублёра Tier-0 — `ollama pull` его модели и проверка
   в `ollama list`; выключен — в логе «дублёр выключен в конфиге — модель не тянем».

Между шагами 3 и 4 выкатка ставит drop-in keep-alive для Ollama, а перед рестартом — юнит
`deploy/bob.service` (BOB-126, §11). Каждый файл ставится, только если отличается от
поставленного; без изменений в логе «keep-alive: без изменений» и «unit bob: без изменений», и
ни Ollama, ни systemd не трогаются.

Отказ любой проверки — красный деплой, Боб не перезапущен. Отказ на 1 или 2 оставляет
`config/bob.yaml` нетронутым. Поведение шага держит `tests/deploy/test_deploy_workflow.py`,
который исполняет скрипт выкатки с заглушками вместо сервера. 🔴 `.env` выкатка **не** пишет
никогда — он на VPS постоянно (gitignored, переживает checkout). Боб при рестарте объявляет
обновление голосом (срез 1).

🔴 «Workflow есть» ≠ «деплой поехал»: критерий приёмки — **реальная** выкатка на VPS,
а не наличие yml (урок BOB-088).

---

## 9. Миграция идентификаторов и секретов в .env (BOB-116)

Разовый шаг перед первой выкаткой релиза с BOB-116 (тег BOB-118). Выполняет владелец или
координатор с явного «да» владельца. До миграции выкатка **падает на шаге 1/4** с текстом
«мигрируй идентификаторы в .env — deploy/RUNBOOK.md §9» и Боба не трогает.

Причина. С BOB-116 `config/bob.yaml` на сервере — копия трекаемого `config/bob.vps.yaml`, а
репозиторий публичный: в файле нет ни идентификаторов, ни секретов. Они приходят из `.env`,
и лоадер приводит значение к типу дефолта (id — целое, список — числа через запятую).

### 9.1 Переменные и откуда взять значения

Значения берутся из старого рукописного `/opt/bob/config/bob.yaml`. Читать их — в своём
терминале на VPS, не в общем логе и не в чате агента:

```bash
sudo -u bob grep -nE 'chat_id|owner_id|topic_id|owner_name|token|api_key' \
  /opt/bob/config/bob.yaml
```

| Переменная `.env` | Ключ в старом `config/bob.yaml` | Формат в `.env` |
|---|---|---|
| `BOB_TELEGRAM__CHAT_ID` | `telegram.chat_id` | целое, для группы с минусом: `-100…` |
| `BOB_TELEGRAM__OWNER_ID` | `telegram.owner_id` | целое |
| `BOB_TELEGRAM__ALLOWED_CHAT_IDS` | `telegram.allowed_chat_ids` (список YAML) | числа через запятую, без скобок |
| `BOB_TELEGRAM__BOB__TOPIC_ID` | `telegram.bob.topic_id` | целое |
| `BOB_TELEGRAM__TOKEN` | уже в `.env` (§2); если лежит в `telegram.bob.token` — перенести | строка |
| `GUPPI_TELEGRAM__TOKEN` | уже в `.env` (§2); если лежит в `telegram.guppi.token` — перенести | строка |
| `BOB_LLM__TIER0_API_KEY` | уже в `.env` (§2); если лежит в `llm.tier0_api_key` — перенести | строка |
| `BOB_LLM__TIER1_API_KEY` | уже в `.env` (§2); если лежит в `llm.tier1_api_key` — перенести | строка |
| `BOB_TELEGRAM__OWNER_NAME` (необязательная) | `telegram.owner_name` | строка |
| `BOB_TELEGRAM__OWNER_ADDRESS` (необязательная, BOB-126) | нет — новый ключ `telegram.owner_address` | строка: как Боб обращается к владельцу в сигналах («Вова»); пусто — первое слово `owner_name` |
| `BOB_TELEGRAM__OWNER_DM_CHAT_ID` (необязательная) | `telegram.owner_dm_chat_id` | целое, по умолчанию = `owner_id` |

Первые восемь обязательны: их проверяет шаг 1/4 выкатки, их называет шапка
`config/bob.vps.yaml`. Пустое значение считается отсутствием. Значение, которое не
приводится к типу (`-100abc`, пустой элемент списка `-100,,-200`), останавливает старт
Боба ошибкой с именем переменной — шаг 2/4 ловит это до рестарта.

### 9.2 Порядок

Шаги идут подряд в одном сеансе: после шага 2 упавший сам по себе Боб поднимется уже новым
кодом.

1. **Резервные копии и текущий тег.**
   ```bash
   sudo -u bob git -C /opt/bob describe --tags          # записать: это тег отката
   sudo -u bob cp -a /opt/bob/config/bob.yaml /opt/bob/config/bob.yaml.pre-BOB-116
   sudo -u bob cp -a /opt/bob/.env /opt/bob/.env.pre-BOB-116   # -a сохраняет права 600
   ```
2. **Новый код на диск, без рестарта.** Работающий Боб продолжает работать на старом коде.
   ```bash
   sudo -u bob git -C /opt/bob fetch --tags --prune
   sudo -u bob git -C /opt/bob checkout <тег-BOB-118>
   sudo -u bob bash -lc 'cd /opt/bob && /usr/local/bin/uv sync'
   ```
3. **Сравнить старый конфиг с трекаемым.** Команда печатает только пути настроек, без
   значений:
   ```bash
   sudo -u bob /opt/bob/.venv/bin/python /opt/bob/deploy/check_config.py compare-keys \
     --old /opt/bob/config/bob.yaml.pre-BOB-116 --new /opt/bob/config/bob.vps.yaml
   ```
   - «идентификатор или секрет -> перенести в .env» — шаг 4;
   - «нет в config/bob.vps.yaml» или «значение отличается» — настройка, которую старый файл
     задавал иначе, чем трекаемый: флаг способности, путь к бинарю, порог. Каждую строку
     решает владелец: либо коммит в `config/bob.vps.yaml` и новый тег (вернуться к шагу 2),
     либо согласие на значение трекаемого файла. Без решения по каждой строке дальше не идти:
     выкатка заменит старый файл целиком, и молча пропавший флаг выключит способность.
4. **Дописать переменные в `.env`.** Редактором, не через `echo`, чтобы значения не легли в
   историю оболочки:
   ```bash
   sudo -u bob nano /opt/bob/.env
   ```
5. **Проверить руками** — те же проверки, что делает выкатка; печатают только имена и
   `config OK`:
   ```bash
   sudo -u bob /opt/bob/.venv/bin/python /opt/bob/deploy/check_config.py \
     require-env --env-file /opt/bob/.env
   sudo -u bob /opt/bob/.venv/bin/python /opt/bob/deploy/check_config.py \
     validate --config /opt/bob/config/bob.vps.yaml --env-file /opt/bob/.env
   ```
   Обе обязаны закончиться кодом 0.
6. **Выкатка.** `workflow_dispatch` у `deploy-bob.yml` с `ref=<тег-BOB-118>` (или push тега).
   В логе выкатки — `env OK`, `config OK`, две строки sha256 с одинаковым хешем, «дублёр
   выключен в конфиге — модель не тянем», `active`.
7. **Проверка.** `sudo journalctl -u bob -n 100 --no-pager` — «Bob GUPPI starting» и строка
   состояния дублёра при старте; Боб отвечает в группе и в личке; `/status` у GUPPI
   показывает состояние LLM-стека.

### 9.3 Откат

- **Выкатка красная на шаге 1/4 или 2/4.** `config/bob.yaml` не тронут, Боб не перезапущен,
  но код на диске уже новый. Исправить `.env` и повторить выкатку — или откатить всё, как
  ниже.
- **Выкатка красная на шаге 3/4 или 4/4.** Боб не перезапущен и работает на прежнем, но
  `config/bob.yaml` уже заменён трекаемым файлом, а код на диске новый: упавший сам по себе
  Боб поднимется в новом состоянии. Исправить причину (копия с другим sha256, модель дублёра
  не скачалась) и повторить выкатку — или откатить всё, как ниже.
- **Боб после рестарта не работает, или нужно вернуть старое состояние целиком.** Откатывать
  и конфиг, и `.env`, и код: старый код читает id из окружения строкой, и отрицательный id
  группы превращается в 0 (найдено в D8a), поэтому новый `.env` со старым кодом не работает.
  ```bash
  sudo systemctl stop bob
  sudo install -o bob -g bob -m 0640 /opt/bob/config/bob.yaml.pre-BOB-116 /opt/bob/config/bob.yaml
  sudo install -o bob -g bob -m 0600 /opt/bob/.env.pre-BOB-116 /opt/bob/.env
  sudo -u bob git -C /opt/bob checkout <тег-отката-из-шага-1>
  sudo -u bob bash -lc 'cd /opt/bob && /usr/local/bin/uv sync'
  sudo systemctl restart bob
  ```
  Откат держится до следующей выкатки: она снова поставит `config/bob.vps.yaml`. Поэтому
  после отката — исправление коммитом и новый тег, а не правка на сервере.

---

## 10. Живой смоук BOB-116: немота при отказе Tier-0 слышна владельцу

Выполняет владелец или координатор после выкатки тега BOB-118 (PRD BOB-116, Q6 RFC);
результат — в `ACTIVE.md` BOB-116. Значения ключей не печатаются: порча и возврат — одной и
той же приставкой, обратимой правкой.

Пороги — из `llm.health` в `config/bob.vps.yaml`: сигнал после 5 отказов подряд или 180 с
отказов подряд, что раньше; зонд лёгшего провайдера раз в 60, 120, затем 300 с.

### 10.1 Отказ 401/403: сигнал владельцу

1. Испортить ключ Tier-0 приставкой и убедиться, что правка легла:
   ```bash
   sudo -u bob sed -i 's/^BOB_LLM__TIER0_API_KEY=/BOB_LLM__TIER0_API_KEY=smoke-broken-/' /opt/bob/.env
   sudo -u bob grep -c '^BOB_LLM__TIER0_API_KEY=smoke-broken-' /opt/bob/.env   # ожидается 1
   sudo systemctl restart bob
   ```
2. Ожидание: в пределах порога после первого вызова Tier-0 (прогрев ~1 мин, затем сердцебиение
   раз в 30 с) — сообщение в личку от бота Боба «я не могу думать: …»; в журнале одна строка
   `LLM health …: healthy → degraded (auth, …)` без стека:
   ```bash
   sudo journalctl -u bob --since "-10 min" --no-pager | grep "LLM health"
   ```
   `/status` у GUPPI показывает провайдер лежащим и время начала отказа.
3. Вернуть ключ обратной правкой и перезапустить:
   ```bash
   sudo -u bob sed -i 's/^BOB_LLM__TIER0_API_KEY=smoke-broken-/BOB_LLM__TIER0_API_KEY=/' /opt/bob/.env
   sudo -u bob grep -c '^BOB_LLM__TIER0_API_KEY=smoke-broken-' /opt/bob/.env   # ожидается 0
   sudo systemctl restart bob
   ```
4. 🔴 Сообщения «вернулся» здесь **не будет**, и это не дефект смоука: `.env` systemd читает
   только при старте, а состояние здоровья живёт в памяти процесса
   (`application/router/health_monitor.py`), поэтому после рестарта монитор начинает со
   «здоров» и перехода «восстановился» не видит. Восстановление проверяет 10.2.

### 10.2 Восстановление без рестарта: «вернулся»

Процедура утверждена в RFC BOB-116 (Q6, 2026-10-21); каждое действие — с явного «да» владельца.
Шаг на время отрезает Бобу **оба** этажа облака (Tier-0 и Tier-1 идут на один хост), то есть
Боб на эти минуты молчит и в разговоре.

1. Отрезать процессу `bob` (и только ему) хост облака Qwen:
   ```bash
   HOST=token-plan.ap-southeast-1.maas.aliyuncs.com
   for ip in $(getent ahostsv4 "$HOST" | awk '{print $1}' | sort -u); do
     sudo iptables -I OUTPUT -m owner --uid-owner bob -d "$ip" -p tcp --dport 443 \
       -j REJECT --reject-with tcp-reset
   done
   ```
2. Ожидание: в пределах порога — сообщение в личку «я не могу думать: …»; в журнале
   `LLM health tier0-primary: healthy → degraded (connection, …)`. Класс — `connection`:
   отказ `tcp-reset` на установке соединения классификатор
   (`application/router/fallback_policy.py`) относит к обрыву канала. Классов всего семь:
   `auth`, `rate`, `server`, `timeout`, `connection`, `shape`, `contract`.
   Tier-1 идёт на тот же хост, но сообщения о нём в этом шаге не ждать: пока лежит Tier-0,
   ход до основной модели не доходит. Замер на собранной программе (loopback, 2026-10-21): оба
   этажа отвечают отказом, владелец дважды пишет Бобу в личку — 0 вызовов Tier-1, 7 вызовов
   облака, в личке одно сообщение «я не могу думать: …». На сами сообщения владельца Боб не
   ответит, вместо ответа в теме группы появится строка «⚠️ Проблемы со связью — Боб временно
   недоступен» (её шлёт бот Боба голосом GUPPI, и шлёт в тему, а не в личку — дефект
   вне BOB-116, беада bob-hod, Issues #71).
   Текст об отказе одного Tier-1 проверяется отдельно, тем же приёмом, что 10.1, но с ключом
   `BOB_LLM__TIER1_API_KEY`: после двух сообщений Бобу в личку в журнале
   `LLM health tier1: healthy → degraded (auth, …)`, а в личке сообщение со словами «Тебе и
   команде я сейчас ответить не могу — вместо меня GUPPI пишет, что я недоступен». Тот же
   замер с живым облаком и отказом одного Tier-1: 6 вызовов Tier-1 на два хода, ответа
   владельцу нет, в теме две строки GUPPI. Обещание «Гостям отвечаю облаком попроще, пока
   оно живо» держит сценарий S14 в `llm_health.feature`.
3. Снять правила той же спецификацией (`-D` вместо `-I`) и проверить, что их не осталось:
   ```bash
   for ip in $(getent ahostsv4 "$HOST" | awk '{print $1}' | sort -u); do
     sudo iptables -D OUTPUT -m owner --uid-owner bob -d "$ip" -p tcp --dport 443 \
       -j REJECT --reject-with tcp-reset
   done
   sudo iptables -S OUTPUT   # правил смоука (владелец bob, tcp-reset) не осталось
   ```
   Если `getent` теперь отдаёт другие адреса, оставшиеся правила снимаются по выводу
   `sudo iptables -S OUTPUT`.
4. Ожидание: при следующем зонде (не позже 300 с) — сообщение «я вернулся: … Молчал …» и
   строка `LLM health tier0-primary: degraded → healthy (connection, down since …)` в
   журнале. В автобиографии Боба — эпизод «я молчал … думать было нечем. Теперь снова
   могу.». Он пишется, потому что `memory.autobiography: true` в `config/bob.vps.yaml`
   (Q5 RFC BOB-116), и только после настоящей немоты. Так было, пока дублёр на VPS был
   выключен (D9): отказ облачного Tier-0 тогда — немота. Ожидание с дублёром — ниже.

**С дублёром (BOB-126).** Дублёр живёт на локальной Ollama, и отрезка облака не замечает:
отказ облачного Tier-0 — уже не немота. Шаги 1 и 3 те же, ожидание другое:

- шаг 2: в личку — «… Пока держусь на дублёре: он слабее, но думать есть чем. Только облако
  надо чинить, пока дублёр жив.»; в журнале `LLM health tier0-primary: healthy → degraded
  (connection, …)`; `/status` у GUPPI — «tier0 облако — деградирован с …» и «дублёр — ок»;
- служебные дорожки идут на дублёре: гейт дорожек закрывает Tier-0, только когда лежит облако
  и дублёр не держит (F2 RFC BOB-116), поэтому рефлексия и монолог продолжаются;
- шаг 4: при следующем зонде — «…облако снова отвечает. Не работало … (…), всё это время
  служебное держал дублёр.», и эпизода «я молчал» в автобиографии **нет**: монитор пишет его
  только после немоты (`health_monitor._SILENT_SITUATIONS`).

Tier-1 отрезан тем же правилом (один хост). Если за время отрезка до него дойдёт порог —
отдельный сигнал о Tier-1 (текст в шаге 2) и при его восстановлении свой эпизод — это второй
отрезанный этаж, а не дефект дублёра. Чтобы проверить только дублёра, не писать Бобу, пока
правила стоят.

---

## 11. Дублёр Tier-0 на VPS (BOB-126)

Включён 2026-10-22 решением владельца по замеру BOB-123 на этом VPS (4 vCPU без GPU):
`qwen3.5:4b` на локальной Ollama, рядом с эмбеддером `bge-m3`. Тёплая модель: классификатор
1,3 с, монолог 24 с, рефлексия 15 с; холодная — 16 с, 73 с и 169 с. Память: 3,1 ГБ + 1,2 ГБ,
модели живут рядом без вытеснения. Числа и правило — в комментарии `llm` в
`config/bob.vps.yaml`.

Дублёр берёт на себя только служебные ходы Tier-0 и только при транспортном отказе облака.
Реплики голосом Боба он не пишет: их держит Tier-1 (`config/bob.example.yaml`, раздел дублёра).

### 11.1 Как увидеть, что он работает

- **Выкатка:** «модель дублёра на месте: qwen3.5:4b» (шаг 4/4).
- **Старт Боба:** строка журнала `tier0 understudy: on, model qwen3.5:4b ready`; если модели
  нет или Ollama не отвечает — `tier0 understudy: on, NOT ready — <причина>`, сообщение
  владельцу «я стартовал без дублёра …», и дублёра нет до перезапуска.
  ```bash
  sudo journalctl -u bob --since "-10 min" --no-pager | grep "tier0 understudy"
  ```
- **`/status` у GUPPI:** строка «дублёр — ок»; «дублёр — выключен при старте: … (до
  перезапуска)» — он был включён, но не готов; «дублёр — нет» — выключен в конфигурации.
- **Ollama:** обе модели в памяти бессрочно.
  ```bash
  ollama ps        # qwen3.5:4b и bge-m3, в колонке UNTIL — Forever
  sudo journalctl -u ollama --since "-1 hour" --no-pager | grep -c "llama-server started"
  ```
  Число загрузок за час после выкатки — не больше двух (по одной на модель). Загрузки по
  кругу каждые ~5 минут — keep-alive не действует (BOB-121, Issues #68).

### 11.2 keep-alive Ollama

Drop-in `deploy/ollama-keep-alive.conf` ставится в
`/etc/systemd/system/ollama.service.d/keep-alive.conf` выкаткой и `bootstrap.sh`:

- `OLLAMA_KEEP_ALIVE=-1` — модели не выгружаются после простоя. По умолчанию Ollama выгружает
  модель через 5 минут, и каждая дверь после паузы платила холодную загрузку;
- `OLLAMA_MAX_LOADED_MODELS=2` — 🔴 **не больше двух моделей на этой RAM.** Третья модель
  рядом дала OOM-kill `llama-server` (замер 22.10). Сменить модель дублёра можно, добавить
  третью постоянную — нет: сначала замер памяти, потом решение владельца.

Файл ставится, только если отличается от поставленного, и тогда же `systemctl daemon-reload`
и `systemctl restart ollama` — до `ollama pull`, чтобы рестарт не выгрузил только что
загруженную модель. После рестарта выкатка ждёт ответа `ollama ps` до 30 с: `systemctl`
возвращается, когда процесс запущен, а не когда он слушает порт. Не ответила — красная
выкатка, Боб не перезапущен. Правка — коммит в `deploy/ollama-keep-alive.conf` и новый тег, не
правка на сервере. Проверить, что systemd его видит:
```bash
systemctl show ollama --property=Environment   # OLLAMA_KEEP_ALIVE=-1 OLLAMA_MAX_LOADED_MODELS=2
```

### 11.3 Как выключить

Одна строка в трекаемом конфиге — `tier0_fallback: ""` в разделе `llm` файла
`config/bob.vps.yaml`, коммит через PR и новый тег (или `workflow_dispatch`). Выкатка
напишет «дублёр выключен в конфиге — модель не тянем», при старте Боба — `tier0 understudy:
off`, в `/status` — «дублёр — нет». Модель с диска выкатка не удаляет: `ollama rm
qwen3.5:4b` — отдельно, если нужна память. keep-alive остаётся: он нужен и эмбеддеру.

Срочно и без релиза — `BOB_LLM__TIER0_FALLBACK=` (пустое значение) в `/opt/bob/.env` и
`sudo systemctl restart bob`: окружение стоит выше файла. Это расхождение с репозиторием —
после него тот же коммит в `config/bob.vps.yaml`, а строку из `.env` убрать.

### 11.4 Пояс и обращение

- `deploy/bob.service` запускает Боба после запуска Ollama (`After=` и `Wants=ollama.service`).
  Это порядок запуска процессов, а не готовность порта: у юнита Ollama тип simple. Старт Боба
  проверяет дублёра один раз, с тайм-аутом 5 с и без повтора. Если после перезагрузки VPS
  Ollama за это время порт не открыла, дублёр снят до следующего рестарта Боба, владелец
  получает «стартовал без дублёра», а `/status` — «дублёр — выключен при старте: … (до
  перезапуска)». Тогда — `sudo systemctl restart bob`.
- `deploy/bob.service` задаёт `Environment=TZ=Europe/Moscow`: время в сообщениях владельцу,
  в `/status` и в эпизоде «я молчал» — `+03:00` (`bob-ol3`). Выкатка ставит изменённый юнит
  сама (`install` + `daemon-reload` до рестарта).
- Обращение в сигналах владельцу — `BOB_TELEGRAM__OWNER_ADDRESS` в `.env` («Вова», §9.1);
  без него — первое слово `BOB_TELEGRAM__OWNER_NAME` («Владимир»). Полное имя остаётся для
  бэкфилла BOB-045.
