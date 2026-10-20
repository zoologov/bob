<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-113 — куда переезжает каждый из 22 контрактов

> **Status:** Approved
> **Created:** 2026-10-21
> **PRD:** [PRD.md](PRD.md) (Approved)
> **Ветка:** `features/BOB-113` от `features/BOB-112`, PR в `features/BOB-112`

---

## Правило, по которому принято каждое решение ниже

Runtime-порядок вертикалей (замер BOB-112 .2, по module-level и function-level импортам):

```
usecases → capabilities → social → telegram → proactivity → memory → runtime-app → conversation → personality
   (зависит от …)                                                              (… от кого зависят)
```

Сигнатуры модуля упоминают только типы модулей **ниже** него или **`kernel`**. Отсюда три
исхода для каждого имени — в порядке предпочтения:

1. **Владельцу.** Если понятие по смыслу принадлежит модулю ниже, а объявлено выше —
   вернуть владельцу; верхний импортирует вниз.
2. **Протокол у владельца-вертикали.** Порт, который описывает хранилище/чтение одного
   контекста (`RelationshipReader` — читатель отношений), живёт в `ports.py` этого контекста.
   Потребители ниже него по порядку импортируют вниз.
3. **В `kernel`.** Значение или порт, нужный и выше, и ниже (или нужный модулю, который
   стоит **ниже** владельца — иначе импорт пойдёт вверх), переезжает в shared kernel.
   Для коллаборатора, у которого потребитель использует одно поле/метод, допустим **узкий
   Protocol у потребителя** (ISP) вместо переезда всего словаря.

`kernel` остаётся без первопартийных импортов (сейчас так; правила `kernel-no-*` в
`rules.yml` это держат).

## Решения по именам

### A. Возврат владельцу (2)

| Имя | Сейчас | Куда | Почему |
|---|---|---|---|
| `PersonalityState` (`soul: SOUL`) | `application/usecases/handle_message.py:579` | **`personality/state.py`** | Поле — `SOUL` из personality; это снимок личности. Потребители conversation / proactivity / runtime wiring импортируют вниз (personality — самый нижний модуль) |
| `EngagementState` (`fatigue: ConversationalFatigue`, `last_turn_at`) | `handle_message.py:590` | **`conversation/engagement.py`** (рядом с `ConversationalFatigue`) | Понятие conversation; единственный потребитель — `conversation/usecases/engagement_model.py` |

### B. Порты — в `ports.py` вертикали-владельца (6)

| Имя | Куда | Потребители и направление |
|---|---|---|
| `InterlocutorResolver`, `FirstImpressionReader`, `RelationshipReader`, `RosterRecaller`, `SulkReader` | **`social/ports.py`** (там уже `FirstImpressionStore`, `RelationshipStore`, `SulkStore` — читатели встают рядом с хранилищами) | `social/usecases/social_context.py` (свой модуль); `handle_message` → social (вниз) |
| `CurrentFascinationReader` | **`personality/ports.py`** (рядом с `FascinationStore`) | conversation / proactivity / personality → personality (вниз) |

Сигнатуры этих портов упоминают `Interlocutor`, `Relationship`, `RosterMember`, `SulkState`,
`MessageReceived`, `Fascination` — после разделов C/D все они либо в kernel, либо в том же
модуле, поэтому новых рёбер вверх не возникает.

### C. В `kernel` (13)

