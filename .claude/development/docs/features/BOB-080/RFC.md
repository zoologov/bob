> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-01
> **Issue:** BOB-080

# RFC — Ростер комнаты: припоминание состава по социальному поводу

## Резюме решения

Данные уже есть (`first_impression`: sender_id, `first_seen_at`, note) — не хватает **retrieval-пути** и
**мульти-персонного рендера в промпт**. Вводим: (1) recency-запрос к стору впечатлений (первый в коде,
где нет `WHERE sender_id=?`), (2) чистое доменное ядро `social/roster.py` (новизна по времени, отбор,
исключение владельца), (3) usecase, собирающий ростер, (4) компактную мульти-персонную voice-директиву.

🔴 **Ключевое дизайн-решение (north star, не скриптовость):** surfacing — не хрупкий детектор
ключевых слов «новенькие/ребята», а **ambient-осознание с окном**. Пока есть недавно зашедшие (в окне
`newcomer_days`), компактная строка ростера присутствует в контексте (как человек держит свежих
знакомых «в голове» несколько дней и упоминает по поводу). Директива: «называй по поводу о людях/
составе, без повода не притягивай» → INV-4. Нет окна недавних → ростер пуст → строки нет. Не зависит от
слов входящего сообщения (INV-2). За флагом `social.roster`.

## Разведанные seam-точки (авторитетно)

- **DATA-дыра:** во всём коде запросы к обеим person-таблицам ТОЛЬКО точечные (`WHERE sender_id=?`;
  `first_impression_store.py:53`, `relationship_store.py:55/129`). `first_seen_at` есть, но по нему
  никогда не запрашивают. Ростер-по-давности — новый метод стора.
- **READ-дыра:** `who_is_writing_directive` (`voice.py:242`) и вся сборка директив рендерят ТОЛЬКО
  текущего одного собеседника; мульти-персонного рендера нет. Точка вставки — список `directives`
  (`voice_composer.py:408-446`).
- **«Новичок» сегодня** = authz-kind GUEST (`room_stream_reader.py:157`→`perceive_kind`), НЕ давность —
  ортогонально нашему time-based «недавно зашёл».
- Стор впечатлений + relationship строятся рядом (`composition.py:442-451`, общий connection),
  инъектятся в `SocialContext` (`:696/:701`). Туда сядет ростер-usecase.
- Per-turn сборка соц-контекста: `handle_message.py:1351/1356` → `_system_prompt_for` (`voice_composer.py:377`).

## DATA (первый recency-запрос + имя)

**`social/adapters/first_impression_store.py`** — новый метод + порт (`social/ports.py:96`):
```python
async def recent(self, *, limit: int) -> list[FirstImpression]:
    # SELECT sender_id, first_seen_at, note[, display_name]
    # FROM first_impression ORDER BY first_seen_at DESC LIMIT ?
```
**Имя участника.** Сущность `FirstImpression(sender_id, first_seen_at, note)` имя хранит только внутри
`note` («{name} — …», формат `impression_note_for` `first_impression.py:46`). Добавляем **guarded ALTER**
колонку `display_name` в `first_impression`, заполняем в `note_first_contact`
(`first_impression_sources.py:64` — там `interlocutor.display_name` в руках). Legacy-строки: имя парсим
из note (split по « — ») как fallback. Владельца из ростера исключаем (он known, не «новичок»).

## ДОМЕН (чистое ядро — mutation-цель)

**`social/roster.py`** (layer=domain, I/O-free):
```python
@dataclass(frozen=True, slots=True)
class RosterMember:
    sender_id: int
    name: str
    first_seen_at: datetime
    is_newcomer: bool

def is_newcomer(first_seen: datetime, now: datetime, *, newcomer_days: float) -> bool: ...

def build_roster(
    impressions: Sequence[FirstImpression], now: datetime, *,
    newcomer_days: float, exclude_ids: frozenset[int], limit: int,
) -> tuple[RosterMember, ...]:
    # исключить exclude_ids (владелец/сам Боб); отметить is_newcomer по времени;
    # отсортировать по first_seen_at DESC; вернуть ≤limit. Имя из display_name|parse(note).
```
Инвариант ядра: `is_newcomer` строго по времени (INV-3); ростер — только из переданных реальных
впечатлений (INV-1); детерминированный порядок. Чистое, без БД/Clock (now — параметр) → TDD + mutation ≥85%.

