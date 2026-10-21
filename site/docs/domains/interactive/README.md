<!-- beadloom:badge-start -->
> ✅ **fresh**
> 
> last synced 2026-10-21T21:04:41.376096+00:00 · coverage 100% (`interactive`)
> 
> _Validation by Beadloom `doc_sync` — same source as `sync-check`._
<!-- beadloom:badge-end -->

<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Модуль interactive — «Боб держит живой терминал»

Живой двусторонний сеанс `claude` в личке owner'а: Боб открывает долгоживущий процесс с
открытым stdin, льёт его вывод в личку и передаёт туда реплики owner'а — тот правит
`claude` в реальном времени, в том числе в **долгоживущем рабочем месте**, копящем работу
между сеансами, и позже поднимает ту же сессию «с телефона». PR-открывашки на этом пути
нет вовсе: правки остаются в изолированном worktree, интеграцию в `main` owner делает сам
через существующий гейт гейтед-кодера (модуль [`coding`](../coding/README.md)).

**Почему это отдельный bounded context (BOB-087.E, беада `bob-6u2`).** Живой терминал
вырос внутри `coding` и довёл тот узел до потолка правила `no-monster-modules`. Честный
разбор показал, что дело не в раздутых файлах, а в том, что в одном узле жили ДВА языка:

| | гейтед-кодер (`coding`) | живой терминал (`interactive`) |
|---|---|---|
| словарь | план, апрув, PR | сеанс, реплика, возобновление |
| процесс | эфемерный прогон до EOF | долгоживущий, с открытым stdin |
| управление | двойной гейт, kill-switch | прямой kill, steer каждой репликой |
| главный инвариант | `EXECUTING` только из `PLAN_READY` | одна сессия за раз, никакого live-attach |
| конец | PR открыт, Боб остановился | сеанс закрыт (owner'ом или процессом самим) |

Общее у них — **рабочее место**, а не язык: worktree, строка сессии в БД, транспорт
`claude`. Поэтому `interactive` — самостоятельный модуль-вертикаль (тег
`module-vertical`), который ОПИРАЕТСЯ на общую доменную поверхность `coding`
(одностороннее ребро `interactive → coding`; `coding` о живом терминале не знает ничего).

🔴 Пакет — **сосед** (`src/bob/interactive/`), а не подпапка `src/bob/coding/`, и это
несущее решение: beadloom считает размер узла по ПРЕФИКСУ `source`
(`code_symbols.file_path LIKE '<source>%'`), поэтому вложенный узел учитывался бы дважды и
`coding` не потерял бы ни одного символа — разделение было бы косметическим.

## Спецификация

### Раскладка модуля

```
src/bob/interactive/
  __init__.py           # layer=domain   — фасад (LiveSession, select_resumable, is_confirmation_fresh)
  entities.py           # layer=domain   — LiveSession: держатель живого сеанса (запись + раннер + судьба дерева)
  intent.py             # layer=domain   — четыре чистых распознавателя DM-команд: parse_interactive_entry (/code -i), parse_interactive_workspace (/workspace), parse_interactive_resume (/resume), is_interactive_exit + is_confirmation/is_rejection
  resume_policy.py      # layer=domain   — select_resumable / is_confirmation_fresh: можно ли поднять приостановленную работу и какую (BOB-087.D3)
  resume_negotiation.py # layer=domain   — ResumeNegotiation: висящий вопрос «поднимаю?» (взвести / разрешить / снять) + исходы ResumeConfirmed/ResumeRejected (BOB-087.E)
  argv_policy.py        # layer=domain   — build_interactive_argv / extract_session_id: чем параметризуется живой claude и что берётся из init-кадра (BOB-087.D1/D4b)
  pipeline_prompt.py    # layer=domain   — кадры, которыми Боб правит сессией: pipeline_first_frame (постановка задачи, BOB-088 срез 2) и permission_retry_frame (возвращение после «да» владельца, срез 3)
  tool_permissions.py   # layer=domain   — tool_permission_argv: узкий ЗАПРЕТ необратимого (всегда), разрешение рутины конвейера (флаг) и ОДНОРАЗОВОЕ точечное доразрешение — BOB-088 срез 3
  permission_denial.py  # layer=domain   — DenialWatch: прочитать в потоке system/permission_denied и назвать, ЧЕГО Боб не смог (команда берётся из связанного tool_use, не из message CLI)
  permission_negotiation.py # layer=domain — PermissionNegotiation: висящий вопрос «упёрся в запрет, разрешаешь?» + исходы PermissionGranted/PermissionRefused (окно PERMISSION_TTL = 30 минут)
  denial_voice.py       # layer=domain   — голос Боба на отказ: вопрос живой речью (без кнопок и слешей), «делаю», «не трогаю», «возвращаться некуда»
  voice.py              # layer=domain   — детерминированные реплики режима (вход/выход, «сеанс кончился сам», цикл возобновления) + ре-экспорт двух общих строк управления сессией
  usecases/             # layer=application
    session.py          — InteractiveSessionManager: жизненный цикл ОДНОГО живого сеанса (open/feed/stop/active + open_workspace/propose_resume/resolve_pending_resume/resume + resolve_pending_permission)
    teardown.py         — SessionTeardown: терминальное завершение забранного сеанса (kill раннера, судьба дерева, терминальная строка)
    intake.py           — InteractiveIntakeRouter: вход / steer→stdin / выход в личке (owner+DM)
    recover_sessions.py — RecoverInteractiveSessions: свип осиротевших INTERACTIVE-строк на старте процесса (BOB-087.D5b)
  adapters/             # layer=infrastructure
    runner.py           — InteractiveClaudeRunner: персистентный claude с ОТКРЫТЫМ stdin (open/feed/events/close) + encode_user_message
```

Из `coding` берётся ОБЩАЯ поверхность сеанса и ничего сверх неё: `entities`
(`CodingSession`, `CodingOutcome`), `ports` (`Worktree`, `CodingSessionStore`,
`InteractiveRunner`, `PersistentWorkspace`, `ResumableSessionLookup`, `OwnerCheck`,
`OwnerNotifier`, `LiveRunStreamer`), `state` (машина состояний), `naming`
(`worktree_branch` / `workspace_branch`), `sandbox_policy` (allowlist режимов +
`ClaudeRunError`), `push_guard`, `stream_json` (разбор NDJSON + предел буфера) и две
общие реплики управления сессией из `session_voice` (`stopped`, `no_session`).

### Живой сеанс (application)

`InteractiveSessionManager` (`usecases/session.py`) — owner-only оркестратор ОДНОГО живого
сеанса. `open(task, sender)` создаёт изолированный worktree на ветке `bob/<slug>`, спавнит
раннер в валидном `permission_mode`, персистит сессию в состоянии `INTERACTIVE` и заводит
фоновую перекачку вывода в личку через порт `LiveRunStreamer` (реюз `_DmLiveStreamer`
BOB-082, `verbose=True` — BOB-085). `feed(text)` форвардит реплику в открытый stdin.
`stop(sender)` — 🔴 ПРЯМОЙ kill (`runner.close()`: terminate→grace→kill→reap), уборка
эфемерного дерева и перевод сессии в терминальное `CANCELLED`. `active()` отвечает
интейк-гейту, идёт ли сеанс.

🔴 **Сеанс может кончиться и БЕЗ owner-команды** (bob-kv4): `claude` крашится, выходит сам
или чтение stdout обрывается. Конец потока событий завершает сеанс ТЕМ ЖЕ путём, что
`stop`, и owner слышит ЧЕСТНУЮ реплику `interactive_ended` — выдать смерть процесса за
исполнение его «стоп» значило бы приписать owner'у чужое действие. **Идемпотентность
структурная:** забрать сеанс можно только через `_claim` — синхронный обмен (проверка и
обнуление `_live` без единого `await` между ними), поэтому гонка «процесс умер И owner
жмёт стоп» не даёт ни двойного закрытия, ни двойной реплики. 🔴 Это несущая конструкция:
`_claim` и поле `_live` остаются в менеджере при любой декомпозиции.

Менеджер держит РЕШЕНИЯ (кто жив, кто забрал сеанс, что услышит owner), а два соседа —
механику:

- **`ResumeNegotiation`** (`resume_negotiation.py`) — машина висящего вопроса «поднимаю?»:
  взвести (`ask`), разрешить следующим ходом (`settle` → `ResumeConfirmed` /
  `ResumeRejected` / `None`), снять. Вопрос ОДИН (новый вытесняет прежний), АДРЕСНЫЙ
  (отвечает только тот, кому задан) и НЕ ЗАЛИПАЕТ (любой ход спрашиваемого его снимает —
  поэтому «да», сказанное потом по другому поводу, ничего не поднимет). Окно свежести —
  чистая политика `is_confirmation_fresh`.
- **`SessionTeardown`** (`usecases/teardown.py`) — ПОСЛЕДСТВИЯ конца, одинаковые для обоих
  его поводов (явный `stop` и смерть процесса) и нарочно ОДНИ: судьба рабочего дерева и
  терминальная запись не смеют разъезжаться по поводу окончания. Всё best-effort по одному
  правилу: уборка не отменяет уже случившийся конец сеанса — ни сбой `close`, ни сбой
  `git worktree remove`, ни сбой стора не съедают прощальную реплику.

### Приём в личке (application)

`InteractiveIntakeRouter` (`usecases/intake.py`) решает судьбу ОДНОГО owner-DM сообщения:
открыть сеанс, сфорвардить реплику в stdin, закрыть — и возвращает, был ли ход ПОГЛОЩЁН
(тогда обычный chat-путь его не ведёт). 🔴 **owner-only + DM-only** проверяются здесь
(defense-in-depth поверх owner-гейта менеджера), а **режим не залипает**: steer-гейт
работает ТОЛЬКО пока `active()` истинно, поэтому после `stop` или смерти процесса личка
возвращается к обычному общению. На входе/выходе роутер шлёт короткую строку режима
(INV-5: owner всегда знает, в каком он режиме).

### Долгоживущее рабочее место и возобновление (BOB-087.D, флаг `coder.resume`, default OFF)

Эфемерный интерактив BOB-083 удалял worktree на «стоп», поэтому накапливать работу между
сеансами было негде. Второй, ДОЛГОЖИВУЩИЙ путь: owner заводит именованное рабочее место,
работает в нём, останавливается — и позже поднимает ту же сессию `claude`.

- **Команды owner'а в личке.** `/workspace <name> [task]` (синоним `/code -w <name> [task]`)
  — завести сеанс сразу в долгоживущем workspace; имя — первый токен, задача опущена →
  задачей становится само имя. `/resume <workspace>` (синоним `/code -r <workspace>`) —
  попросить поднять прошлую сессию. Ответ на вопрос-подтверждение — «да» либо «нет» ЦЕЛЫМ
  сообщением (`is_confirmation` / `is_rejection`, множества не пересекаются: «да, но
  сначала покажи дифф» подтверждением не считается). 🔴 Распознаётся ТОЛЬКО явная
  слэш-команда: свободный естественный язык здесь не разбирается и разбираться не будет —
  однажды дешёвая Tier-0 мис-классификация болтовни уже запустила runaway-кодер (BOB-076).
- **Двухшаговое подтверждение с TTL.** `/resume` сам по себе не поднимает ничего:
  `propose_resume` находит кандидата и задаёт вопрос голосом Боба, называя workspace и
  время той сессии (метка с зоной, чтобы owner с телефона не подтвердил не ту).
  `resolve_pending_resume` разрешает вопрос следующим ходом: «да» в окне
  `CONFIRMATION_TTL` (5 минут; окно двустороннее — часы, ушедшие назад, считаются
  протухшими) → `resume`; «нет» → отмена; любая другая реплика, ответ не того отправителя
  или истёкший TTL → вопрос СНИМАЕТСЯ, а ход идёт обычным разговорным путём.
- **Поднять можно только остановленную сессию.** Кандидата выбирает чистая политика
  `select_resumable`: та же ветка, непустой `claude_session_id` и ТЕРМИНАЛЬНОЕ состояние
  (`coding.state.is_terminal` — тот же единственный источник правды, что и у стора); из
  подходящих берётся самая свежая по `updated_at`. 🔴 Live-attach невозможен структурно:
  живая `INTERACTIVE`-сессия кандидатом не является, а при живом сеансе весь resume-путь
  отказывает (одна сессия за раз) — два водителя за одним процессом `claude` встретиться
  не могут.
- **Дерево переживает «стоп».** `open_workspace` и `resume` работают в персистентном
  worktree (`PersistentWorkspace.ensure` на ветке `workspace_branch(name)` =
  `bob/epic-<slug>` — отдельное пространство имён, с эфемерной `bob/<slug>` не
  пересекается). `stop` такое дерево НЕ удаляет, как не удаляет его и провал спавна: в нём
  накоплена работа, ради которой сессию и поднимали. Маркер персистентности
  (`LiveSession.persistent`) живёт в памяти рядом с живым сеансом — по имени ветки его
  выводить нельзя (эфемерная задача, названная «epic …», дала бы ту же форму), а колонки в
  БД он не требует.
- **Session-id claude.** `extract_session_id` берёт id из первого `init`-кадра потока, а
  `_capture_id` (проходной трансформер между раннером и стримером; событие уходит в личку
  НЕИЗМЕНЁННЫМ, рендер байт-в-байт прежний) сразу пишет его в
  `coding_session.claude_session_id`. Раньше id сохранялся только на «стоп», и краш
  посреди сеанса терял его навсегда; теперь `stop` — лишь бэкстоп.
- **Свип на старте процесса.** `RecoverInteractiveSessions` (вызывается из
  `Application.startup`) переводит осиротевшие `INTERACTIVE`-строки в `CANCELLED`. Живой
  сеанс существует ровно столько, сколько живёт держащий его процесс, поэтому увиденная на
  старте `INTERACTIVE`-строка по определению осиротела. Пока строка нетерминальна,
  `active()` отдаёт её как in-flight и гейтед-кодер на любую новую задачу отвечает «я уже
  в работе», а `select_resumable` её пропускает и поднимает более старую нить разговора.
  Свип нарочно узкий — только `INTERACTIVE`; гейтед стадии (`PLANNING` / `PLAN_READY` /
  `EXECUTING`) рестарт переживают намеренно. Идемпотентен и best-effort: уронить старт он
  права не имеет. Собирается безусловно — строка могла остаться от прежнего запуска.
- **Голос.** `workspace_opened` честно предупреждает, что дерево долгоживущее;
  `stopped_persistent` (парная к общей `stopped`) на остановке такой сессии не говорит ни
  слова про уборку — её не было; `interactive_setup_failed` отвечает на провал ПОДГОТОВКИ
  дерева («ничего не тронул» — в отличие от `interactive_failed`, где копия создавалась и
  убрана); `resume_confirm` / `resume_nothing` / `resume_cancelled` / `resumed` /
  `resume_failed` ведут двухшаговый путь. Реплика всегда идёт за реальной судьбой файлов —
  Боб не докладывает об уборке того, что осталось на месте.
- **Ни один сбой не уходит в молчание (BOB-087.D5b B2 + D5c N2).** Приёмный гейт глотает
  любое исключение роутера и уводит ход обычным chat-путём, поэтому падение внутри
  интерактива выглядело бы как «owner сказал «да», а Боб просто поболтал». Правило:
  подготовка дерева (`create` / `ensure`), поиск кандидата (`by_branch`) и персист — все
  под `try`, и любой сбой ПОСЛЕ спавна не только отвечает owner'у честной репликой, но и
  закрывает раннер, чтобы не остался неостановимый процесс без живой сессии (`_go_live`
  возвращает признак успеха, `_resumable_or_refusal` различает «сбой стора» и «нечего
  поднимать», `SessionTeardown` не теряет прощание).
- **OFF (default).** При выключенном `coder.resume` узкие порты `lookup` / `workspace` не
  инъектируются, а роутер вообще не держит resume-seam: ни `/workspace …`, ни `/resume …`
  не являются командами, персистентное дерево не создаётся, поведение байт-в-байт как в
  BOB-083.

### Транспорт (infrastructure)

`InteractiveClaudeRunner` (`adapters/runner.py`) держит **персистентный** процесс
`claude -p --input-format stream-json --output-format stream-json --verbose
--permission-mode <mode>`, спавненный через `create_subprocess_exec` (никогда не shell,
каждый элемент argv — дискретный токен) с `stdin=PIPE, stdout=PIPE, stderr=PIPE`.
`feed` кодирует реплику owner'а в ОДИН stream-json user-фрейм (`encode_user_message` —
чистое ядро) и пишет её в stdin; `events` читает stdout NDJSON построчно через общий
примитив `coding.stream_json` (`parse_event`, буфер `STREAM_LIMIT` = 16 МиБ — та самая
защита от краша BOB-084 на строке >64 КБ); `close` — `terminate→grace→kill→reap`,
идемпотентно, никогда не бросает, зомби не оставляет.