| Имя | Сейчас | Куда | Почему не владельцу |
|---|---|---|---|
| `MessageReceived`, `BobMessageReaction` (весь модуль) | `application/runtime/events.py` (без первопартийных импортов) | **`kernel/events.py`** | Событие интейка читают conversation и personality — ниже runtime-app. `kernel/ports.py` уже держит `DomainEvent`; события входят в ту же ответственность. Переезжает модуль целиком (две сущности — одна ответственность «события интейка») |
| `Recalled` (`type Recalled = Mapping[str, object]`) | `memory/entities.py` (ре-экспорт через `memory/ports.py`) | **`kernel/episode_types.py`** (там уже словарь типов эпизодов) | Читают conversation и personality — ниже memory |
| `EpisodeReader`, `MemoryRecall` | `handle_message.py:343`, `memory/ports.py:57` | **`kernel/ports.py`** | Порты чтения памяти, которыми пользуются conversation/personality (ниже memory) и proactivity (выше). Соседи — `LLMProvider`, `EventBus` |
| `ReplyGateway` | `handle_message.py:305` | **`kernel/ports.py`** | Исходящий канал (reply / photo / document / typing) — нужен application и proactivity; транспорт-нейтральный порт |
| `BobUserIdSource` | `handle_message.py:524` | **`kernel/ports.py`** | Источник собственного id — нужен conversation и runtime-app |
| `ToolDefinition`, `ToolCall`, `ToolCallResult`, `ToolCallingProvider` | `capabilities/ports.py` | **`kernel/ports.py`** (рядом с `ToolLoopMessage`, который уже там, и `LLMProvider`) | Словарь tool-calling'а LLM: его используют personality (`voice_composer`, ниже capabilities), application, infrastructure/llm. `ToolLoopMessage` уже в kernel — половина словаря переехала раньше; здесь — вторая половина |
| `RuleModulators` | `proactivity/self_improvement.py:405` | **`kernel/modulators.py`** | Результат самоулучшения, который применяют conversation (`turn_gate`, `anti_repeat_guard`) и personality (`voice_composer`) — ниже proactivity. Замороженное значение без зависимостей |

### D. Shared Kernel социальных сущностей (7)

Это единственное место, где переезд — не «вернуть на место», а признание факта: **кто
говорит с Бобом и в каких с ним отношениях** — общий словарь всего Боба. `social` остаётся
владельцем **поведения** (`apply_interaction`, `build_roster`, `observe_relationship`,
`classify`, `detect_self_gender` — всё остаётся в `social`), а **значения** уходят вниз.
Инвертировать направление (`social` → под `personality`) нельзя без правки runtime-рёбер
`social → personality` (`relationship.py` использует `Stance`, `social_context` — `voice`,
`profanity`) — это вне границ PRD.

| Имя | Сейчас | Куда | Что остаётся в social |
|---|---|---|---|
| `Interlocutor`, `InterlocutorKind`, `Trust` | `social/interlocutor.py` | **`kernel/interlocutor.py`** | `classify(...)`, `_UNKNOWN_NAME` |
| `Gender` (только Enum) | `social/gender.py` | **`kernel/interlocutor.py`** (поле `Interlocutor.gender`) | `detect_self_gender`, `GenderRead` и вся логика самоидентификации (BOB-078) |
| `Relationship` | `social/relationship.py` | **`kernel/relationship.py`** | `RelationshipDeltas`, `apply_interaction`, `compromise_bias`, `endorsed_seed`, `_drift` |
| `RosterMember` | `social/roster.py` | **`kernel/roster.py`** | `build_roster`, `is_newcomer`, `member_name` |
| `SulkState` | `social/sulk.py` | **`kernel/sulk.py`** | `SulkConfig`, `observe_relationship`, `recover` |

Потребители ниже social (conversation 15 строк, personality 8, runtime-app 1) и сам social
импортируют из kernel. **Ре-экспортов в `social/*` не оставляем**: ре-экспорт сохранил бы
путь `bob.social.interlocutor.Interlocutor`, и граф снова увидел бы ребро вверх у любого,
кто им воспользуется. Один дом — kernel.

### E. Узкий Protocol у потребителя (1)

| Имя | Сейчас | Решение |
|---|---|---|
| `WebSearchProvider` в `conversation/usecases/verify_step.py` | порт capabilities (`search(query) -> WebSearchResult`) | `verify_step` читает **одно поле** — `result.answer`. В **`conversation/ports.py`** объявляется `VerifySearch(Protocol)` с `async def search(query: str) -> HasAnswer`, где `HasAnswer(Protocol)` — `answer: str`. Адаптер capabilities удовлетворяет ему структурно, проводка не меняется. Тянуть в kernel `WebSearchResult` + `WebSource` ради одного поля — против ISP |

