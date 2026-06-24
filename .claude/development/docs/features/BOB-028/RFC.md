<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-028 — «T2.2 Self-Improvement: метакогнитивное обучение на паттернах»

> **Status:** Approved
> **Created:** 2026-06-24

---

## Обзор

Над эстетической эволюцией (вкус/fascination/phantom) появляется **метакогнитивный слой**: Боб
периодически анализирует свою историю общения + сигналы трения, **детектит поведенческие паттерны**,
формирует человекочитаемое **правило-стратегию** (`ImprovementRule`: наблюдение + поправка +
**рычаг из жёсткого allowlist** + ограниченная величина), **предлагает owner** (вариант A,
authz-before-autonomy, реюз апрув-паттерна Goal Engine) и по апруву применяет как **мягкий
обратимый модулятор** в существующих точках поведения. Рычаги — фиксированный набор
(тон/длина/проактивность/адресность/юмор) и **только**: authz / гость-инвариант / ядро SOUL /
safety-инварианты автономии **не представимы** правилом по конструкции. Мастер-выключатель OFF.

## Технический контекст

### Ограничения
- Python 3.12+, DDD/Clean: модель правила + машина состояний + выбор активных — **чистый домен**
  (без I/O, детерминированно); детектор/LLM/persist за портами; композиция в `app.py`; инъекция
  Clock/RNG/портов. **TDD на фейках через `.venv/bin/pytest`** (uv run висит), `mypy --strict`,
  `ruff`, cov >=80%.
- Не ломать: Тир 1 (личность), эстетическая эволюция (BOB-013/020/021), governance, автономность
  (BOB-015), capability-шов, authz/гость-инвариант. **Правила НИКОГДА не трогают границу безопасности.**

### Реюз существующей машинерии
- **ReflectTick** (`heartbeat.py`, грундированная рефлексия BOB-026) — драйвер детектора (узкий
  опциональный seam-Protocol, как fascination/phantom/consolidation; unwired → поведение как раньше).
- **Апрув-паттерн Goal Engine** (BOB-015): машина состояний + owner-команды + persist-стор — образец.
- **Точки мягкого применения:** `voice.*_directive` (тон/юмор), BOB-024 verbosity (длина), BOB-010
  urge/governance (проактивность), BOB-023/025 пороги (адресность-байес).
- Persistence-паттерн `XxxStore`; signals из эпизодов + relationship/engagement/mood.

### Затрагиваемые области
`domain/personality/self_improvement.py` (new — правило/рычаги/машина/выбор), `domain/ports.py`
(+`SelfImprovementStore`, +`PatternDetector`), `infrastructure/persistence/` (+Sqlite-стор),
`application/usecases/` (+`detect_patterns`, +`manage_rules`), `heartbeat.py` (детектор-seam),
`handle_message.py` / `voice.py` (применение модуляторов), `infrastructure/telegram/guppi.py`
(owner-команды), `app.py`, `config`.

---

## Предлагаемое решение

### (1) Модель правила — чистый домен (`self_improvement.py`)
- **`Lever`** (Enum — ЖЁСТКИЙ ALLOWLIST): `TONE`, `LENGTH`, `PROACTIVITY`, `ADDRESSIVITY_BIAS`,
  `HUMOR`. **И только.** Нет члена для authz/гостя/SOUL/safety → правило их не представит.
- **`RuleState`** (Enum, машина): `PROPOSED` → `APPROVED` → (`PAUSED` ↔) ; `PROPOSED` → `REJECTED`;
  `APPROVED`/`PAUSED` → `REMOVED`. **Переход в APPROVED только owner-апрувом (use-case).**
- **`ImprovementRule`** (`frozen, slots`): `id`, `observation: str` (рус, человекочитаемо), `adjustment:
  str`, `lever: Lever`, `magnitude: float` (в `[0, max_magnitude]` — мягкий наклон), `state`,
  `origin` (BOB_PROPOSED), `created_at`, `evidence: str` (какие паттерны сработали).
- Чистые: `active_rules(rules) -> tuple[ImprovementRule, ...]` (только APPROVED не-PAUSED),
  `can_transition(frm, to)`, `clamp_magnitude(value, *, cap)`. Юнит-тесты на все ветки.

### (2) Детектор паттернов (порт + impl, driven by ReflectTick)
- **`PatternDetector(Protocol)`**: `async detect(signals: ImprovementSignals) -> Sequence[ImprovementRule]`
  (кандидаты в `PROPOSED`). `ImprovementSignals` — структурированный срез: самоповторы (BOB-026),
  исходы адресности (SILENT/REACT/ENGAGE), verbosity-vs-demand промахи (BOB-024), дельты отношений
  (BOB-014), застревание настроения (valence/arousal залип надолго), поправки/трение owner'а
  (повтор вопроса, «почему»), что зашло (позитивные дельты). **Полный набор** (стабильный диалог
  только зарождается).
- **Impl** через Tier-1 LLM: из сигналов + эпизодов формулирует человечное правило (observation/
  adjustment) и **выбирает рычаг из Lever** (строгий JSON, как memory-extraction). Тест — фейк-детектор.
- **`detect_patterns` use-case**, вызывается из ReflectTick-seam (редкий кадэнс): собрать сигналы →
  `detect` → дедуп против существующих правил → сохранить кандидатов в `PROPOSED`. Никакого
  применения здесь.

### (3) Предложил → апрув (реюз паттерна Goal Engine)
- Боб **проговаривает** свежее правило owner'у (через проактивный канал / при случае): «Заметил за
  собой X. Предлагаю Y — включить?». Owner решает.