Argv собирает не адаптер, а чистая политика `argv_policy.build_interactive_argv`
(приоритет `--resume` > `--continue` > фреш; `--add-dir` — всегда суффикс); адаптер лишь
доносит её вердикт до границы процесса. Режим валидируется общей политикой
`coding.sandbox_policy` (allowlist `{plan, acceptEdits}`, плюс `bypassPermissions` ТОЛЬКО
под owner-флагом `coder.allow_bypass`), и под тем же флагом спавн несёт push-барьер
`coding.push_guard`.

🔴 **Живой терминал наследует рабочее место и изоляцию из BOB-089.** Под флагом
`coder.isolated_clone` композиция подставляет сюда тот же адаптер, что и гейтед-кодеру:
рабочим местом становится отдельный КЛОН со своим `.git` (`GitClone` вместо `GitWorktree`,
один объект обслуживает и эфемерный `worktree`, и персистентный `workspace`), а
`InteractiveClaudeRunner` получает `isolation` — окружение спавна без кредов owner'а
(подробности и честная рамка — в README [`coding`](../coding/README.md) и
[`identity`](../identity/README.md)). Подмена происходит в `runtime/wiring/coding.py`, а не
в менеджере: он по-прежнему видит только порты. OFF (default) → `None` и прежний linked
worktree, спавн байт-в-байт как в BOB-083.

