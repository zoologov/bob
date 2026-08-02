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
