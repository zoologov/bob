> **Status:** Approved
> **Type:** feature
> **Created:** 2026-07-31
> **Issue:** BOB-078

# PLAN — BOB-078 (DAG + seam-точки из разведки)

## Seam-точки (авторитетно, из разведки)

**A (пол):**
- Детектор: новый чистый детектор рода (домен, pure) + Tier-0 адаптер по образцу
  `personality/usecases/update_mood_from_text.py:72-127` (само-презентация: родовые глаголы «пошла/
  пошёл», местоимения; fem|masc|unknown). Запуск где `SenderPerception.resolve` (`social/usecases/
  sender_perception.py:44`).
- Хранить: колонка `gender` в `person_relationship` (`social/adapters/relationship_store.py`, UPSERT
  per sender_id) — миграция guarded ALTER; накопление уверенности (как оси relationship). НЕ в
  write-once `first_impression`.
- VO: поле `gender` в `Interlocutor` (`social/interlocutor.py:68`).
- Применить: строка в `who_is_writing_directive` (`personality/voice.py:227`) — «обращайся в женском/
  мужском/нейтральном роде»; уже в system_prompt (`voice_composer.py:429`). Прецедент — `guppi_canon`
  (`voice.py:111`, форс мужского рода GUPPI).

**B (engagement):**
- Прокинуть per-message `kind`/«новичок» в батч: `BatchAmbientMessage` (`conversation/room_reading.py:212`),
  `build_batch_room_prompt` (`conversation/room_reading_wire.py:349`), `room_stream_reader.py:118` (там
  `kind` доступен через resolve). Правило в `BATCH_ROOM_READ_SYSTEM_PROMPT` (`room_reading_wire.py:306`):
  «соц-значимую реплику участника не игнорь».
- «Ты»-обращение к Бобу → directed-ish в `classify_addressivity` (`conversation/addressivity.py:92`) —
  🔴 только когда адресовано Бобу (не третьему; эвристика границ как у вокатива `addressivity.py:187`).
  Порог `SALIENCE_THRESHOLD` (`room_verdict.py:54`) НЕ трогать.

**C (анти-повтор):**
- 🔴 СНАЧАЛА найти, почему BOB-026/032 анти-повтор не поймал дубль на stream-read reply-пути (обходит ли
  batch-применение проверку). Опоры: анти-повтор BOB-026/032, `voice_composer`, персист bob-сообщений.
- Guard: не отправлять реплику с дословным/почти-дословным совпадением с недавними своими ответами
  (нормализованное сравнение по окну последних N bob-сообщений) → перегенерация/вариация. Чистое ядро.

## Часть D — Резилентность приёма (интейк не глохнет от ошибки coding-router)
🔴 Живой инцидент: `coding_intent_router.route` дёргается на КАЖДОМ сообщении (`precompose_gate.
maybe_route_coding`, `handle_message.py:1319`); ошибка в `active()`/`active_state()` (напр. битый
`state` в БД → `ValueError`) → **весь intake-воркер падает** → Боб оглох на owner. Fix: обернуть
coding-router вызов (или `active()`/`active_state`) в try/except → на ошибке лог + treat as no active
session → ход ПРОДОЛЖАЕТСЯ (обычный chat-путь), не крашит приём. Плюс `session_store.active()`
устойчив к битой строке (пропустить/лог, не бросать весь список).

## Беады
```
BOB-078 [feature] — качество группового диалога
├── .1 [dev] — A: детектор рода (само-презентация) + gender в person_relationship + Interlocutor + who_is_writing_directive
├── .2 [dev] — B: kind/новичок в batch-контекст + правило промпта engagement + «ты»-directed адресность. deps .1
├── .3 [dev] — C: найти обход анти-повтора на stream-путь + guard дословного само-дубля. deps .2
├── .4 [dev] — D: резилентность интейка — ошибка coding-router/active() НЕ крашит приём (chat-путь продолжается). deps .3
├── .5 [test] — unit (детектор рода; «ты»-directed без ложных; анти-дубль; интейк выживает битую сессию) + BDD + mutation. deps .4
├── .6 [review] — A не-по-имени/unknown; B баланс/«ты»-к-Бобу; C легит-повторы; D приём не глохнет; DDD. deps .5
└── .7 [tech-writer] — docs (social gender + conversation engagement/анти-повтор + intake резилентность). deps .6
```

## Волны / критерии
Dev последовательно (.1→.2→.3, урок BOB-066). Test → review → tw → PR → self-merge → restart → живой прогон.
🔴 Живой смоук: детектор рода на реплике Лили → fem; анти-дубль на повторе. Все чистые ядра mutation ≥85%.
Флаг НЕ нужен (правки поведения аддитивны + консервативны); но unknown/баланс — дефолт безопасный.

## Риски
- A: не угадывать по имени (только грамматика); порог уверенности; unknown→нейтрально.
- B: «ты» частотно → требовать адресованность Бобу; не влезать в кросс-ток; баланс «не баржить».
- C: не подавлять легитимные короткие повторы («да»/«ок»); нормализация сравнения аккуратная.