## Инварианты

- **Одна сессия за раз.** `open` при живой сессии отказывает; весь resume-путь при живой
  сессии отказывает тоже.
- **Никакого live-attach.** Возобновить можно ТОЛЬКО терминальную сессию — это требование
  чистой политики `select_resumable`, а не проверка в оркестраторе.
- **Подтверждение обязательно.** `/resume` только задаёт вопрос; поднимает сессию
  исключительно явное «да» того же owner'а в окне `CONFIRMATION_TTL`.
- **Идемпотентный конец.** Сеанс забирается ровно один раз (`_claim`, синхронный обмен) —
  «процесс умер И owner жмёт стоп» закрывает его один раз и отвечает одной репликой.
- **Никакого PR/push/merge.** У менеджера структурно нет PR-открывашки; правки остаются в
  worktree `bob/<slug>` (или `bob/epic-<slug>`), в `main` — только через существующий гейт
  `coding`. 🔴 Оговорка при `coder.allow_bypass: true`: это верно про КОД Боба, но linked
  worktree делит с основным репозиторием `.git`, refs, remotes и credentials, а
  `bypassPermissions` даёт claude неподнадзорное выполнение — тогда неприкосновенность
  `main` держится на суждении owner'а, а не на структуре (см. README `coding`).
  🔴 `coder.isolated_clone` закрывает именно эту локальную дорогу (у клона свой `.git`, общих
  refs нет), но не отменяет оговорку целиком: под одним UID остаются прямой `ssh` ключом
  owner'а и файловый путь до его репозитория — названное ограничение, которое закрывает
  только раздельный UID (беады BOB-093 / BOB-094).
