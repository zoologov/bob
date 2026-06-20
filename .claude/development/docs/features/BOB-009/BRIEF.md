<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-009 — Фикс: typing-индикатор не виден (шлётся после генерации, не во время)

> **Status:** Approved
> **Created:** 2026-06-20
> **Type:** bug

---

## Проблема

Live (Вариант A): ответ быстрый и чистый, но **«Bob печатает…» не появляется**.

Корень — **жадный, не стримящий поток** в `handle_message.py`:
```python
reply = await self._router.run(request)                       # весь LLM-вызов (медленно), целиком
await self._gateway.stream_reply(tokens=_iter_tokens(reply))  # synthetic «токены» из готового текста
```
`_iter_tokens` нарезает **уже готовый** текст. `stream_reply` шлёт typing «up front», но это уже **ПОСЛЕ**
завершения генерации → typing мгновенно сменяется ответом. Медленная часть (`router.run`) проходит **до**
typing → индикатор не перекрывает ожидание → не виден (даже на медленном plus).

## Решение

**Typing-keepalive параллельно с генерацией.** Во время `router.run` (реальное ожидание) слать
`sendChatAction("typing")` в тред Боба (`message_thread_id`) каждые ~`typing_interval` (~4с), отменять
по готовности ответа, затем — один rich-финал (как в Варианте A).

Реализация: gateway даёт **typing-индикатор как async-контекст** (или keepalive-таск), оборачивающий
медленный await:
```python
async with self._gateway.typing_indicator(chat_id):
    reply = await self._router.run(request)   # typing шлётся каждые ~4с, пока ждём
await self._gateway.reply(chat_id=..., markdown=reply, thinking=...)  # один rich-финал
```
- Таск рефреша **отменяется** по выходу из контекста (без утечки); ошибка typing не валит turn.
- Инъекция `clock`/`sleep` для детерминизма тестов.
- `stream_reply` поверх synthetic-токенов — заменить/убрать (псевдо-стрим больше не нужен).

## Беады

| ID | Название | Роль | Зависит от |
|----|----------|------|------------|
| BEAD-01 | dev: typing-keepalive во время генерации (async-контекст) + один rich-финал; убрать synthetic-стрим + тесты | dev | — |
| BEAD-02 | review: typing виден во время ожидания, таск отменяется (без утечки), ответ не теряется, без регрессий | review | 01 |
| BEAD-03 | tech-writer: доки (рус) + Gate | tech-writer | 02 |

## Критерии приёмки

- [ ] Во время генерации (`router.run`) идёт повторяющийся `sendChatAction("typing")` в тред → «Bob
      печатает…» виден всё ожидание (особенно на медленном plus).
- [ ] Keepalive-таск **отменяется** по готовности ответа (без утечки/висящего таска); ошибка typing не
      валит turn.
- [ ] Ответ по-прежнему один rich-финал в тред (plain fallback); тиринг/authz целы.
- [ ] Тесты ≥80%; ruff + `mypy --strict` чисто; `beadloom ci` зелёный.
