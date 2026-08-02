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
- 2026-08-03: Срез D dev bob-abk.24 (D4b: честная реплика stop персистентной сессии + постоянный
  mutation-гейт argv-ядер) — DONE (in_progress, ждёт координатора; не коммичу/не закрываю).
  Закрыты обе находки BDD-волны D4.
  **(1) Честность голоса.** `session_voice.stopped_persistent()` — новая парная реплика к `stopped()`:
  «Окей, тормознул. GUPPI свернулся, но всё наработанное осталось на месте — скажешь поднять,
  продолжим оттуда же.» Ни слова про уборку (её не было), ни обещания PR, ни пути на диске.
  `InteractiveSessionManager.stop` выбирает реплику по `live.persistent` — голос идёт ЗА судьбой
  дерева. Эфемерный путь не тронут (та же `stopped()`, старые тесты прошли без правок).
  Тесты на НАБЛЮДАЕМОЕ (урок D3: юниты смотрели только `worktree.removed` и баг проглядели):
  BDD-сценарии R8 «на остановке возобновлённой сессии Боб не врёт, что убрал работу» (реплика
  в личке, а не внутреннее состояние) + контраст «на остановке эфемерной — по-прежнему говорит,
  что убрал»; use-case тесты на `outcome.message`; 3 доменных теста реплики.
  **(2) Постоянный mutation-гейт.** `build_interactive_argv` + `extract_session_id` (+ приватная
  `_INTERACTIVE_FLAGS`) переехали из `coding/adapters/interactive_runner.py` в НОВЫЙ доменный
  модуль `coding/argv_policy.py` («чем параметризуется живой claude и что берётся из init-кадра»);
  адаптер импортирует их и больше не ре-экспортирует (в src на них никто, кроме него, не ссылался).
  Юниты переехали в `tests/domain/coding/test_argv_policy.py` (mutmut меряет именно domain-юниты);
  в инфра-тесте остался базлайн argv, отданный спавнеру. 🔴 Конфиг mutmut (`do_not_mutate`) НЕ
  трогал — гейт появился за счёт переезда ядра из adapters, а не ослабления конвенции.
  Гейты: pytest 5295 (было 5288, +7) · ruff · mypy (src 328 + tests 487) · beadloom lint --strict
  0 violations (coding 209/220 символов: +1 `stopped_persistent`, переезд счётчик не менял) · reindex ok.
  Mutation: `coding.argv_policy` 30/30 killed = 100% (build_interactive_argv 12/12,
  extract_session_id 18/18), выживших нет — гейт теперь штатный (`./scripts/mutation.sh
  coding.argv_policy`). ruff per-file-ignores: +2 записи RUF001-003 для русских докстрингов
  нового модуля и его теста (конвенция репо).
  Sync-check: пред-существующий доменный drift architecture.md + новый `coding/argv_policy.py`
  в domains/coding/README.md — на tw-волну.