- **owner-only + DM-only, режим не залипает.** Гейты проверяются и в интейке, и в
  менеджере; steer работает только при активной сессии.
- **Off-by-default.** Живой терминал строится лишь при `coder.interactive`; resume-путь —
  лишь при `coder.resume`; оба по умолчанию выключены.
- **Реплика идёт за судьбой файлов.** Боб не докладывает об уборке того, что осталось на
  месте, и не выдаёт смерть процесса за owner-«стоп».
- **Shell-free.** Спавн `claude` — дискретный argv через `create_subprocess_exec`; всё,
  что попадает в argv извне (`--add-dir` из конфига, `--resume` из колонки БД), проходит
  `is_safe_argv_value`.

### Границы модуля (AaC)

Дисциплина держится path-glob `forbid_import`-правилами
(`.beadloom/_graph/rules.yml`, генерируемый регион):

- `usecases/` не импортят `adapters/` (только порты; адаптеры — на композиции);
- доменная логика не импортит ни `usecases/`, ни `adapters/`;
- снаружи к `interactive` — только через фасад/порты (не `usecases/`/`adapters/` напрямую);
- модуль не импортит композиционный корень (`app.py` / `bob.runtime.*`).

🔴 Единственное межмодульное ребро — `interactive → coding`, и оно ведёт в КОРЕНЬ модуля
`coding` (домен + порты). Импорт из `coding/usecases/*` или `coding/adapters/*` ЗАПРЕЩЁН
правилами `coding-boundary-no-interactive-*`; именно поэтому в срезе E общие контракты
(`CodingOutcome`, порты `OwnerCheck` / `OwnerNotifier` / `LiveRunStreamer`, разбор
stream-json, `ClaudeRunError`) переехали на общую доменную поверхность `coding`. Ребро
одностороннее: `coding` не импортирует `interactive` нигде (симметричные правила
`interactive-boundary-no-coding-*`), цикла нет. Полное обоснование — в note-блоке
«BOB-087.E: the DELIBERATE `interactive → coding` edge» в `rules.yml`.

