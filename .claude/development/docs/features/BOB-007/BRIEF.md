<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-007 — Нативные драфты-first в топике (плавный стрим) + edit-fallback

> **Status:** Approved
> **Created:** 2026-06-20
> **Type:** feature

---

## Проблема

Live: стриминг в топике через `editMessageText` с троттлом 3с — **медленно и рывками** (ответ
обновляется раз в 3с, длинный занимает минуты). Это костыль, который мы ввели, ошибочно решив, что
«драфты в группах не работают».

**Первоисточник ([core.telegram.org/bots/api#sendrichmessagedraft](https://core.telegram.org/bots/api#sendrichmessagedraft)):**
боты поддерживают `sendMessageDraft`/`sendRichMessageDraft` нативно **включая топики групп** при
включённом **Threaded Mode**. Прошлый `TEXTDRAFT_PEER_INVALID` был именно из-за **выключенного**
Threaded Mode. Owner **включил Threaded Mode в BotFather** → нативные драфты должны заработать в топике.

## Решение

**Нативные драфты — основной путь стриминга для всех чатов (включая топики); edit-стриминг — fallback.**

- **Primary:** `sendMessageDraft` / `sendRichMessageDraft` (нативный плавный токен-стрим, с
  `message_thread_id` где нужно) — **без 3с-троттла, без edit-спама, без флуда**. Rich-блоки +
  `RichBlockThinking` стримятся нативно.
- **Fallback (без регресса):** если драфт вернёт `TelegramBadRequest` (напр. `TEXTDRAFT_PEER_INVALID`) →
  существующий **edit-стриминг (throttled)** → **plain** (safety-net BOB-004). Работа BOB-004/006
  становится подстраховкой, не выкидывается.
- **Убрать 3с edit-троттл из основного пути** (он остаётся только на fallback edit-пути).
- **Гибридный тиринг (flash/plus) — оставить** (быстрая модель + нативный стрим = снапповый чат).

## Беады

| ID | Название | Роль | Зависит от |
|----|----------|------|------------|
| BEAD-01 | dev: драфты-first для топиков (нативный стрим) + edit/plain fallback на ошибке драфта + тесты | dev | — |
| BEAD-02 | review: корректность стрима/fallback, ответ не теряется, без регрессий tiering/authz | review | 01 |
| BEAD-03 | tech-writer: доки (рус) + Gate | tech-writer | 02 |

## Критерии приёмки

- [ ] В топике стрим идёт через **нативные драфты** (плавно, без 3с-троттла) — подтверждается live.
- [ ] При ошибке драфта (`TelegramBadRequest`) — **graceful fallback** на edit-стриминг → plain; ответ
      **не теряется**.
- [ ] `RichBlockThinking`/rich-блоки в драфт-стриме сохранены; гибридный тиринг работает.
- [ ] Тесты ≥80%; ruff + `mypy --strict` чисто; `beadloom ci` зелёный.
