<!-- beadloom:badge-start -->
> ✅ **fresh**
> 
> last synced 2026-10-21T21:04:41.376096+00:00 · coverage 10% (`telegram`)
> 
> _Validation by Beadloom `doc_sync` — same source as `sync-check`._
<!-- beadloom:badge-end -->

<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# telegram — транспортный адаптер (aiogram)

Транспортный адаптер Telegram на aiogram: long-polling-приём с authz-гейтом, нативный
draft-стриминг и Rich Messages, пиннинг ответа в topic-thread, `MultiBotGateway`
(два admin-бота в одном процессе с cross-bot дедупом и центральным identity/scope
роутером) и gatekeeper `GuppiHandler`. Узел `telegram` (`part_of` слоя
`bob-infrastructure`, source `src/bob/infrastructure/telegram/`). Это чистый транспорт:
бизнес-решения принимаются выше, здесь — только приём/отправка и порты-протоколы.

## Спецификация

### Модули

- **gateway.py** — `TelegramGateway`, long-polling-приём + ход «typing-индикатор →
  финальный rich-ответ» поверх бота: `poll_once`, `intake`, `intake_reaction`,
  `typing_indicator`, `reply`, `react`, `send_photo`, `send_document`, `set_bob_identity`,
  `bob_user_id`. Здесь же узкие структурные порты Telegram (`BotLike`, `UpdateLike`,
  `MessageLike`, `MessageEntityLike`, реакционные `*Like`, `AuthorizerLike`,
  `BotIdentitySignals`) — держат тесты без сети. `RichMarkdownSender` шлёт markdown
  нативным rich-сообщением, деградируя к plain-тексту при rich-ошибке; `is_reaction_update`.
  🔴 Нормализация входящего (`_to_message_received`) доводит до приложения два сигнала,
  которые апдейт нёс и раньше, а граница теряла (BOB-090): `message_thread_id` →
  `MessageReceived.topic_id` (точный адрес рядом с `chat_id`) и `from_user.username` →
  `MessageReceived.sender_username` (ник без «собаки», без него обращение в комнате
  невозможно). Ни то ни другое не достраивается: нет — значит `None`.
- **aiogram_adapter.py** — `_AiogramBotAdapter`, конкретный край Telegram за портом
  `BotLike`: адаптирует async-`Bot` aiogram (`get_me`, `get_updates`, `send_message`,
  `send_chat_action`, `send_rich_message`, `edit_message_text`, `set_message_reaction`,
  `send_photo`, `send_document`); view-адаптеры над aiogram `Update` и `_BobReactionFilter`
  (реакция на собственное сообщение Боба, BOB-050).
