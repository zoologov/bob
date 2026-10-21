<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PRD: BOB-113 — контракты сцепленных контекстов переезжают в kernel/ports (ADP без полумер)

> **Status:** Approved
> **Created:** 2026-10-21
> **Bead:** `bob-etb` (`type: feature`, P1) — срезы `bob-etb.1`–`.7`
> **Родитель по смыслу:** BOB-112 (beadloom 2.1.0 → 9.0.0) — BOB-112 не уходит в `main`, пока эта работа не вернула `lint --strict` в 0 на `severity: error`
> **Ветка:** `features/BOB-113` от `features/BOB-112`, PR в `features/BOB-112`

---

## Цель owner'а

Чтобы граф зависимостей Боба был **ациклическим по контрактам, а не только по исполнению**,
и чтобы правило `no-dependency-cycles` работало на `error` без оговорок — само, без
`exempt`, без `warn`, без «временно до релиза beadloom». Решение owner'а 2026-10-21:
**«Вариант B, без полумер. Всё максимально качественно и вдумчиво».**

## Что показал замер (BOB-112, срез .2)

beadloom с 2.2.0 читает импорты под `if TYPE_CHECKING:` и внутри функций. На нетронутом
графе Боба это дало:

- **98** производных рёбер `depends_on`, из них **30** существуют только под `TYPE_CHECKING`;
- с ними — **одна** сильно связная компонента из **9 узлов** (`capabilities`, `conversation`,
  `memory`, `personality`, `proactivity`, `runtime-app`, `social`, `telegram`, `usecases`),
  904 строки `cycle:error`; без них — **ноль** циклов;
- точный перебор: разомкнуть компоненту можно только убрав **16 из 20** type-only рёбер
  внутри неё — это **50 импорт-строк** в ~25 файлах;
- по runtime-рёбрам у вертикалей есть **естественный порядок** (depends-on → … →
  depended-upon):
  `usecases → capabilities → social → telegram → proactivity → memory → runtime-app → conversation → personality`,
  и **все 16** рёбер — **обратные** ему: нижний модуль упоминает в сигнатурах тип верхнего.

Что именно упоминается (22 имени, 7 модулей-источников):

| Источник | Имена | Кто ссылается снизу |
|---|---|---|
| `application/usecases/handle_message.py` | порты-читатели `BobUserIdSource`, `CurrentFascinationReader`, `EpisodeReader`, `FirstImpressionReader`, `InterlocutorResolver`, `RelationshipReader`, `ReplyGateway`, `RosterRecaller`, `SulkReader`; значения `PersonalityState`, `EngagementState` | conversation, personality, proactivity, social, runtime-app (12 строк) |
| `social/{interlocutor,relationship,roster,sulk}.py` | `Interlocutor`, `InterlocutorKind`, `Relationship`, `RosterMember`, `SulkState` | conversation (15), personality (8), runtime-app (1) |
| `memory/ports.py` | `Recalled`, `MemoryRecall` | conversation, personality (6) |
| `capabilities/ports.py` | `ToolCallingProvider`, `WebSearchProvider` | conversation, personality (2) |
| `application/runtime/events.py` | `MessageReceived` | conversation, personality (3) |
| `proactivity/self_improvement.py` | `RuleModulators` | conversation, personality (3) |

## Почему это дефект, а не «шум инструмента»

Связь по контракту — всё равно связь. Если `personality` аннотирует себя типом
`PersonalityState`, объявленным в application-use-case, то изменить этот тип нельзя, не
трогая оба конца; если `conversation` описывает свои входы сущностями `social`, а `social`
ходит в `personality`, которая ходит в `conversation`, — три контекста меняются вместе.
Исполнение (runtime-импорты) этого не показывает, потому что Python позволяет отложить
импорт под `TYPE_CHECKING`; граф контрактов — показывает. Это ровно **ADP** (Acyclic
Dependencies Principle, Р. Мартин) применительно к типам, а наш «kernel» — **Shared Kernel**
из карты контекстов DDD (Эванс): место для понятий, общих нескольким контекстам.

## Принцип размещения (единое правило для всех 50 строк)