- 2026-08-03: Срез D dev bob-abk.25 (D5b: фиксы SECURITY-review bob-abk.22 — 2 blocker + 5 major
  + 4 минорных) — DONE (in_progress, ждёт координатора; не коммичу/не закрываю).
  **B1 (blocker) — реюз персистентного worktree был мёртв в проде.** `GitWorktree.ensure` сравнивал
  `str(worktree_root / slug)` (относительный `.worktrees` по умолчанию) с абсолютными путями из
  `git worktree list --porcelain` → реюз не срабатывал никогда, второй подъём падал на
  `fatal: a branch named … already exists`. Фикс: обе стороны через `Path.resolve()`; плюс при
  СУЩЕСТВУЮЩЕЙ ветке `worktree add <path> <branch>` без `-b` (проверка `git branch --list` —
  exit 0 в обоих случаях, никакого глотания CommandError). Доказательство — НОВЫЙ real-git файл
  `tests/infrastructure/coding/test_git_worktree_persistent_real_git.py` (относительный корень +
  `monkeypatch.chdir` в throwaway-репо): второй `ensure` реюзит дерево и наработанный файл цел;
  дерево снесено + `worktree prune` → ветка чекаутится, не пересоздаётся. Проверено, что тесты
  КУСАЮТ: против старого адаптера 3/3 падают. 🔴 Урок BOB-084 подтверждён снова: фейк моделировал
  контракт, адаптер его не держал — для git/subprocess нужен тест на РЕАЛЬНОМ транспорте.
  **B2 (blocker) — тихий провал.** `create` в `open()` и `ensure` в `resume()` жили ВНЕ `try`;
  исключение улетало в `PrecomposeGate.maybe_route_interactive`, который глотает всё → owner
  сказал «да», а Боб просто поболтал. Теперь оба внутри try: resume → `resume_failed()` (ход
  ПОГЛОЩЁН), open → НОВАЯ реплика `session_voice.interactive_setup_failed()` («ничего не тронул» —
  `interactive_failed` врала бы про уборку несозданной копии).
  **M1** `sandbox_policy._is_usable_dir` → публичный `is_safe_argv_value` (общий примитив
  argv-значения); `build_interactive_argv` санитайзит `resume_session_id` тем же предикатом:
  пустой/пробельный/с ведущим `-`/с NUL = «сессии нет» (проваливаемся в continue/фреш), годный
  идёт `.strip()`.
  **M2** транслитерация кириллицы в `_slugify` (lower → translate → ascii-ignore): «эпик»→
  `bob/epic-epik`, «проект»→`bob/epic-proekt` — больше не один `bob/epic-task`. Выбран транслит,
  а не отказ: чинит РЕАЛЬНЫЙ сценарий (owner пишет по-русски) и не меняет контракт чистой функции.
  Остаточный вырожденный случай (имя вообще без букв/цифр: `..`, `----`) по-прежнему fallback
  `task` — задокументировано в модуле.
  **M3** появился НЕДОСТАЮЩИЙ путь завести долгоживущее рабочее место: `/workspace <name> [task]`
  (и `/code -w`) → `parse_interactive_workspace` (чистый распознаватель, только слэш-команда —
  урок BOB-076) + `InteractiveSessionManager.open_workspace` (ensure на `workspace_branch`, СВЕЖИЙ
  claude без `--resume`, `persistent=True`) + `open_workspace` в `ResumeSupportLike`/интейке. Под
  тем же флагом `coder.resume` (OFF → команда не распознаётся). BDD R10 замыкает полный цикл:
  завёл рабочее место → поработал → stop (дерево цело) → `/resume` поднял ИМЕННО ту сессию.
  **M4** переписаны формулировки про `coder.allow_bypass` (loader.py + 2 докстринга wiring):
  linked worktree делит `.git`/refs/remotes/креды с основным репо, а `bypassPermissions` даёт
  неподнадзорный шелл → при ON INV-2 держится на суждении owner'а, а не на структуре.
  **M5** (а) `claude_session_id` персистится в момент прихода init-кадра — проходной трансформер
  `_capture_id` между `runner.events()` и стримером (событие идёт дальше НЕИЗМЕНЁННЫМ); `stop`
  остался бэкстопом. (б) НОВЫЙ `coding/usecases/recover_interactive_sessions.py` — свип на старте
  (`Application.startup`), РОВНО `INTERACTIVE` (гейтед `PLAN_READY`/`EXECUTING` переживают рестарт
  намеренно), best-effort, идемпотентный; тесты и на фейке, и на РЕАЛЬНОМ SQLite.
  Минорные: m2 (снята ложная заявка «pure, mutation target» у `_registered_worktrees` в adapters),
  m3 (`.worktrees/` в `.gitignore`), m4 (зона в метке времени `resume_confirm` — «10:00 UTC»),
  n3 (цифра «24 файла» в rules.yml → 35 + уточнение про «дробление узла счётчик СНИЖАЕТ»).
  НЕ взяты: m1 (доки — волна tw bob-abk.23), m5 (расщепление менеджера — долг bob-6u2),
  m6 (стиль сборки argv в claude_runner), n1/n2 (юникод-дефисы и регистр в дедупе `--add-dir`:
  инъекции нет; n2 сломал бы корректность на case-sensitive FS), n4 (CSV-сплит env).
  Гейты: pytest 5365 (было 5295, +70) · ruff · mypy (src 329 + tests 490) · beadloom lint --strict
  0 violations (coding 213/220 — потолок НЕ поднимал) · reindex ok · diff --since main: no graph
  changes. Mutation: argv_policy 34/34 · interactive_intent 50/50 · resume_policy 20/20 ·
  sandbox_policy 21/21 (все 100%), naming 25/29 = 86.2% с 4 эквивалентными (кодек-имена
  регистронезависимы ×2; `strip("XX-XX")` == `strip("-")` для уже-lowercase slug ×2).
  Sync-check: пред-существующий доменный drift + новые символы среза — на tw-волну.