- **multibot.py** — `MultiBotGateway`, один процесс, два admin-бота, один центральный
  роутер (BOB-003): поллит каждого зарегистрированного бота, дедупит cross-bot и
  маршрутизирует по контенту (`poll_once`, `route`, `reply_gateway`, `reactor`,
  `resolve_bot_identities`). `BotRegistry` (набор ботов, ключ — `BotIdentity`),
  `BotScope` (чат, опционально пиннутый к topic-thread'у), `BotRegistration`.
- **guppi.py** — `GuppiHandler`, gatekeeper/admin-идентичность GUPPI (BOB-003):
  видимый reject неавторизованного, объявление обиды и owner-команды `/quiet`, `/wake`,
  `/goals`, `/code`, `/rules`, `/rule <действие> <id>` (`reject`, `announce_sulk`,
  `handle_general_command`) поверх узких store-портов (`ProactivityStoreLike`,
  `GoalStoreLike`, `PursuitStoreLike`, `CodingAssistantLike`, `RuleStoreLike`).
  🔴 `/rules` перечисляет ВСЕ правила Боба и объясняет, почему он о каком-то молчит
  (BOB-096): `· не доставлено` — попытки отправки исчерпаны; `· нечего одобрять` —
  предложение вырожденное; `· просит 0.7 при потолке 0.3` — содержание есть, величина
  выше конфигурного потолка. Причину считает домен (`unactionable_reason` /
  `is_undelivered_proposal`), GUPPI лишь кладёт её в слова, а потолок берёт тот же, с
  которым провязан анонсёр (`rule_max_magnitude`, проброс через `MultiBotGateway`), —
  иначе список судил бы по одному числу, а молчание Боба по другому. Числа в третьей
  метке показываются намеренно: из них владелец и решает, поднять потолок или отклонить.
  Совпадение чисел держится провязкой, а не типом: у анонсёра `max_magnitude` обязателен
  без умолчания, а здесь и у `MultiBotGateway` умолчание есть (`MAGNITUDE_RANGE_TOP`,
  то есть «потолка не сообщили»), поэтому непровязанный `GuppiHandler` покажет мусор, но
  промолчит о превышении. Живая сборка передаёт настоящее число — это проверяется тестом
  через `_build_multibot` и настоящую команду владельца, а не через конструктор.
  🔴 `/status` (BOB-116 D6) отвечает whoami-строкой и, если подключён `HealthReader`, снимком
  здоровья LLM-провайдеров (`health_status.render_health_status`), прочитанным в момент
  команды, а не при сборке. Читатель — необязательный параметр `health` у `GuppiHandler` и у
  `MultiBotGateway`, который передаёт его в `_build_guppi`; без него `/status` байт-в-байт
  прежний.
- **health_status.py** (BOB-116 D6) — чистая функция `render_health_status(snapshot, *,
  tz=None)`: снимок монитора → блок строк по-русски, по строке на провайдера:
  ```
  LLM:
  tier0 облако — деградирован с 2026-10-01 06:10 +03:00 (не пускало по ключу/квоте, 5 подряд)
  дублёр — нет
  tier1 — ок
  ```
  Порядок — `tier0-primary`, `tier0-understudy`, `tier1`, незнакомые id следом по алфавиту
  под своим id. Нет дублёра — «нет»; дублёр, снятый при старте, — «выключен при старте:
  <причина> (до перезапуска)»; здоровый с допороговыми отказами — «ок, сбоев подряд: N (…)».
  Причина — безличная фраза `bob.kernel.ru_text.failure_report`, та же таблица, что в
  сообщении владельцу и в эпизоде «я молчал». Время начала отказа — в поясе процесса с явным
  смещением (`bob.kernel.local_time`).
- **owner_alert.py** (BOB-116 D4) — `OwnerAlert(bot, owner_id, *, timeout_seconds=5.0)`,
  реализация порта `OwnerAlertSink`: личное сообщение владельцу ботом Боба
  (`send_message(chat_id=owner_id, text=…)` под `asyncio.wait_for`), без LLM — путь сигнала
  не зависит от того, что сломалось. Таймаут живёт в адаптере (5 с, как у объявления
  рестарта); `timeout_seconds ≤ 0` — `ValueError`; `TimeoutError` и ошибки транспорта уходят
  наружу, глотает их монитор. `NoopOwnerAlert` — для `llm.health.owner_alert: false`.
  Адаптер не тянет ни LLM-стек, ни `proactivity`: это держит тест на собранном импорте, а не
  на тексте исходника.
- **rich.py** — `MarkdownToRichMessage`, чистая конвертация markdown → дерево aiogram
  `RichMessage` (`convert`): заголовки/списки/цитаты/код/inline (bold/italic/`code`/spoiler)
  **+ GFM-таблицы `| … |` → нативный `RichBlockTable`** (header `is_header`, выравнивание из
  separator `:---:`, inline в ячейках; рваная/неполная → деградация в paragraph, BOB-086, Bot API 10.1);
  `RichMessageSerializer` — обратный рендер дерева в rich-message markdown (`to_markdown`).
- **outage_notifier.py** — `_GuppiOutageNotifier`, честная системная строка «Bob
  unavailable» в топик Боба при outage'е (`notify_outage`, BOB-049 .3). 🔴 Строка уходит в
  фиксированные `chat_id`/`topic_id` группы, а не туда, откуда пришёл ход: на ход владельца в
  личке он видит тишину, а в теме группы появляется строка о сообщении, которого там никто не
  видел. Дефект найден ревью BOB-116, не регресс этой работы; беада `bob-hod`, Issues #71.
- **restart_notifier.py** — `_RestartNotifier`, объявление рестарта голосом Боба
  (`notify_owner` в личку owner'а + `notify_group` в топик Боба, BOB-094 срез 1) поверх
  того же узкого plain-`send_message`, что и outage-нотис. Транспорт только: таймаут и
  best-effort живут в use-case `proactivity.usecases.announce_restart`.
- **outbound_messenger.py** — `TelegramOutboundMessenger`, отправка по ЯВНОМУ адресу
  (`send(chat_id, topic_id, markdown)`, BOB-090.B1) поверх того же `RichMarkdownSender`:
  новый транспорт не заводился — недоставало понятия «исходящий адрес». `topic_id`
  передаётся как есть и не выдумывается: в форум-группе `None` — это General, а не «чат».

## Инварианты

- Все Telegram-контракты объявлены как узкие структурные Protocol (`BotLike`, `UpdateLike`,
  …) — приём и отправка тестируются без сети.
- `MultiBotGateway` дедупит cross-bot по `(chat_id, message_id)` — одно сообщение,
  прилетевшее обоим ботам, обрабатывается один раз.
- Транспорт не принимает бизнес-решений: authz — через `AuthorizerLike`, компоновка
  ответа — выше по стеку.
- `RichMarkdownSender` деградирует к plain-тексту при rich-ошибке — ответ доходит всегда.
- Тред не выдумывается: `message_thread_id` передаётся сквозь (`None` = «топика нет»).
  Обратное и было дефектом ack'а разрешения — он падал в General (BOB-090.B5).

## API

Модуль `src/bob/infrastructure/telegram/gateway.py`:
- `TelegramGateway.poll_once()` / `.intake(...)` / `.reply(...)` / `.react(...)` — приём и отправка.

Модуль `src/bob/infrastructure/telegram/multibot.py`:
- `MultiBotGateway.poll_once()` / `.route(...)` / `.reply_gateway(...)` — два бота, один роутер.
- `BotRegistry.register(...)` / `.get(...)` / `.scope_of(...)` — реестр ботов.

Модуль `src/bob/infrastructure/telegram/guppi.py`:
- `GuppiHandler.reject(...)` / `.handle_general_command(...)` — gatekeeper + owner-команды;
  конструктор принимает необязательный `health: HealthReader | None` для `/status`.

Модуль `src/bob/infrastructure/telegram/health_status.py`:
- `render_health_status(snapshot, *, tz=None)` → `str` — блок «LLM:» для `/status`.

Модуль `src/bob/infrastructure/telegram/owner_alert.py`:
- `OwnerAlert(bot, owner_id, *, timeout_seconds=5.0).notify_owner(text)` — личка владельцу;
  свойство `timeout_seconds`; `NoopOwnerAlert`; константа `DEFAULT_TIMEOUT_SECONDS = 5.0`.

Модуль `src/bob/infrastructure/telegram/rich.py`:
- `MarkdownToRichMessage.convert(...)` / `RichMessageSerializer.to_markdown(...)` — markdown ↔ RichMessage.

## Тестирование

Тесты: `tests/infrastructure/telegram/test_gateway.py`, `test_gateway_reaction.py`,
`test_guppi.py`, `test_guppi_proactivity.py`, `test_guppi_rules.py`,
`test_multibot_content_routing.py`, `test_multibot_guppi.py`, `test_rich.py`,
`test_rich_markdown_sender.py`, `test_coding_indicator.py`. Здоровье LLM (BOB-116):
`test_guppi_health_status.py` (рендер снимка, пояс и смещение, «выключен при старте»,
провязка читателя через `MultiBotGateway`), `test_owner_alert.py` (личка владельца, таймаут,
путь сигнала не грузит LLM-стек). Живая документация — `tests/acceptance/features/llm_health.feature`
S9 (`/status` показывает состояние LLM-стека и время начала отказа) и S13 (`/status`
показывает лежащий `tier1`).

<!-- beadloom:track=src/bob/infrastructure/telegram/gateway.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/aiogram_adapter.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/multibot.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/guppi.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/rich.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/outbound_messenger.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/outage_notifier.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/restart_notifier.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/health_status.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/owner_alert.py -->
