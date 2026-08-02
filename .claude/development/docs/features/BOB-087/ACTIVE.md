# ACTIVE — BOB-087 Человечный dev-Боб (эпик A–E)

> **Focus (Срез A):** firehose Claude Code уходит ботом GUPPI (исполнитель); голос Боба — ботом Боба.

## Срезы
| Срез | Что | Статус |
|---|---|---|
| A | GUPPI-канал (стрим ботом GUPPI) | ⏳ В РАБОТЕ |
| B | Боб-оператор + дистиллированная память | ⬜ план |
| C | Целостность памяти (домен/провенанс/register-recall) | ⬜ план 🔴 |
| D | Интерактив-2 (resume + bypass/add-dir за флагом) | ⬜ план 🔴 |
| E | Tier-0 Ollama-fallback (#34) | ⬜ план |

## Срез A — волны
| bob-abk.1 dev стрим→GUPPI | bob-abk.2 test | bob-abk.3 review | bob-abk.4 tw |

## Живой смоук (Срез A)
Флаг coder.stream_via_guppi ON → firehose приходит от GUPPI-бота, реакции/голос — от Боба. OFF → как сейчас.
🔴 Человечность: Боб звучит как Боб-оператор, не робот.

## Прогресс
- 2026-08-02: PRD/RFC/CONTEXT/PLAN approved (детальное обсуждение); эпик bob-abk; Срез A беады; ветка features/BOB-087.
- 2026-08-02: Срез B dev bob-abk.6 (оператор-голос Боба) — DONE (in_progress, ждёт координатора). Новое:
  `personality/voice.py::operator_stance()` (позитивная оператор-рамка: Боб рулит GUPPI + реагирует на вехи
  своим голосом, усиливает BOB-074 анти-нарратив; вплетён в базовый `_SYSTEM_PROMPT` voice_composer).
  `_CAPABILITY_PREFACE` — добавлена оператор-строка («ты здесь оператор: направляешь, реагируешь на РЕЗУЛЬТАТ»),
  BOB-074 запрет цел. `coding/session_voice.py` — гейт-реплики перетюнены на живые реакции оператора
  (accepted «О, любопытная задача — берусь»; pr «Всё, готово — GUPPI закрыл»; failed «Чёрт, сорвалось»;
  stopped «тормознул»). Без пер-правочного нарратива (канал GUPPI). +11 тестов; pytest 4958 / ruff / mypy(src+tests)
  / lint --strict зелёные. Prompt/template-only, флаг не нужен. Sync-check: domain-doc drift (architecture.md/README)
  — на tw-волну.
- 2026-08-02: Срез B dev bob-abk.5 (дистиллированная рабочая память, за флагом memory.work_journal OFF) — DONE (in_progress, ждёт координатора). Новое: coding/work_facts.py (аккумулятор ключевых фактов, mutation-цель), memory/work_journal.py (WorkEpisode + event_type 'work'), coding/usecases/distill_work_journal.py (WorkJournalDistiller порт + Tier0, parse mutation-цель), coding/usecases/work_journal_recorder.py (Distilling+NoOp best-effort), wiring/work_journal.py (флаг), CodingAssistant врезка (_observe_facts tee + record_session на execute-терминале). +29 тестов; pytest/ruff/mypy(src+tests)/lint зелёные. event_type CHOICE=новый 'work' (self_action recall/voice байт-в-байт). Firehose НЕ хранится сырым — только ключевые факты.
- 2026-08-02: Срез D dev bob-abk.19 (D2: permission-mode `bypassPermissions` + `--add-dir` за owner-флагами)
  — DONE (in_progress, ждёт координатора; не коммичу/не закрываю). Новое: `coding/sandbox_policy.py` —
  чистое доменное ядро «политика owner-ослаблений изоляции claude» (`allowed_modes`/`is_allowed_mode`:
  база {plan, acceptEdits}, `bypassPermissions` ТОЛЬКО при `allow_bypass=True`; `extra_dir_argv`: strip,
  отброс пустых/флагоподобных (argv-инъекция!)/с NUL, дедуп с порядком, кэп 8 → `['--add-dir', d, …]`);
  mutation 21/21 killed (100%). `_ALLOWED_MODES` удалён из claude_runner — оба раннера валидируют через ядро;
  конструкторы получили `allow_bypass=False` / `extra_dirs=()`; `build_interactive_argv` расширен `extra_dirs`
  (фрагмент ПОСЛЕ resume/continue, precedence resume>continue>fresh цела). Конфиг `coder.allow_bypass=False`
  + `coder.extra_dirs=[]` (честный комментарий: что ослабляет, почему OFF, main всё равно через PR);
  reader `_str_list` (YAML-список или CSV из env); прокидка в `_build_coding_assistant` и в runner_factory
  `_build_interactive_session`. OFF-путь доказан argv-равенством байт-в-байт + отказом `bypassPermissions`
  (ClaudeRunError, процесс не спавнится). +63 теста (pytest 5149), ruff/mypy(src+tests)/lint --strict зелёные.
  Sync-check: предсуществующий доменный drift (architecture.md по всему coding) — на tw-волну.
- 2026-08-03: Срез D dev bob-abk.20 (D3: «поднять с телефона нашу эпик-сессию» — resume-by-session-id
  из лички за флагом `coder.resume` OFF) — DONE (in_progress, ждёт координатора; не коммичу/не закрываю).
  Поток: owner шлёт ЯВНУЮ команду `/resume <workspace>` (или `/code -r`) → Боб НИЧЕГО не спавнит, а
  переспрашивает голосом Боба (называет workspace и когда та сессия была) → только явное «да» в окне
  TTL 5 мин поднимает `claude --resume <id>` в ПЕРСИСТЕНТНОМ worktree (`GitWorktree.ensure`, D1).
  Новое: `coding/resume_policy.py` — чистое ядро (select_resumable: та же ветка + непустой
  claude_session_id + ТЕРМИНАЛЬНОЕ состояние через `state.is_terminal` → самая свежая по updated_at;
  is_confirmation_fresh: двустороннее окно, часы назад = протухло); `interactive_intent`
  +parse_interactive_resume (🔴 ТОЛЬКО слэш-команда, свободный NL не распознаётся — урок BOB-076)
  +is_confirmation/is_rejection (точное совпадение всего сообщения); `session_voice` +5 реплик resume;
  узкие порты `ResumableSessionLookup.by_branch` / `PersistentWorkspace.ensure` (CodingSessionStore и
  Worktree НЕ трогал — фейки целы), `InteractiveRunner.open` получил опц. resume_session_id;
  `SqliteCodingSessionStore.by_branch`; менеджер +propose_resume/resolve_pending_resume/resume;
  интейк +опциональный ResumeSupportLike; конфиг `coder.resume=False` + wiring.
  Три предохранителя под тестами: owner-only + подтверждение (команда сама не спавнит; «нет»/чужая
  реплика/протухший TTL/чужой sender не поднимают) · нет live-attach (кандидат только терминальный +
  отказ при живой сессии) · персистентный workspace НЕ удаляется на stop и на провале спавна
  (эфемерный — удаляется, как раньше). OFF-путь доказан: при дефолтном конфиге `/resume …` не
  поглощается роутером, ничего не спавнится, БД не трогается.
  Гейты: pytest 5270 (было 5149, +121) · ruff · mypy(src 327 + tests 484) · lint --strict 0 violations.
  Mutation: resume_policy 20/20 (100%), interactive_intent 37/37 (100%), выживших нет.
  🔴 Рекалибровка (осознанная, задокументирована в rules.yml): `coding` вырос до 208 символов при
  общем потолке feature-узлов 200 → общий 200 сохранён с `exclude: [coding]`, для `coding` заведён
  ОТДЕЛЬНЫЙ явный бюджет 220 (узел не переклассифицирован; следующий по величине conversation = 178).
  Sync-check: пред-существующий доменный drift architecture.md по coding — на tw-волну.
- 2026-08-03: Срез D test bob-abk.21 (D4: BDD интерактив-2 + mutation-гейт ядер) — DONE (in_progress,
  ждёт координатора; не коммичу/не закрываю). BDD-слой живой документации поверх D1–D3, юниты НЕ дублирует:
  новый харнесс `tests/acceptance/interactive_resume_harness.py` поднимает НАСТОЯЩИЙ стек
  (InteractiveClaudeRunner над фейковым процессом → InteractiveSessionManager → InteractiveIntakeRouter)
  и наблюдает только через границу — **argv + cwd**, отданные спавнеру (`--resume <id>` / `--permission-mode`
  / `--add-dir` ровно так, как они легли бы в реальную командную строку), ensure-vs-create-vs-remove
  рабочего дерева, что поглощено/пропущено обычному Бобу, что ушло в личку, что ушло в stdin claude,
  и `pushes` (INV-2). `tests/acceptance/features/interactive_resume.feature` — 17 сценариев R1–R9
  (# language: ru): подъём ИМЕННО прошлой сессии по сохранённому session-id в персистентном workspace ·
  накопление работы между сеансами (дерево не удаляется, второй подъём реюзит его и продолжает цепочку
  session-id) · bypassPermissions отвергнут/пропущен по `coder.allow_bypass` · `--add-dir` только при
  заполненном `coder.extra_dirs` (флагоподобная запись не становится флагом) · owner-only + DM-only ·
  обязательное подтверждение (голая команда/протухшее «да»/«да, но…»/посторонняя реплика не поднимают) ·
  🔴 нет live-attach (при живой сессии отказ, команда не утекает в stdin; нетерминальная сессия не кандидат) ·
  🔴 возобновлённая сессия не пушит/не мержит/не открывает PR · флаги OFF → argv свежей сессии байт-в-байт
  равен базлайну BOB-083 и `/resume …` не поглощается.
  Гейты: pytest 5288 (было 5270, +18) · ruff · mypy(src 327 + tests 486) · beadloom lint --strict 0 violations.
  Mutation: sandbox_policy 21/21 (100%) · resume_policy 20/20 (100%) · interactive_intent 37/37 (100%) ·
  naming 23/27 (85.2%, было 81.5% — добавлен честный тест «ведущий мусор не съедает бюджет длины»,
  остаток 4 эквивалентных: регистр имени кодека ascii/ASCII ×2, `strip("XX-XX")` ×2 — символ 'X' невозможен
  после `.lower()`). 🔴 Дыра гейта: `build_interactive_argv` + `extract_session_id` (D1 объявлял их
  mutation-целями) лежат в `coding/adapters/interactive_runner.py`, а конвенция репо (`do_not_mutate =
  ["*/adapters/*"]`) адаптеры не мутирует → штатный прогон даёт 0 мутантов. Измерил временным
  override'ом (pyproject возвращён байт-в-байт): build_interactive_argv 12/12 (100%),
  extract_session_id 18/18 (100%) — ядра сильные, но постоянного гейта у них НЕТ.
  🔴 Найденная дыра поведения (не чинил — тест-роль): `session_voice.stopped()` говорит «рабочую копию
  убрал» и для ВОЗОБНОВЛЁННОЙ (персистентной) сессии, у которой дерево сознательно НЕ удаляется —
  Боб сообщает owner'у неправду о судьбе накопленной работы.
  Sync-check: пред-существующий доменный drift architecture.md — на tw-волну.
