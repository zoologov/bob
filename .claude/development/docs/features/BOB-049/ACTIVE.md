<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-049 — фокус

## Текущий бид
— (между бидами)

## Готово
- `bob-yyg.1` — шов суждения ResponseJudge + ResponseChoice/ResponseContext + DecideResponse
  + Tier-0 LlmResponseJudge (RAISE на сбое). 23 теста, 100% cov на новом коде, suite 2644 зелёный.

## Следующее
- `bob-yyg.2` — провязка в handle_message (ветвление + персист во всех ветках).
