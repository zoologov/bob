&lt;!-- beadloom:badge-start -->
> ✅ **fresh**
> 
> last synced 2026-07-31T12:12:20.297951+00:00 · coverage 100% (`coding`)
> 
> _Validation by Beadloom `doc_sync` — same source as `sync-check`._
&lt;!-- beadloom:badge-end -->

&lt;!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль coding — «Боб пишет код»

Гейтованный автономный кодинг: по команде owner'а Боб гоняет локальный `claude` CLI
над собственным репозиторием, собирает план, после явного апрува исполняет его в
изолированном worktree и открывает PR. Мержа в машине нет — Боб останавливается на
открытом PR, интеграцию в `main` делает owner вручную вне Боба.

Это первый **вертикальный** модуль domain-first раскладки (BOB-062.1, срез 1/8 эпика
BOB-062): вся способность собрана в одном месте `src/bob/coding/`, а не размазана по
слоям `domain/` + `application/usecases/` + `infrastructure/`. Модуль охватывает три
слоя **внутри** одного bounded-context, поэтому в графе он несёт не-слойный тег
`module-vertical` (правило `architecture-layers` его рёбра пропускает), а внутреннюю
и внешнюю дисциплину держат path-glob `forbid_import`-правила в
`.beadloom/_graph/rules.yml`.

## Спецификация

### Раскладка модуля

```
src/bob/coding/
  ports.py            # layer=domain   — порты-протоколы способности
  __init__.py         # layer=domain   — фасад (CodingSession, предикаты, narrate, worktree_branch)
  state.py            # layer=domain   — машина состояний + чистые предикаты переходов
  entities.py         # layer=domain   — CodingSession (immutable value-object)
  naming.py           # layer=domain   — worktree_branch: безопасное имя ветки bob/<slug>
  narrate.py          # layer=domain   — stream-json событие Claude Code → нарратив-строка / None
  intent.py           # layer=domain   — is_approval / is_stop (чистые предикаты NL-команд)
  session_voice.py    # layer=domain   — детерминированные шаблоны реплик в персоне Боба
  usecases/           # layer=application
    coding_assistant.py       — CodingAssistant (оркестратор гейтед-сессии)
    coding_context.py         — make_coding_context (арх-преамбула в claude-промпт)
    classify_coding_intent.py — ClassifyCodingIntent (Tier-0 классификатор «это dev-запрос?»)
    coding_intent_router.py   — CodingIntentRouter (NL-маршрутизация к гейтед-сессии)
  adapters/           # layer=infrastructure
    claude_runner.py    — SubprocessClaudeRunner (headless claude через subprocess, без shell)
    git_worktree.py     — GitWorktree (изолированный worktree только на трекнутых файлах)
    gh_pr.py            — GhPullRequestOpener (gh pr create; НИКОГДА merge)
    session_store.py    — SqliteCodingSessionStore (персист сессий через рестарт)
    indicator.py        — TypingKeepalive + StatusPanel (индикаторы работы в топике Боба)
    owner_notifier.py   — _CodingOwnerNotifier (нотификатор owner'а; переехал из app.py, BOB-062.7a)
    _branch.py, _exec.py — внутренние shell-free хелперы адаптеров
```

### Машина состояний (чистый домен)

`CodingSessionState` (`state.py`) — строковый `StrEnum` (значение совпадает с
TEXT-колонкой SQLite). Жизненный цикл:

```
PROPOSED → PLANNING → PLAN_READY → EXECUTING → PR_OPEN  (успешный терминал)
                          │ (ГЕЙТ ПЛАНА)
CANCELLED / FAILED ← из любого нетерминального
```

`EXECUTING` достижимо **только** из `PLAN_READY` (непробиваемый гейт плана). Чистые
предикаты: `can_transition`, `can_start`, `can_approve_plan`, `can_stop` (kill-switch
из любого нетерминального), `is_terminal` (`PR_OPEN`/`DONE`/`CANCELLED`/`FAILED`).
`CodingSession` (`entities.py`) — immutable `frozen, slots` value-object без I/O и
часов: момент времени инжектится параметром `at` в мутаторы `with_state`/`with_plan`/
`with_worktree`/`with_pr_url` (каждый возвращает новый объект).

