<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-019 — «Свои и чужие» (соц. идентичность · T1.4)

> **Last updated:** 2026-06-23
> **Phase:** Development
> **Epic:** bob-apv · branch `features/BOB-019`

---

## Текущий беад

**Беад:** `bob-apv.1` — dev: Interlocutor + восприятие отправителя (в работе).

## Прогресс

- [ ] `.1` Interlocutor (owner/known/guest/bot + trust) + восприятие sender_id/name
- [ ] `.2` 🔴 гость-роут + соц.-режим (без tools/owner-памяти, redaction) + stranger_directive
- [ ] `.3` first-impression per-sender стор
- [ ] `.4` test · `.5` review (+безопасность) · `.6` tech-writer

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-apv.1 | dev Interlocutor+восприятие | — | in_progress |
| bob-apv.2 | dev гость-роут+соц.-режим | .1 | blocked |
| bob-apv.3 | dev first-impression | .1 | blocked |
| bob-apv.4 | test | .1,.2,.3 | blocked |
| bob-apv.5 | review (+безопасность) | .4 | blocked |
| bob-apv.6 | tech-writer | .5 | blocked |

## Заметки

- Dev-беады **последовательно** на одной ветке (фоновые агенты, общий tree).
- 🔴 Инвариант: гость = ноль capability + ноль owner-приватной памяти; chat-scope/owner-доступ не трогаем;
  промоушен только `/authorize`. Соц.-реакция «как характер».
- `MessageReceived` уже несёт sender_id/sender_name. Источник: PRD/RFC/CONTEXT + memory bob-social-identity-strangers.
