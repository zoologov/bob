<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-049 — фокус

## Текущий бид
— (между бидами)

## Готово
- `bob-yyg.1` — шов суждения ResponseJudge + ResponseChoice/ResponseContext + DecideResponse
  + Tier-0 LlmResponseJudge (RAISE на сбое). 23 теста, 100% cov на новом коде, suite 2644 зелёный.
- `bob-yyg.2` — провязка в handle_message (ветвление REPLY/REACT/IGNORE + персист во всех ветках).
- `bob-yyg.3` — отказоустойчивость «полный Боб или честный GUPPI-нотис»:
  `call_with_retry` (новый `application/reliability.py`, ретрай ЛЮБОГО essential-сбоя с
  инъектируемым sleep); essential-шаги (суждение + генерация ответа) обёрнуты ретраем →
  при стойком сбое `OutageNotifier.notify_outage()` (GUPPI-нотис «⚠️ Проблемы со связью —
  Боб временно недоступен» в топик Боба через `_GuppiOutageNotifier`/`GUPPI_OUTAGE_TEXT`),
  ход пользователя персистится, деградированный ответ НЕ шлётся; опциональные флейворы
  (leak/callback/fascination) обёрнуты `_safe_addon` → тихо опускаются; genuine REACT/IGNORE
  ≠ сбой. +30 тестов; ruff/mypy --strict зелёные; новый код 100%/98% cov; suite 2673 зелёный.

## Следующее
- `bob-yyg.4` — test-волна (US-1..5 + authz + отказоустойчивость + регрессии).
- 🔴 Tech-writer: architecture.md + domains/application/README re-attest (sync-update bob /
  bob-application) — добавлены `application/reliability.py`, `OutageNotifier`-шов, `GUPPI_OUTAGE_TEXT`.