### Оркестратор (application)

`CodingAssistant` (`usecases/coding_assistant.py`) — чисто-оркестрационный use-case
над чистым доменом и инжектированными портами (раннер, worktree, стор, PR-открывашка,
нотификатор owner, authz, часы, фабрика id) плюс опциональные сеймы индикаторов и
арх-контекста. Четыре owner-only метода: `start(task, sender)` (worktree + план без
правок → `PLAN_READY`, останавливается), `approve_plan(sender)` (гейт: только из
`PLAN_READY` → исполнение → PR → `PR_OPEN`), `stop(sender)` (kill-switch → `CANCELLED`
+ уборка worktree), `status(sender)`. Естественный язык (постановка задачи Бобу его
словами в топике) маршрутизируется `CodingIntentRouter` поверх Tier-0
`ClassifyCodingIntent`; NL-путь **не обходит ни одного гейта** — лишь выбирает, *когда*
звать `start`/`approve_plan`/`stop`.

### Адаптеры (infrastructure)

`SubprocessClaudeRunner` гоняет `claude` headless через `create_subprocess_exec`
(никогда не shell), с фиксированным allowlist режимов `{plan, acceptEdits}` и лимитами
(таймаут/события/байты). `GitWorktree` создаёт worktree на новой ветке фиксированной
формы `bob/<slug>` — свежий worktree содержит **только трекнутые файлы**, поэтому
приватные данные Боба (`data/soul/`, `bob.db*`, `.env*`, `config/*` — все gitignored)
в нём физически отсутствуют. `GhPullRequestOpener` строит единственную форму
`gh pr create --base main --head <branch>` (discrete argv, без shell) — merge-метода в
порте нет. `SqliteCodingSessionStore` round-trip'ит `CodingSession` (двойной гейт
честен и через границу процесса).

## Инварианты

- **Never-merge:** в порте `PullRequestOpener` и в модуле физически **нет** merge-пути
  и git-записи в защищённую ветку. Боб открывает PR и останавливается (`PR_OPEN` —
  успешный терминал).
- **PR ≠ merge:** `is_terminal(PR_OPEN)` истинно — завершённая сессия не блокирует
  новую, но нового пути в `EXECUTING` это не создаёт.
- **Двойной гейт плана:** `EXECUTING` достижимо только из `PLAN_READY`; на уровне
  домена (таблица переходов) и повторно на уровне use-case'а (`can_approve_plan`).
- **Worktree-изоляция:** приватные gitignored-данные отсутствуют в свежем worktree —
  Claude Code их не видит; `remove` проверяет containment (symlink-resolved потомок
  `worktree_root`).
- **Sender-is-bob / owner-гейт (defense-in-depth):** тройная owner-проверка —
  `_maybe_route_coding` пускает только `InterlocutorKind.OWNER`, роутер перепроверяет
  `is_owner`, use-case проверяет `OwnerCheck.is_owner` на каждом методе. Отправитель
  сообщений сессии — **бот Боба** (BOB-046), нарратив атрибутирован GUPPI (`GUPPI: …`).
- **NL-safe:** естественно-языковой путь не обходит гейтов; классификатор намерения
  консервативен (ложноположительное лишь предложит план за гейтом).
- **Off-by-default:** мастер-switch `coder.enabled` по умолчанию `false`; при выключенном
  флаге assistant не подключён и шов инертен.
- **Shell-free:** все внешние вызовы (`claude`, `git`, `gh`) идут через
  `create_subprocess_exec` дискретными argv, без интерполяции метасимволов.

### Границы модуля (AaC)

Дисциплина держится path-glob `forbid_import`-правилами (`.beadloom/_graph/rules.yml`,
§ vertical modules):
- `usecases/` не импортят `adapters/` (только порты; адаптеры — на композиции);
- доменная логика/адаптеры не импортят `usecases/`;
- снаружи к `coding` — только через фасад/порты (не `usecases/`/`adapters/` напрямую);
- модуль не импортит композиционный корень (`app.py`).

