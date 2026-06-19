<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-004 — Фикс: draft-стриминг падает в теме супергруппы (TEXTDRAFT_PEER_INVALID)

> **Status:** Approved
> **Created:** 2026-06-19
> **Type:** bug

---

## Проблема

Live-тест (первый запуск двух ботов): при ответе Боба в теме супергруппы нативный стриминг через
`sendMessageDraft` / `sendRichMessageDraft` падает с
`aiogram.exceptions.TelegramBadRequest: Bad Request: TEXTDRAFT_PEER_INVALID`.

- **Приём и роутинг работают** (Боб получает сообщение в своём топике `thread_id=37`, topic-scope верный).
- Падает **только отправка ответа** через draft-методы: Telegram-драфты валидны не для всякого peer и
  отклоняются в группе/теме.
- Fallback на plain (BOB-002) НЕ спасает: он ловит ошибку rich-финала, а здесь падает **draft-путь**
  раньше, и исключение всплывает (turn не доставляет ответ).
- На фейк-ботах не воспроизводилось (фейки принимали draft-вызовы).

## Решение

**Draft-стриминг → best-effort.** В gateway обернуть draft-вызовы (`send_message_draft`/
`send_rich_message_draft`) в `try/except TelegramBadRequest` (и родственные): при отказе —
- перестать слать драфты в этом turn (и, опц., запомнить, что peer не поддерживает драфты),
- **доставить ответ финальным НЕ-draft send**: `send_rich_message` → при ошибке `send_message` (plain),
  всегда с `message_thread_id` (ответ в тред).
- Драфты **никогда не блокируют** доставку финального ответа.
- (Опционально: пропускать драфты сразу для не-private чатов — но catch-and-fallback общее и надёжнее.)

## Живая печать в теме (Вариант B — выбрано 2026-06-19)

Драфты — только ЛС. Для **живой печати «как в GPT» в теме** — инкрементальный `editMessageText`:
- **Тема/группа:** шлём плейсхолдер → **редактируем его plain-текстом по мере генерации** (троттлинг,
  уважая `TelegramRetryAfter`) → **финал = `send_rich_message`** (таблицы/математика/**`RichBlockThinking`**)
  + **удаляем плейсхолдер** (Вариант B: живая печать + полный rich, ценой лёгкого мерцания).
- **ЛС:** нативный `sendMessageDraft`/`sendRichMessageDraft`.
- При ошибке rich-финала → edit плейсхолдера в entity-formatted plain → safety-net BEAD-01.

## Беады

| ID | Название | Роль | Зависит от |
|----|----------|------|------------|
| BEAD-01 | dev: draft-стриминг best-effort + гарантированная доставка финала (rich→plain, в тред) + регресс-тест | dev | — |
| BEAD-02 | dev: живая печать в теме (инкрементальный edit-стриминг) + финал rich/RichBlockThinking (Вариант B) + удаление плейсхолдера + тесты | dev | 01 |

## Критерии приёмки

- [ ] Когда draft-вызов кидает `TelegramBadRequest` (TEXTDRAFT_PEER_INVALID), ответ Боба всё равно
      **доставляется** финальным send (`send_rich_message`→`send_message`) в правильный тред.
- [ ] Исключение из draft-пути не всплывает и не роняет turn/рантайм.
- [ ] Регресс-тест на фейк-боте: draft кидает TEXTDRAFT_PEER_INVALID → ассерт, что финал доставлен.
- [ ] Существующие тесты зелёные; ruff + `mypy --strict` чисто; `beadloom ci` зелёный.
