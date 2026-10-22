<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF — BOB-126: дублёр Tier-0 на VPS (qwen3.5:4b) + keep_alive + человечное обращение + пояс

> **Type:** chore · **Status:** Approved
> **Created:** 2026-10-22 · **Беада:** `bob-9kk` (P1; блокирует закрытие `bob-wk5` BOB-121 и `bob-ol3`)

## Проблема

1. **Дублёра на VPS нет** — при мёртвом облаке Боб молчит (теперь слышно, но молчит). Замер BOB-123
   (2026-10-22): `qwen3.5:4b` (3,1 ГБ) живёт рядом с `bge-m3` (1,2 ГБ) без вытеснения; тёплые двери:
   классификатор 1,3 с, монолог 24 с, рефлексия 15 с; генерация 4,5 ток/с; русский связный, в характере.
   Решение владельца: «мне нравится дублёр» — включаем.
2. **Холодный старт модели 16 с и взаимное вытеснение** — без keep_alive каждая дверь после 5 минут
   простоя платит загрузку, а `bge-m3` перегружается каждые ~5 мин уже сейчас (BOB-121, Issues #68:
   130 k строк журнала в день). Третья модель рядом → OOM-kill `llama-server` (замер 2B).
3. **Обращение полным именем**: «Владимир Зоологов, я не могу думать…» — `owner_name` из `.env` подставляется
   целиком; по-человечески — «Вова» (или имя).
4. **Пояс в текстах +05:30** — пояс процесса на VPS (Asia/Kolkata), владелец в Москве (`bob-ol3`).

## Решение

1. `config/bob.vps.yaml`: `tier0_fallback: ollama`, `tier0_fallback_base_url: http://localhost:11434/v1`,
   `tier0_fallback_model: qwen3.5:4b` + комментарий с числами замера и правилом «не больше двух моделей
   на этой RAM». Выкатка сама тянет модель и проверяет `ollama list` (шаг 4/4), sign-on при старте пишет
   «tier0 understudy: on», `/status` показывает дублёра.
2. **keep_alive для обеих моделей:** systemd drop-in `/etc/systemd/system/ollama.service.d/keep-alive.conf`
   с `Environment=OLLAMA_KEEP_ALIVE=-1` (и `OLLAMA_MAX_LOADED_MODELS=2`) — файл трекается в `deploy/ollama-keep-alive.conf`,
   деплой и bootstrap ставят его (`install` + `systemctl daemon-reload` + `restart ollama` только при изменении
   файла — иначе рестарт Ollama на каждой выкатке). Замер после выкатки: `ollama ps` показывает обе модели с
   `UNTIL: Forever`; журнал Ollama за час — без `llama-server started` по кругу. Закрывает **BOB-121**.
3. **Обращение:** новый необязательный ключ `telegram.owner_address` («как обращаться», напр. `Вова`), из `.env`
   `BOB_TELEGRAM__OWNER_ADDRESS`; дефолт — первое слово `owner_name`. `health_messages` обращается по нему.
   Тест: «Владимир Зоологов» без адреса → «Владимир, …»; с адресом «Вова» → «Вова, …».
4. **Пояс:** `deploy/bob.service` получает `Environment=TZ=Europe/Moscow`; деплой переустанавливает unit при
   изменении (`install` + `daemon-reload` до `restart bob`). Тексты и журнал — `+03:00`. Закрывает `bob-ol3`.
5. RUNBOOK: раздел про дублёра (как выключить одной правкой конфига, что смотреть в `/status`), про keep_alive.
6. Живая проверка после выкатки (владелец/координатор): `/status` у GUPPI — «дублёр — ок»; журнал старта —
   «tier0 understudy: on»; `ollama ps` — две модели `Forever`; смоук §10.2 повторить — ожидание теперь:
   сообщение «держусь на дублёре: он слабее, но думать есть чем», рефлексия идёт (F2), эпизода «я молчал» нет.

## Axes

> **Derived by:** `beadloom impact src/bob/runtime/wiring/health.py` и
> `beadloom impact src/bob/application/router/health_messages.py`; строки по узлам, которые работа
> трогает, размечены вручную 2026-10-22 по ревью `bob-9kk` (Minor 6), строка `runtime-app` и
> `composition.py` добавлены вместе с фиксом ревью M1 (очередь восприятия реакций).
> **Seed:** `health_owner_address` (обращение к владельцу) и подписчик `BOB_MESSAGE_REACTION`
> в `composition.py`.

| Axis | Node | Sites | Owns unread | In scope | Why |
|---|---|---|---|---|---|
| callers | runtime | `src/bob/runtime/wiring/health.py`, `src/bob/runtime/wiring/tool_health.py`, `src/bob/runtime/composition.py` | none | yes | обращение `owner_address` в сигналах здоровья и при старте; очередь реакций вне цикла поллинга (ревью M1) |
| callers | router | `src/bob/application/router/health_messages.py`, `src/bob/application/router/health_monitor.py` | none | yes | поле и параметр `owner_address` вместо `owner_name` |
| co-writers | config | `src/bob/infrastructure/config/loader.py` | none | yes | дефолт `telegram.owner_address` |
| callers | telegram | `src/bob/infrastructure/telegram/health_status.py` | none | yes | только докстринг: пояс на VPS задаёт юнит |
| callers | runtime-app | `src/bob/application/runtime/serial_queue.py`, `src/bob/application/runtime/__init__.py` | none | yes | очередь с одним воркером для восприятия реакций (ревью M1) |
| co-writers | social | `src/bob/social/usecases/run_genesis.py:139` | none | no | найдено деривацией по совпадению эффекта записи YAML, работа его не трогает |

Остальное — конфигурация, `deploy/*`, systemd и документы; узлов они не имеют. Новых узлов нет,
маршрут `chore`.

## Что НЕ входит

- Качество/тон дублёра (мрачноватый уклон Qwen) — BOB-117 заземление REFLECT действует и на него.
- `keep_alive` в запросах Боба (API-уровень) — env на сервере достаточно; если Ollama сменит дефолты — отдельно.
- Mac mini и локальный Tier-0 (VISION §7) — не здесь.

## Acceptance

- [ ] выкатка: «модель дублёра на месте: qwen3.5:4b», старт «tier0 understudy: on», `/status` — «дублёр — ок»
- [ ] `ollama ps` после часа работы: обе модели, `UNTIL Forever`; журнал Ollama без циклических загрузок (Issues #68 закрыт)
- [ ] сообщение владельцу начинается с «Вова,» (или имени), время — `+03:00`
- [ ] смоук §10.2 на дублёре: «держусь на дублёре», рефлексия идёт, эпизода «я молчал» нет; «вернулся» по зонду
- [ ] тесты: адрес владельца (2 случая), деплой ставит drop-in/unit только при изменении (на фейковом каталоге), гарды конфига зелёные; `beadloom ci` PASS; PR, мёрж владельцем
