> **Status:** Approved
> **Type:** epic
> **Created:** 2026-08-02
> **Issue:** BOB-087

# RFC — Человечный dev-Боб (швы по срезам, из разведки)

## Срез A — GUPPI-канал (стрим ботом GUPPI)
Единственная точка выбора бота: `composition.py:516 notifier_bot=resolved_bob_bot` (+ :536 интерактив,
:548 интейк). GUPPI-бот доступен `resolved_guppi_bot` (`composition.py:501-505`). `_CodingOwnerNotifier`
(`coding/adapters/owner_notifier.py:29-58`) и `_DmLiveStreamer` берут инъектированный бот — не выбирают сами.
- Стрим/firehose → строить notifier поверх **GUPPI-бота**; Боб-голос (session_voice гейты «берусь/готово»,
  реакции) — остаётся ботом Боба. `narrate.py:46 _GUPPI_PREFIX` (косметика) можно упростить — теперь
  атрибуция настоящая (шлёт GUPPI).
- 🔴 Feasibility: GUPPI-бот шлёт в свой scope (General, topic=None); для dev-канала (личка/топик) — куда
  постить? Опции: GUPPI постит firehose в отдельный dev-топик/личку (owner должен нажать Start на GUPPI-боте
  — проверить), Боб-реакции в свой топик/личку. Решается в срезе (флаг `coder.stream_via_guppi`).

## Срез B — Боб-оператор + дистиллированная память
- Оператор-голос: `coding/session_voice.py` (двухголосый сплит уже есть) расширить — Боб даёт директивы
  GUPPI + реагирует. `personality/voice.py:111 guppi_canon` + `voice_composer.py:99 _CAPABILITY_PREFACE`
  (BOB-074) — оператор-рамка.
- Дистилляция сессии → эпизоды: сегодня авто-память грубая (`memory/self_action.py` 5 kinds; запись
  `coding_assistant.py:_record:567` на вехах; interactive_session НЕ пишет ничего). Добавить **дистиллятор**
  (Tier-0/локальный) арки сессии → несколько ДЕТАЛЬНЫХ первого-лица `self_action`/новый `work`-эпизодов
  (файлы/тесты/сломалось/фикс). 🔴 НЕ per-firehose-event (флуд) — на смысловых точках / в конце сессии.
  Чокпоинт записи: `_record`→`MemoryBackedSelfActionRecorder.record` (`self_action_recorder.py:56`) — один
  `save_episode_entity` на вызов.

## Срез C — целостность памяти (домен + провенанс + register-recall)
- **Домен/провенанс:** `EpisodicEvent` (`memory/entities.py:37-60`) — колонки `tags`/`event_type`/
  `visibility` есть, поля актора нет. Ввести домен-тег (`work`/`dev`) + провенанс (актор: bob/guppi/tool/
  test) — через tags + новую конвенцию/поле. Провенанс-guard уже есть (`voice.py:438 recall_has_self_action`
  + `_RECALLED_SELF_ACTION_DIRECTIVE:428` первого-лица).
- **Register-aware recall:** `fts_recall.py:85-98` / `hybrid_recall.py:101-136` — recall **глобальный без
  фильтра** по тегу/домену. Ввести scope/register-параметр: в dev-контексте work-домен в полном весе; в
  casual — приглушён (down-weight, не исключение → сквозной). Точка: `_recall_surfaceable`
  (`handle_message.py:~2062`) передаёт контекст-регистр в recall/фильтр (по образцу `filter_surfaceable`
  visibility). 🔴 По умолчанию (флаг OFF) — recall байт-в-байт (INV-5).
- **Анти-яд:** GUPPI-firehose НЕ в episodic_log (срез A убирает его из бот-Боба-истории); рабочие эпизоды
  первого-лица; work-домен вне casual-few-shot.

## Срез D — интерактив срез 2 (за флагом owner-only)
- **resume/continue:** claude CLI умеет `-c/--continue`, `--resume`, `--from-pr`. Прокинуть в
  `interactive_runner.py` argv (сейчас каждый `/code -i` свежий). Хранить session-id (coding_session) для resume.
- **permission-mode config:** `_ALLOWED_MODES={plan,acceptEdits}` (`claude_runner.py:52`,
  `interactive_runner.py:44`) — добавить `bypassPermissions` **только** за явным флагом
  `coder.allow_bypass` (owner-only); иначе allowlist как есть. Comment «no bypassPermissions ever» —
  снимаем ТОЛЬКО под флаг.
- **--add-dir:** прокинуть доп-директории в argv за флагом `coder.extra_dirs` — ослабляет worktree-изоляцию
  → owner-only, явно. main через PR не трогаем.

## Срез E — Tier-0 Ollama-fallback (#34)
- Роутер `application/router/llm_router.py` (Tier-0 «no fallback» при отвале Aliyun). Добавить локальный
  **Ollama-провайдер как fallback для Tier-0**: при сбое облачного Tier-0 → локальная small-модель (класс/
  монолог/гейты). Config `llm.tier0_fallback: ollama`. Приватность/локальность (уже стек Ollama BGE-M3).

## Тест/безопасность (сквозное)
Каждый срез: TDD + BDD + mutation на чистых ядрах (дистиллятор/провенанс/recall-scope — mutation-цели);
🔴 живой смоук человечности («Боб звучит как Боб»); C — тест «work не всплывает в casual / не путает
актора»; D — security-review (bypass/add-dir owner-only, main цел); флаги default OFF → байт-в-байт.