> Сигнатуры модуля упоминают только типы **модулей ниже него** в runtime-порядке или
> **`kernel`**. Если значение нужно и сверху и снизу — оно переезжает в **`kernel`**
> (shared kernel). Если нужен **коллаборатор** (кто-то, кого вызывают) — потребитель
> объявляет **свой узкий `Protocol` в своём `ports.py`** (ISP + DIP), а верхний модуль
> просто ему соответствует. Тип, который по смыслу принадлежит нижнему модулю, но объявлен
> выше (`PersonalityState` в application) — **возвращается владельцу**.

Три класса переездов, вытекающие из таблицы (точные решения по каждому имени — в RFC):

1. **Владельцу.** `PersonalityState` → `personality`, `EngagementState` → `conversation`:
   это их собственные понятия, application их лишь собирает.
2. **В kernel.** Общие значения и события: `MessageReceived`, сущности social
   (`Interlocutor`, `InterlocutorKind`, `Relationship`, `RosterMember`, `SulkState`),
   `Recalled`, `RuleModulators` — если RFC подтвердит, что это значения, а не поведение.
3. **Protocol у потребителя.** Порты-читатели из `handle_message` и порты `memory`/
   `capabilities` (`MemoryRecall`, `ToolCallingProvider`, `WebSearchProvider`): каждый
   потребитель объявляет ровно то, что вызывает.

## Инварианты

- **Поведение Боба не меняется.** Это чистый рефакторинг размещения: ни один тест поведения
  не переписывается ради прохождения; меняются только пути импорта и место объявления.
  7986 зелёных остаются зелёными.
- **Никаких полумер.** В `rules.yml` не появляется `exempt`/`warn`/`suppress` для циклов;
  `no-dependency-cycles` остаётся `severity: error` и возвращается в 0.
- **`kernel` не импортирует ничего из модулей** (как сейчас) — переезжающие в него значения
  не тащат за собой зависимостей.
- **Порядок вертикалей не «узаконивается» слоями** — вертикали по-прежнему вне
  `architecture-layers`; ациклическость держит `no-dependency-cycles` (beadloom) и
  `tests/test_no_runtime_import_cycles.py` (второй, независимый зуб).
- **`TYPE_CHECKING`-импорты не запрещаются** — они легальны, когда направлены вниз или в
  kernel. Запрещено только направление против порядка.

## Границы

- Не трогаем runtime-рёбра и их направление (в т.ч. `social → telegram`, `telegram →
  proactivity` — замечено, зафиксировано как наблюдение для отдельной работы, здесь не
  правится).
- Не меняем публичные интерфейсы адаптеров/транспорта; не меняем конфиг и данные.
- Не переписываем `handle_message.py` (2426 строк) целиком — из него уходят только порты и
  два значения; остальное — как было.
- Не делаем «заодно» обновление зависимостей (отдельный chore) и не трогаем срезы `.3`–`.5`
  BOB-112.

## Критерии приёмки

- [ ] `rm -f .beadloom/beadloom.db && uvx --from beadloom==9.0.0 beadloom reindex && … lint --strict` → **0 нарушений** при `no-dependency-cycles: severity: error`; число производных рёбер и число type-only рёбер — в ACTIVE (до/после).
- [ ] `tests/test_no_runtime_import_cycles.py` зелёный; кусачесть повторно доказана саботажем.
- [ ] Полный `pytest`, `ruff check src/ tests/`, `mypy src/ tests/` — зелёные; ни один тест поведения не ослаблен (ревью сверяет diff тестов: только пути импорта).
- [ ] `kernel` импортирует только stdlib/typing (проверяется тестом или forbid_import-правилом `kernel-no-*`, которое уже есть).
- [ ] Каждое из 22 имён имеет в RFC записанное решение (владельцу / kernel / Protocol у потребителя) и это решение реализовано — ни одного «временно оставил».
- [ ] Доки модулей (`docs/domains/*/README.md`, `kernel`) и `services.yml` отражают новое место контрактов; `sync-check` 0, `docs audit` 0.
- [ ] Mutation: тронутые чистые ядра (если RFC затронет логику, а не только размещение) — числа мутантов и триаж в ACTIVE.
- [ ] PR в `features/BOB-112` зелёный по CI; после мёржа BOB-112 .2 закрывается.