Три cross-boundary ссылки узаконены по дизайну (не нарушения): `classify_coding_intent
→ application/router/llm_router` (общий shared-router вне модулей), `coding_context →
capabilities/introspection/privacy_guard` (TYPE_CHECKING-only; `PrivacyGuard` переехал
в вертикальный модуль `capabilities`, BOB-062.4) и `adapters/indicator →
infrastructure/telegram/gateway` (TYPE_CHECKING-only). Если любая станет runtime-импортом
— всплывёт в скане и подлежит переоценке.

## API

&lt;!-- beadloom:track=src/bob/coding/ports.py -->

Модуль `src/bob/coding/ports.py` (порты-протоколы, только интерфейсы):
- `ClaudeCodeRunner` — шов headless-раннера Claude Code.
- `Worktree` — шов изолированного git-worktree.
- `CodingSessionStore` — шов долговечного хранилища сессий.
- `PullRequestOpener` — шов открытия PR (merge-метода намеренно нет).

Фасад `src/bob/coding/__init__.py` re-export'ит: `CodingSession`, `CodingSessionState`,
`can_transition`, `can_start`, `can_approve_plan`, `can_stop`, `is_terminal`, `narrate`,
`worktree_branch`. Канонический импорт портов — `from bob.coding.ports import
ClaudeCodeRunner`; транзитный ports-шим `bob.domain.ports` удалён (BOB-062.8).

Ключевые точки входа:
- `state.py`: `can_transition(frm, to)`, `can_approve_plan(state)`, `can_stop(state)`,
  `is_terminal(state)` → `bool`.
- `naming.py`: `worktree_branch(task)` → `str` (безопасное `bob/<slug>`).
- `narrate.py`: `narrate(event)` → `str | None`.
- `intent.py`: `is_approval(text)`, `is_stop(text)` → `bool`.
- `usecases/coding_assistant.py`: `CodingAssistant` — `start`/`approve_plan`/`stop`/`status`.
- `usecases/coding_intent_router.py`: `CodingIntentRouter.route(text, sender, is_owner)`.
- `usecases/classify_coding_intent.py`: `ClassifyCodingIntent.is_coding_request(text)`.
- `usecases/coding_context.py`: `make_coding_context(...)` — bounded, privacy-safe преамбула;
  собственный узкий `_is_safe_doc_path` (сегмент-префикс `src`/`tests`/`docs`/`.claude/dev-docs`/
  `.claude/development/docs`) НЕ пускает personal-data доки (SOUL/`bob.db`/`.env`/`config`) во
  внешнюю coder-преамбулу, хотя расширенный full-repo `PrivacyGuard` (BOB-067) в чате их читает.
- `adapters/`: `SubprocessClaudeRunner`, `GitWorktree`, `GhPullRequestOpener`,
  `SqliteCodingSessionStore`, `TypingKeepalive`, `StatusPanel`.

Композиция и owner-команды (`/code`, `/code approve`, `/code stop`, `/code status`) —
в композиционном корне `app.py` (`_build_coding_assistant` / `_build_coding_router`,
только при `coder.enabled`) и GUPPI (`infrastructure/telegram/guppi.py`). Подробный
разбор потока, голоса Боба на гейтах и индикаторов работы — в `docs/architecture.md`
(раздел «Боб запускает Claude Code: гейтед coding-сессия»).

## Тесты

Тесты покрывают коды-инварианты и поведение (identical после переезда): машина
состояний и гейт плана, never-merge (отсутствие опасных токенов в `gh_pr`),
worktree-изоляция и containment, allowlist режимов раннера, консервативность
классификатора намерения и предикатов апрува/стопа, автономный guard (coding вне
`goals.safe_capabilities`). См. `tests/` (переехавшие coding-тесты, включая строковые
литералы путей в `test_coding_never_merge_and_autonomy_guard.py`, обновлены под
`src/bob/coding/`).