## API

<!-- beadloom:track=src/bob/interactive/usecases/session.py -->

- `entities.py`: `LiveSession(session, runner, persistent=False)` — держатель живого
  сеанса.
- `intent.py`: `parse_interactive_entry(text)` → `str | None`;
  `parse_interactive_workspace(text)` → `tuple[str, str] | None` (workspace, задача);
  `parse_interactive_resume(text)` → `str | None`; `is_interactive_exit(text)`,
  `is_confirmation(text)`, `is_rejection(text)` → `bool`. Все распознаватели попарно не
  пересекаются.
- `resume_policy.py`: `select_resumable(sessions, *, branch)` → `CodingSession | None`;
  `is_confirmation_fresh(*, requested_at, now, ttl=CONFIRMATION_TTL)` → `bool`; константа
  `CONFIRMATION_TTL` = 5 минут.
- `resume_negotiation.py`: `ResumeNegotiation(clock=…)` — `ask(*, name, sender)`,
  `is_pending()` → `bool`, `settle(text, sender)` → `ResumeConfirmed(workspace) |
  ResumeRejected() | None`.
- `argv_policy.py`: `build_interactive_argv(claude_bin, *, mode, resume_session_id=None,
  continue_session=False, extra_dirs=(), permissions=())` → `list[str]`;
  `extract_session_id(event)` → `str | None` (только настоящий `init`-кадр с непустым
  строковым `session_id`). `permissions` — готовый хвост прав инструментов, приписывается
  последним; сама политика живёт в `tool_permissions`.