- **Owner-команды GUPPI** (owner-only в General, как `/goals`): `/rules` (список+состояния), `/rule
  approve <id>`, `/rule reject <id>`, `/rule pause|resume <id>`, `/rule remove <id>`, опц. `/rule
  edit <id> <текст>`. `PROPOSED→APPROVED` только так. Гость/не-owner — не управляют.

### (4) Мягкое применение (модуляторы в allowlist-точках)
- `active_rules` → набор модуляторов, каждый **по своему рычагу** в СВОЮ точку:
  - `TONE`/`HUMOR` → дополнительная `voice`-директива в `_system_prompt_for` (мягкий наклон тона/юмора).
  - `LENGTH` → байес к `decide_verbosity` (BOB-024) на ±magnitude (ограниченно).
  - `PROACTIVITY` → байес к urge/governance (BOB-010).
  - `ADDRESSIVITY_BIAS` → байес к порогам BOB-023/025 (мягко).
- **Жёстко:** применение читает ТОЛЬКО `Lever`-allowlist; величина клампится; это **наклон, а не
  перехват** (никогда не зануляет/инвертирует базовое поведение). Нет рычага — нет применения.

### (5) Persistence + конфиг
- **`SelfImprovementStore`** (порт) + `SqliteSelfImprovementStore` (таблица `improvement_rule`).
- Конфиг `self_improvement.*`: **`enabled` (OFF по умолчанию)** — мастер-выключатель; `detect_cadence`,
  `max_magnitude` (потолок наклона), `max_active_rules` (предел числа активных), tier детектора.

### Композиция / безопасность (инварианты)
```
ReflectTick → detect_patterns (сигналы → кандидаты PROPOSED) → Боб предлагает owner →
  /rule approve → APPROVED → active_rules → мягкие модуляторы в allowlist-точках
```
Гость-инвариант (BOB-019) и authz целы (команды только owner; правила не трогают authz/гостя). Ядро
SOUL и safety-инварианты автономии (BOB-015) недостижимы (нет соответствующего `Lever`). Эстетическая
эволюция и Тир 1 не затронуты — модуляторы аддитивны.

## Guardrails (под тестами)
- **Authz-before-autonomy:** ни одно правило не применяется без owner-апрува; детектор только
  предлагает (`PROPOSED`); `active_rules` берёт лишь APPROVED-не-PAUSED.
- **Граница безопасности по конструкции:** `Lever` не содержит authz/гость/SOUL/safety → правило их
  не представит; применение читает только allowlist. **Defense-in-depth:** домен (нет рычага) +
  применение (только allowlist).
- **Ограниченность:** `magnitude` клампится (`max_magnitude`); модулятор — наклон, не перехват;
  `max_active_rules` ограничивает суммарный дрейф.
- **Обратимость/прозрачность:** owner видит `/rules`, паузит/удаляет; Боб проговаривает наблюдение
  и поправку.
- **OFF по умолчанию:** `self_improvement.enabled=false` → детектор не запущен, правил нет, поведение
  ровно как до BOB-028.
- Чистый домен/детерминизм; детектор seeded/фейкаемый.

## Рассмотренные альтернативы
- **Авто-применение без апрува** — отвергнуто (PRD, вариант A): нарушает authz-before-autonomy;
  риск дрейфа/подхалимства. Ослабление — позже, отдельно.
- **Свободная форма правила (произвольный «модулятор»)** — отвергнуто: правило могло бы тронуть что
  угодно; жёсткий `Lever`-allowlist делает границу безопасности конструктивной, а не «по тестам».
- **RL/онлайн-дообучение модели** — отвергнуто: цена/непредсказуемость/необратимость; берём
  символьные правила-наклоны поверх существующих знобов.
- **Правило меняет mood/SOUL напрямую** — отвергнуто: ядро/состояние не рычаг; правило лишь
  наклоняет ПОВЕДЕНИЕ (тон/длина/проактивность/адресность/юмор).

## Риски
| Риск | Вер. | Влияние | Митигация |
|---|---|---|---|
| Правило ослабляет безопасность | Low | **High** | `Lever`-allowlist (нет рычага для authz/гостя/SOUL/safety) + apply читает только allowlist; тесты |
| Боб «учит» плохое (подхалимство/дрейф) | Med | Med | Owner-апрув-гейт (всё курирует owner); ограниченная величина; max_active_rules; pause/remove |
| Дрейф личности от множества наклонов | Med | Med | `max_active_rules` + клампы; модуляторы аддитивно-ограничены; обратимость |
| Шумный детектор (мусорные правила) | Med | Low | Дедуп против существующих; owner отклоняет; OFF по умолчанию |
| Конфликт модуляторов между собой | Low | Low | По одному рычагу → одна точка; суммарный наклон клампится |

## Открытые вопросы
| # | Вопрос | Предложение |
|---|--------|-------------|
| Q1 | Канал, где Боб проговаривает предложение | Реюз проактивного канала (BOB-010) при governance-окне; иначе при ближайшем релевантном ходе |
| Q2 | Как Боб «замечает» застрявшее настроение | Сигнал из mood_history: valence/arousal вне окна базлайна дольше порога → кандидат-правило (lever PROACTIVITY/TONE) |
| Q3 | Дедуп похожих правил | По (lever + близость observation), как анти-повтор BOB-026 |
| Q4 | Стартовый `max_magnitude` / `max_active_rules` | Консервативно (малый наклон, ≤3-5 активных), тюнится конфигом |
