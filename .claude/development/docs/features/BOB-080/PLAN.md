> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-01
> **Issue:** BOB-080

# PLAN — BOB-080 (DAG + seam-точки)

## Seam-точки (авторитетно, из разведки)

- Стор впечатлений: `social/adapters/first_impression_store.py` (load@49/save@65, точечные) — новый
  `recent(limit)`; порт `social/ports.py:96`. Сущность `social/first_impression.py:53` (+ note-gen
  `impression_note_for`@66/@46). ALTER `display_name`: schema `infrastructure/persistence/schema.sql:195`
  + guarded в `connection.py`; заполнение — `social/usecases/first_impression_sources.py:64`
  (`note_first_contact`, есть `interlocutor.display_name`).
- Ядро: **новый** `social/roster.py` (pure). Relationship (опц. тон): `relationship_store.py`.
- Usecase: **новый** `social/usecases/roster_recall.py`; экспонировать в `social/usecases/social_context.py`
  (рядом `recall_prior_impression`@96); собрать в `handle_message.py:1351-1356`, прокинуть в
  `_system_prompt_for` (`voice_composer.py:377`).
- READ: `personality/voice.py` (`roster_directive` рядом `recalled_impression_directive`@363) → вложить в
  `directives` (`voice_composer.py:408-446`). Приватность: viewer OWNER/KNOWN (`interlocutor.kind`).
- Wiring: `composition.py:442-451` (оба стора + connection) → построить `RosterRecall`, инъектить в
  `SocialContext` (@696/@701). Флаг `social.roster` (образец `presence.stream_read`).

## Беады

```
BOB-080 [feature] — ростер комнаты: припоминание состава по социальному поводу
├── .1 [dev] — DATA+ДОМЕН: FirstImpressionStore.recent(limit) + guarded ALTER display_name (+заполнение,
│              legacy note-parse) + чистое ядро social/roster.py (is_newcomer, build_roster) + флаг
│              social.roster (+newcomer_days/limit).
├── .2 [dev] — USECASE+READ: RosterRecall (ambient-окно: пусто без свежих; приватность OWNER/KNOWN;
│              best-effort) через SocialContext → handle_message → voice; roster_directive в voice.py +
│              вложение в voice_composer.directives; wiring в composition. deps .1
├── .3 [test] — unit (is_newcomer порог/границы; build_roster исключение владельца/порядок/limit/флаг;
│              note-parse+display_name; recent-запрос; ambient-окно; приватность) + BDD .feature (S1
│              ростер по поводу без имён / S2 новички vs старожилы / S4 без выдумки) + mutation ≥85% на
│              roster.py. deps .2
├── .4 [review] — INV-1..4; ambient-окно не флудит; приватность (гость не получает перечень); best-effort;
│              новизна строго по времени; DDD (domain I/O-free, узкий стор-метод). deps .3
└── .5 [tech-writer] — docs (social: ростер/recency-запрос/новизна по времени + voice-директива + флаг). deps .4
```

## Волны / критерии

Dev последовательно (.1→.2 — общие касания social/voice/wiring; урок BOB-066). Test → review → tw → PR →
self-merge → рестарт → живой прогон.

🔴 **Живой смоук:** «как тебе новенькие/новые ребята?» → Боб называет недавних (Лиля/Паша) САМ, без
подсказки имён; старожилов (Norman/Алексей) как «новых» не подаёт; на пустом ростере — «новеньких не
припомню» (без выдумки, INV-1/S4). Ядро `roster.py` mutation ≥85%.

## Риски (из RFC)

- Over-mention → директива «по поводу» + окно newcomer_days + компактность + флаг.
- Legacy-имя → note-parse fallback покрыт тестом; новые — display_name.
- Приватность → ростер только owner/known; authz нетронут.
- Чтение роняет ход → best-effort (пустой ростер).
- Скриптовость → ambient-окно + семантическое суждение LLM, НЕ keyword-детектор.