- `tool_permissions.py`: `tool_permission_argv(*, routine=False, allow_once="")` →
  `list[str]`. Запрет необратимого (`git push`, `git remote`, `git reset --hard`, `rm`,
  `gh pr merge`, `curl`, `wget`) едет в КАЖДЫЙ спавн и ключа не имеет; `routine`
  (owner-флаг `coder.pipeline_tools`, default OFF) добавляет разрешение рутины конвейера;
  `allow_once` — команда, одобренная владельцем словами: она разрешается ТОЧНЫМ текстом, а
  накрывающие её шаблоны запрета отходят на ОДИН заход. 🔴 Каждый пункт списка измерен
  живым прогоном настоящего `claude` (версия CLI записана в протоколе), включая находку «узкий `rm -rf` не ловит
  `rm -fr`» (протокол — в комментарии беады `bob-c3r.3`). Это СТРАХОВКА от нечаянного, а
  не граница: границу держит структура (клон без кредов).
- `permission_denial.py`: `DenialWatch(remember=64)` — `see(event)` →
  `PermissionDenial(tool_name, tool_use_id, command) | None`. Команда берётся из вызова,
  связанного по `tool_use_id`: поле `message` события несёт её ДАЛЕКО не всегда (у
  встроенного отказа CLI там английское «This command requires approval»), и произносить
  служебную строку внутри русской реплики Боба нельзя.
- `permission_negotiation.py`: `PermissionNegotiation(clock=…)` — `ask(*, command, sender,
  session_id)`, `is_pending()`, `settle(text, sender)` → `PermissionGranted(command,
  session_id) | PermissionRefused() | None`; `PERMISSION_TTL` = 30 минут (дольше
  пятиминутного `CONFIRMATION_TTL`: этот вопрос застаёт владельца врасплох, а работа
  стоит).
- `denial_voice.py`: `permission_question(denial)`, `permission_stuck(denial)`,
  `permission_lifted(command)`, `permission_declined()`, `permission_unreachable()` →
  `str`. Голос БОБА (канон BOB-090.D), без кнопок и слешей: разные запреты звучат разными
  словами, служебный текст CLI в реплику попасть не может по конструкции (в
  `PermissionDenial` его просто нет).
- `pipeline_prompt.py`: `permission_retry_frame(command)` → `str | None` — кадр
  возвращения после «да» владельца (`None` на пустой команде): поднятая по `--resume`
  нить сама по себе ничего не повторяет, это проверено живым прогоном.
  `pipeline_first_frame(task)` → `str | None` — постановка, которой
  начинается СВЕЖАЯ сессия (`None` на пустой задаче: додуманная моделью задача, которую
  поведёт конвейер, хуже отсутствия постановки). Живёт в домене, а не строкой в адаптере,
  ровно по доводу `argv_policy`: текст определяет поведение конвейера, значит обязан быть
  под тестом и mutation-гейтом (§0.3 п.7). Скармливает его менеджер сразу после
  `runner.open(...)` под флагом `coder.pipeline_prompt` (default OFF) — и только свежей
  сессии: у возобновлённой задача уже в контексте.
- `voice.py`: `interactive_opened()`, `interactive_busy()`, `interactive_failed()`,
  `interactive_setup_failed()`, `interactive_ended()`, `interactive_ended_persistent()`,
  `workspace_opened(workspace)`, `stopped_persistent()`, `resume_confirm(*, workspace,
  when)`, `resume_nothing(workspace)`, `resume_cancelled()`, `resumed(workspace)`,
  `resume_failed()` → `str`; плюс ре-экспорт общих `stopped()` / `no_session()` из
  `bob.coding.session_voice`.