## Что НЕ переезжает (и почему это не полумера)

- 14 type-only рёбер **вне** компоненты (например `coding → capabilities`, `llm → kernel`,
  `interactive → identity`) направлены вниз или в kernel — они легальны по правилу и
  остаются как есть.
- Runtime-рёбра `social → telegram`, `telegram → proactivity`, `social → personality`
  зафиксированы как наблюдение (вертикаль зависит от адаптера транспорта; транспорт — от
  проактивности). Это настоящие архитектурные вопросы, но **не циклы** и не type-only —
  отдельная работа со своим замером, здесь не трогаются.

## Механика переезда

- Каждый переезд — **перенос определения + обновление всех импортов** (src и tests) на новый
  путь. Старый путь не оставляет ни шима, ни ре-экспорта (см. D).
- Документация и тесты, которые называют старый путь в тексте (`:class:` в докстрингах,
  README модулей), правятся в той же волне — иначе `sync-check`/`docs audit` честно покраснеют.
- `services.yml`: `kernel` получает `summary`, называющий новые дома (события интейка,
  социальный словарь, порты памяти/ответа/tool-calling, модуляторы); узлы social/memory/
  capabilities/proactivity — обновлённые `summary` без переехавших имён.
- `tests/test_no_runtime_import_cycles.py` дополняется проверкой: **ни один `TYPE_CHECKING`-
  импорт не направлен вверх** по объявленному порядку вертикалей (порядок — константа теста,
  выведенная из runtime-рёбер; при его изменении тест называет новое ребро). Это второй зуб
  ровно на тот класс, который этот RFC устраняет, независимый от beadloom.

## Оценка объёма

| Раздел | Файлов (src / tests, оценка по импорт-сайтам) |
|---|---|
| A | 2 модуля-владельца + ~8 потребителей + тесты handle_message/heartbeat/perceive_reaction |
| B | `social/ports.py`, `personality/ports.py`, `handle_message.py`, ~6 потребителей |
| C | `kernel/{events,ports,episode_types,modulators}.py`; `events` — 21 src + 61 tests импорт-сайтов (механически); tool-calling — `capabilities/ports.py`, `infrastructure/llm/*`, `application/*`, `runtime/wiring/*` |
| D | `kernel/{interlocutor,relationship,roster,sulk}.py`; импорт-сайты: interlocutor 26 + 39, relationship 13 + 13, roster 7 + 3, sulk 8 + 6 |
| E | `conversation/ports.py`, `verify_step.py`, `runtime/wiring/*` (тип параметра) |

Всё — механика путей; ни одна функция не меняет поведения. Риск — пропущенный импорт-сайт,
и его ловят `mypy src/ tests/` (неизвестное имя) и `ruff` (F401/F821), а не прод.

## Гейты (повторяют PRD, с механикой)

```bash
rm -f .beadloom/beadloom.db && uvx --from beadloom==9.0.0 beadloom reindex \
  && uvx --from beadloom==9.0.0 beadloom lint --strict --no-reindex      # 0, cycles на error
uv run pytest -q -rs -p no:randomly                                       # 7986+ зелёных
uv run ruff check src/ tests/ && uv run mypy src/ && uv run mypy tests/
uv run pytest -q tests/test_no_runtime_import_cycles.py                   # + саботаж
uvx --from beadloom==9.0.0 beadloom sync-check && … docs audit && … doctor
```

## Риски

- **Тесты с патчами по старому пути** (`monkeypatch.setattr("bob.social.interlocutor.X")`):
  mypy их не поймает — ловит только прогон. Поэтому полный `pytest` — на каждой волне, не в
  конце.
- **Циркулярный импорт на уровне модулей** при переезде значений в kernel: исключён
  структурно — kernel ничего не импортирует; проверяется `kernel-no-*` правилами и импортом
  `bob.kernel` в изоляции (тест).
- **`handle_message.py` (2426 строк)** — из него уходят только объявления; правка точечная,
  diff ревью читает по именам.
