<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-049 — фокус

## Текущий бид
`bob-yyg.1` — шов суждения ResponseJudge + DecideResponse + Tier-0 LlmResponseJudge.

## Прогресс
- [x] Прочитаны RFC/CONTEXT + исходники (addressivity, reaction, interlocutor, router, classify_coding_intent).
- [ ] domain: ResponseIntent/ResponseChoice/ResponseContext/ResponseJudge + промпт/парсер/валидация эмодзи.
- [ ] application: DecideResponse use-case.
- [ ] infra: LlmResponseJudge (Tier-0, RAISE on failure).
- [ ] Тесты зелёные, ruff/mypy чисто.

## Заметки
- Эмодзи-набор переиспользуем STANDARD_REACTION_EMOJI (reaction.py) — DRY.
- Добавлен TaskType.RESPONSE_JUDGE -> Tier 0 (API change).