- `usecases/session.py`: `InteractiveSessionManager` — `open(task, sender)`, `feed(text)`,
  `stop(sender)`, `active()` плюс путь долгоживущего рабочего места
  `open_workspace(name, task, sender)`, `propose_resume(name, sender)`,
  `resolve_pending_resume(text, sender)` → `CodingOutcome | None` (`None` = ход резюме не
  касается) и `resume(name, sender)`. 🔴 Плюс `resolve_pending_permission(text, sender)` →
  `CodingOutcome | None` (BOB-088 срез 3): «да» владельца на вопрос о запрете закрывает
  текущий процесс и поднимает ТУ ЖЕ нить `claude` (`--resume`) с точечным разрешением
  одной команды и кадром возвращения. Роутер обязан спрашивать этот метод ДО `feed`,
  иначе «да» уедет в stdin `claude`.
- `usecases/teardown.py`: `SessionTeardown` — `finalize(live)` → `CodingSession`,
  `hand_over(live)` → `CodingSession` (закрыть строку сеанса, НЕ трогая дерево: в него
  сейчас же возвращаются повторным заходом), `close_runner(runner)`, `cleanup(path)`.
- `usecases/intake.py`: `InteractiveIntakeRouter.route(*, text, sender, is_owner,
  is_group)` → `bool` (был ли ход поглощён).
- `usecases/recover_sessions.py`: `RecoverInteractiveSessions.run()` → `int` (сколько
  осиротевших `INTERACTIVE`-строк закрыто).
- `adapters/runner.py`: `InteractiveClaudeRunner` (`open`/`feed`/`events`/`close` +
  property `session_id`), `encode_user_message(text)` → `str`, `InteractiveRunError`.

Команды owner'а в личке: `/code -i <task>` (`/interactive <task>`),
`/workspace <name> [task]` (`/code -w`), `/resume <workspace>` (`/code -r`); выход —
`stop` / `стоп` / `/stop` / `/code stop` целым сообщением. Сборка —
`runtime/wiring/coding.py` (`_build_interactive_session` и `_build_interactive_intake` при
`coder.interactive`, с resume-швами только при `coder.resume`; `_build_interactive_recovery`
— безусловно).

## Тесты

- **Чистые ядра** — `tests/domain/interactive/test_argv_policy.py`, `test_intent.py`,
  `test_resume_policy.py`, `test_voice.py`, `test_pipeline_prompt.py`,
  `test_tool_permissions.py`, `test_permission_denial.py`, `test_permission_negotiation.py`,
  `test_denial_voice.py` (+ общая политика песочницы —
  `tests/domain/coding/test_sandbox_policy.py`). Первые модули — mutation-цели
  (`./scripts/mutation.sh interactive.argv_policy` и так далее). Ради постоянного гейта
  `build_interactive_argv` и `extract_session_id` и живут в домене, а не в адаптере:
  конвенция mutmut исключает `*/adapters/*`.
- **Use-case и адаптеры** — `tests/application/usecases/test_interactive_session.py`,
  `test_interactive_session_death.py`, `test_interactive_session_spawn_cancel.py`,
  `test_interactive_resume.py`, `test_interactive_intake.py`,
  `test_recover_interactive_sessions.py`, `tests/infrastructure/interactive/test_runner.py`,
  `test_session_death_real_subprocess.py` (конец сеанса на РЕАЛЬНОМ процессе),
  `tests/runtime/wiring/test_interactive_session_wiring.py`,
  `test_interactive_intake_wiring.py`, `test_coding_resume_wiring.py`,
  `test_coding_sandbox_relaxations.py`.
- **Приёмочный BDD** — `tests/acceptance/features/interactive_terminal.feature` и
  `interactive_resume.feature` (русскоязычный Gherkin) поверх харнессов
  `interactive_terminal_harness.py` / `interactive_resume_harness.py`, которые поднимают
  настоящий стек (`InteractiveClaudeRunner` над фейковым процессом → менеджер → интейк) и
  наблюдают только через границу: argv и cwd, отданные спавнеру, судьбу рабочего дерева,
  что ушло в личку и в stdin claude, и что список выполненных push пуст.
