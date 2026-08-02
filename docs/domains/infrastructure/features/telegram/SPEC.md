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
  `/goals`, `/code`, … (`reject`, `announce_sulk`, `handle_general_command`) поверх
  узких store-портов (`ProactivityStoreLike`, `GoalStoreLike`, `PursuitStoreLike`,
  `CodingAssistantLike`, `RuleStoreLike`).
- **rich.py** — `MarkdownToRichMessage`, чистая конвертация markdown → дерево aiogram
  `RichMessage` (`convert`): заголовки/списки/цитаты/код/inline (bold/italic/`code`/spoiler)
  **+ GFM-таблицы `| … |` → нативный `RichBlockTable`** (header `is_header`, выравнивание из
  separator `:---:`, inline в ячейках; рваная/неполная → деградация в paragraph, BOB-086, Bot API 10.1);
  `RichMessageSerializer` — обратный рендер дерева в rich-message markdown (`to_markdown`).
- **outage_notifier.py** — `_GuppiOutageNotifier`, честная системная строка «Bob
  unavailable» в топик Боба при outage'е (`notify_outage`, BOB-049 .3).

## Инварианты

- Все Telegram-контракты объявлены как узкие структурные Protocol (`BotLike`, `UpdateLike`,
  …) — приём и отправка тестируются без сети.
- `MultiBotGateway` дедупит cross-bot по `(chat_id, message_id)` — одно сообщение,
  прилетевшее обоим ботам, обрабатывается один раз.
- Транспорт не принимает бизнес-решений: authz — через `AuthorizerLike`, компоновка
  ответа — выше по стеку.
- `RichMarkdownSender` деградирует к plain-тексту при rich-ошибке — ответ доходит всегда.

## API

Модуль `src/bob/infrastructure/telegram/gateway.py`:
- `TelegramGateway.poll_once()` / `.intake(...)` / `.reply(...)` / `.react(...)` — приём и отправка.

Модуль `src/bob/infrastructure/telegram/multibot.py`:
- `MultiBotGateway.poll_once()` / `.route(...)` / `.reply_gateway(...)` — два бота, один роутер.
- `BotRegistry.register(...)` / `.get(...)` / `.scope_of(...)` — реестр ботов.

Модуль `src/bob/infrastructure/telegram/guppi.py`:
- `GuppiHandler.reject(...)` / `.handle_general_command(...)` — gatekeeper + owner-команды.

Модуль `src/bob/infrastructure/telegram/rich.py`:
- `MarkdownToRichMessage.convert(...)` / `RichMessageSerializer.to_markdown(...)` — markdown ↔ RichMessage.

## Тестирование

Тесты: `tests/infrastructure/telegram/test_gateway.py`, `test_gateway_reaction.py`,
`test_guppi.py`, `test_guppi_proactivity.py`, `test_guppi_rules.py`,
`test_multibot_content_routing.py`, `test_multibot_guppi.py`, `test_rich.py`,
`test_rich_markdown_sender.py`, `test_coding_indicator.py`.

<!-- beadloom:track=src/bob/infrastructure/telegram/gateway.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/aiogram_adapter.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/multibot.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/guppi.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/rich.py -->
<!-- beadloom:track=src/bob/infrastructure/telegram/outage_notifier.py -->