## USECASE + приватность

**`social/usecases/roster_recall.py`** — `RosterRecall.recent_roster(now, *, viewer: Interlocutor)`:
- Читает `store.recent(limit=cap)` → `build_roster(..., exclude_ids={owner_id, bob_id})`.
- **Ambient-окно:** возвращает ростер, ТОЛЬКО если в нём есть хоть один `is_newcomer` (свежие есть →
  держим в голове); иначе пусто (нет флуда, INV-4).
- **Приватность:** ростер отдаётся, только если `viewer.kind ∈ {OWNER, KNOWN}` — гостю не вручаем
  перечень всех (уважение trust, scope §PRD). Не расширяет authz.
- best-effort: ошибка чтения → пустой ростер, ход продолжается (урок Part D [[bob-078-dialogue-quality]]).

Экспонируется через `SocialContext` (новый метод, параллельно `recall_prior_impression`
`social_context.py:96`), собирается в `handle_message` рядом с `prior_impression`/`relationship`
(`:1351-1356`) и прокидывается в `_system_prompt_for`.

## READ (мульти-персонная директива)

**`personality/voice.py`** — `roster_directive(roster: Sequence[RosterMember]) -> str` (рядом с
`recalled_impression_directive:363`): компактно, напр.
«Недавно к вам в чат зашли: Лиля, Паша. Ты с ними уже знаком(а). Если речь зайдёт о людях/составе —
называй их сам, по имени; без повода в разговор не притягивай.» Пустой ростер → "".
Вкладывается в `directives` (`voice_composer.py:408`) при непустом ростере. Пред-сформулировано, тяжёлого
рендера не нужно.

## Флаг

`social.roster` (bool, default OFF в коде → ON в running-config после ревью, образец
`presence.stream_read` [[bob-072-stream-read]]). Пороги: `social.roster.newcomer_days` (default 7),
`social.roster.limit` (default ~6). OFF → usecase не строится/возвращает пусто (ноль изменений поведения).

## Границы (как в PRD)

Без live-членства Telegram (строим из накопленных впечатлений), без переписи engagement BOB-078 (S3
опирается: ростер даёт `is_newcomer`), без authz-изменений, без проактивного «первым к новичку».

## Инварианты → реализация

- INV-1 реальные встречи → ростер только из строк `first_impression`.
- INV-2 припоминание по поводу без имён → ростер в контексте по ambient-окну, НЕ по FTS-матчу текста.
- INV-3 новизна по времени → `is_newcomer(first_seen, now, newcomer_days)`, настраиваемо.
- INV-4 точечность → ambient-окно (пусто без свежих) + директива «по поводу, не притягивай» + приватность
  owner/known + компактность.

## Риски и меры

- **Over-mention** (Боб талдычит про новичков) → директива-framing «по поводу»; окно `newcomer_days`
  ограничивает срок; компактная строка; при желании ужать порог. Живой смоук проверит тон.
- **Имя из note для legacy** → парс « — »-fallback покрыт тестом; новые строки — колонка display_name.
- **Приватность** → ростер только owner/known; гостю не выдаётся; authz нетронут.
- **Чтение роняет ход** → best-effort (пустой ростер на ошибке).
- **Скриптовость** → сознательно НЕ keyword-детектор; ambient-окно + семантическое суждение LLM по
  директиве, кого и когда упомянуть.

## Тест-стратегия

- **Unit/TDD:** `is_newcomer` (порог, границы), `build_roster` (исключение владельца, порядок DESC,
  limit, флаг новичка, пустой при отсутствии свежих), парс имени из note (fallback) + display_name,
  recency-запрос стора. **mutation ≥85%** на `roster.py`.
- **Usecase:** ambient-окно (нет свежих → пусто), приватность (гость → пусто), best-effort.
- **BDD `.feature`** (`tests/acceptance/`, через границу): S1 ростер всплывает по соц-поводу без имён,
  S2 новички vs старожилы (Norman/Алексей не как «новые»), S4 без свежих → не выдумывает.
- **Живой смоук:** «как тебе новенькие?» → Боб называет недавних сам; на пустом ростере — «новеньких не
  припомню».
