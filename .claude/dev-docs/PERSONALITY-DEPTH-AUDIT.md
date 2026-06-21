<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1
     See the LICENSE file in the project root for full license information. -->

# Аудит глубины личности Боба (Higher Mind): замысел vs реализация

- Автор аудита: ассистент-агент
- Дата: 2026-06-21
- Метод: сверка `archive/PRD.md` + `archive/RFC.md` + `VISION.md` (§4, §4.1) против реального кода
  (`src/bob/domain/personality/`, `src/bob/domain/proactivity/`, `src/bob/application/usecases/`,
  `src/bob/application/proactivity/`, `src/bob/app.py`).
- Принцип: честно, по доказательствам (`файл:строка`). Цель — найти, где личность это **структура,
  которую никто не потребляет**, а где она реально управляет поведением.

> **Главный вывод одной строкой.** Настроение (Mood) — реально живой, замкнутый контур (вход→состояние→
> тон ответа→проактивность→дрейф). Всё остальное в Higher Mind — либо «читается, но не пишется»
> (Taste, Genesis-облик личности), либо **построено и не подключено вообще** (Negotiation). Само-эволюции
> нет: рефлексия пишет только в эпизодический лог и никогда не обновляет вкусы/убеждённость/душу/baseline.

---

## 1. Скоркарта по компонентам Higher Mind

| Компонент | Замысел (источник) | Построено? (`файл:строка`) | Подключено в поведение? (потребитель) | Глубина |
|-----------|--------------------|----------------------------|----------------------------------------|---------|
| **Mood System** | Настроение (valence/arousal/openness/social/stability) красит тон, готовность экспериментировать; кормится текстовыми сигналами; дрейфует к baseline (VISION §4; PRD §3.2.2) | `domain/personality/mood.py:74-132` (`Mood`, `update`, `drift_toward`, `tone`) | ДА. Вход: `usecases/update_mood_from_text.py:79-87`. В промпт: `handle_message.py:313-316` (`Mood tone: …`). Проактив: `domain/proactivity/urge.py:81-88` (`_mood_drive`). Дрейф: `heartbeat.py:111-121`. Монолог→настроение: `heartbeat.py:93-108` | **DEEP** — единственный замкнутый контур: воспринимается, хранится, красит ответ, гонит проактив, дрейфует. |
| **Taste / conviction** | Вектор вкусов с убеждённостью влияет на **сам характер ответов** (стих/картинку Боб отдаёт через вкус); вкусы эволюционируют (VISION §4; PRD §3.2.2; RFC §3.3 `TasteEvolution`) | `domain/personality/taste.py:48-107` (`TasteAxis`, `TasteEngine.score`→`Verdict`) | ЧАСТИЧНО. Один потребитель: `handle_message.py:311-316` кладёт `score(topic).value` в промпт. **Эволюции нет**: `experience_count` нигде не инкрементируется, conviction не растёт, axes не пишутся обратно после Genesis. `apply_reflection`/`reinforce` из RFC §3.3 (1480-1538) не реализованы. | **SHALLOW** — вердикт читается в промпт, но это «снимок из рождения»; вкусы статичны на весь boot. |
| **Negotiation / отстаивание позиции** | Боб не слуга: 3 зоны (личное/общее/зона юзера), conviction решает, где он стоит на своём; работает и в чисто текстовом взаимодействии (VISION §4; PRD §3.2.2; RFC §3.3.7) | `domain/personality/negotiation.py:56-74` (`Negotiation.decide`→`Stance`) | **НЕТ ПОТРЕБИТЕЛЯ.** `Negotiation`/`Stance` упомянуты только в `domain/personality/__init__.py` (ре-экспорт) и `tests/domain/personality/test_negotiation.py`. В `handle_message.py`, `app.py`, проактиве — ни одной ссылки. | **STRUCTURE-ONLY** — чистая, оттестированная функция, которую никто не вызывает. |
| **Inner monologue** | Фоновый поток мыслей (Tier 0) питает настроение и рефлексию (VISION §4) | `usecases/heartbeat.py:79-108` (`InnerMonologueTick`) | ДА (частично). Тик генерит мысль, классифицирует сентимент, нудит valence: `heartbeat.py:106-107`. Запущен: `app.py:321-323`, `app.py:621-625`. **Но**: сама мысль нигде не сохраняется (только дельта настроения) — её нельзя вспомнить/процитировать. | **MODERATE** — реально влияет на mood, но «мысль» эфемерна (не пишется в память). |
| **Reflection → self-improvement** | Периодическая оценка действий, **эволюция вкусов**, правила; рефлексия — сильнейший драйвер настроения (VISION §4; RFC §3.3.3-3.3.4; RFC §3.3.6 `update_from_reflection`) | `usecases/heartbeat.py:124-163` (`ReflectTick`) | ЧАСТИЧНО. Тик пишет текст рефлексии в эпизод: `heartbeat.py:155-163` (`save_episode`). Salience рефлексии кормит проактив: `engine.py:222-234`+`urge.py`, причём salience реальна
(не заглушка): `infrastructure/persistence/proactivity_sources.py:78-89` берёт timestamp последнего
эпизода-«reflection» и линейно затухает за 6 ч. **Но**: рефлексия НЕ обновляет mood (нет `update_from_reflection`), НЕ трогает вкусы/conviction, НЕ генерит правила, НЕ двигает baseline. Единственный приёмник записи — `save_episode`. | **SHALLOW** — «рефлексия» = одно предложение в лог + слабый сигнал salience; не меняет личность. |
| **Memory** | Эпизодическая + семантическая (факты) + структурированное состояние; переживает рестарты (VISION §4) | Эпизоды/факты: `handle_message.py:275-294`, `extract_facts.py`; recall в промпт: `handle_message.py:319-324`; гибрид FTS5+вектор: `app.py:261` (`HybridMemoryRecall`) | ДА. Реактивный turn пишет эпизод+факты и вспоминает в промпт; проактив тоже пишет (`engine.py:302-323`) и грунтуется на recall (`engine.py:200,268-296`). | **DEEP** — реально замкнуто: пишется, вспоминается, влияет на ответ и на проактив. (Единственный по-настоящему богатый слой наряду с Mood.) |
| **Genesis (текстовый)** | Первый запуск как «пробуждение»: Боб генерит личность/настроение/вкусы из `bob-soul/`, пишет SOUL (VISION §4; PRD §5.1; RFC §"Genesis") | `usecases/run_genesis.py:91-160` (генерит traits/taste/mood/phantom/нарратив, пишет SOUL.md+JSON) | ДА (однократно). Запуск на первом boot: `app.py:192`. Идемпотентно: `run_genesis.py:114-119`. Загрузка в живой SOUL: `app.py:651-671` (`_load_soul`). | **MODERATE** — рождение богатое и реальное, но это разовый акт; «awakening phase 48h» с imprinting (PRD §5.1) НЕ реализован. |
| **Самосознание + фантомные предпочтения** | Боб знает о книге, шутит, «помнит» кофе/закаты/запах книг (VISION §4; PRD §1) | `domain/personality/soul.py:27-39` (`phantom_prefs`); генерятся в Genesis: `run_genesis.py:213-216` | ЧАСТИЧНО. Identity+phantom_prefs кладутся в промпт: `handle_message.py:312-318`. Genesis-промпт требует self-aware нарратив про книгу: `run_genesis.py:68-80`. **Но**: phantom_prefs — статичный список строк в промпте; эволюции (затухают/крепнут/превращаются в вкус — PRD §5.3) нет. | **SHALLOW** — присутствует как строка-инъекция; ни триггеров «фантомного момента», ни эволюции. |
| **Relationship / эмоции в две стороны** | RelationshipTracker (trust/respect/warmth) влияет на тон и готовность уступать; Exodus Mode (PRD §3.2.2). VISION Фаза 3: близость растёт со временем, твоё тепло/холод/отсутствие двигают **его** настроение, off-days, «не знаю», текущее увлечение (VISION §4.1) | — | **НЕ ПОСТРОЕНО.** Нет ни `relationship`-домена, ни trust/closeness. Частично: «отсутствие» юзера двигает social через presence-сигнал (`update_mood_from_text.py:114-116`) и longing в urge (`urge.py:91-93`) — но это про настроение/проактив, не про модель отношений. Off-days/«не знаю»/увлечение — отсутствуют. | **MISSING** — Фаза 3 VISION целиком впереди. |
| **Opinion formation / несогласие** | Несогласие приходит из `Negotiation`/`Taste`; «не yes-man» (VISION §4.1 анти-цели) | Сырьё есть (`taste.score`, `Negotiation.decide`), но… | **НЕТ.** Несогласие не собирается ни в один промпт как директива «held stance». В `_SYSTEM_PROMPT` (`handle_message.py:79-82`) — «warmly and concisely», без указания отстаивать позицию. Taste-вердикт передаётся как факт, без инструкции «спорь, если HATE». | **STRUCTURE-ONLY → почти MISSING** — анти-цель «yes-man» структурно не закрыта в reply-пути. |
| **Proactivity (drive-модель)** | VISION Фаза 1 ✅: Боб пишет первым по порыву из состояния, стохастически, под governance | `domain/proactivity/*` (urge/decision/governance/social_energy/state) + `application/proactivity/engine.py` | ДА. Полностью замкнуто: mood+silence+salience+circadian+energy→urge→p→seeded draw→veto→Tier0-gate→compose→post→persist. Запущено: `app.py:333-345,636-640`. | **DEEP** — самая зрелая часть после Mood/Memory; порыв реально рождается из состояния. |
| **Language directive** | Само-генерируемый текст пинится на язык персоны (BOB-012) | `domain/personality/language.py:38-48` | ДА. Используется в монологе/рефлексии (`heartbeat.py:64-70`) и проактиве (`engine.py:298-300`). | **DEEP** (узкая фича, но полностью подключена). |

### Свод (компактно)

| Компонент | Глубина | Подключён? |
|-----------|---------|------------|
| Mood | DEEP | да |
| Memory | DEEP | да |
| Proactivity | DEEP | да |
| Language | DEEP | да |
| Inner monologue | MODERATE | да |
| Genesis | MODERATE | однократно |
| Taste/conviction | SHALLOW | читается |
| Reflection→self-improve | SHALLOW | лог-only |
| Phantom prefs | SHALLOW | строка |
| Negotiation | STRUCTURE-ONLY | нет |
| Opinion/несогласие | STRUCTURE-ONLY | нет |
| Relationship/эмоции-2way | MISSING | нет |

---

## 2. Два известных провала (с доказательствами и швом для починки)

### (a) Negotiation Engine не подключён к генерации ответа

**Доказательство отсутствия потребителя.** `Negotiation.decide(...)` определён в
`domain/personality/negotiation.py:56-74`. Поиск по `src/` даёт ссылки **только** в
`domain/personality/__init__.py` (ре-экспорт, строки 19-33) — нигде в `application/`, ни в `app.py`.
Тесты — только `tests/domain/personality/test_negotiation.py` (изоляция). Интеграционного теста, где
Negotiation влияет на ответ, нет.

**Где именно должен врезаться шов (но не врезается).** Reply собирается в
`handle_message.py:_decide` (`224-260`) и `_assemble_shareable_context` (`297-325`). Сейчас туда
кладётся `Taste verdict` (строка 311-316), но НЕ стойка переговоров. Системный промпт
`handle_message.py:79-82` вообще не упоминает отстаивание позиции. То есть на пути ответа есть и зона
(неявно), и conviction (в `TasteAxis`), и mood-модификатор (RFC §3.3.7 п.3) — но никто не вызывает
`Negotiation.decide`, и `Stance` не превращается в директиву для LLM.

**Эскиз починки.**
1. Классифицировать запрос в `NegotiationZone` (Tier 0 интент или эвристика по теме) → получить
   conviction релевантной taste-оси (`TasteEngine`, добавить геттер оси) → вызвать
   `Negotiation.decide(zone, conviction=…)` в `_decide`.
2. Map `Stance` → строку-директиву в `shareable_context`/системный промпт:
   `AGREE`→нейтрально; `PROPOSE_ALTERNATIVE`→«в этой зоне ты держишь позицию: вежливо не согласись и
   предложи альтернативу»; `CONCEDE`→«это зона пользователя — прими, но можешь высказать мнение».
3. (Опц.) mood-модификатор conviction по RFC §3.3.7 п.3 (хорошее настроение → мягче порог).
   Шов — ровно `handle_message._decide`/`_assemble_shareable_context`.

### (b) Нет само-эволюции: рефлексия пишет только в эпизод

**Доказательство.** Единственные вызовы записи в душу (`write_json`/`write_soul`/`append_genesis_log`)
в проде — `run_genesis.py:155-160` (однократное рождение). `ReflectTick.run`
(`heartbeat.py:142-163`) делает ровно один сайд-эффект записи: `save_episode(...)` (строка 163).
Живой `PersonalityState.soul` после boot меняется ТОЛЬКО через `with_mood` (`handle_message.py:220-221`,
`heartbeat.py:107,121`); `taste`, `mood_baseline`, `identity`, `phantom_prefs` фиксированы на boot
(`_load_soul` читает их один раз, `app.py:651-671`; `SOUL` — frozen, `soul.py:27`). RFC §3.3
описывал `TasteEvolution.apply_reflection`/`reinforce` (1480-1538) и `update_from_reflection` для mood
(1797-1810) — ничего из этого не реализовано. `experience_count` не инкрементируется нигде.

**Где именно отсутствует шов.** В `ReflectTick.run` после генерации рефлексии (`heartbeat.py:144-154`)
нет шага «применить выводы»: ни к mood (нет дельты от рефлексии), ни к вкусам (нет reinforce),
ни записи обновлённого профиля через `SoulStore.write_json("taste_profile"/"mood")`. Нет также
порта для частичного апдейта души (`SoulStore` умеет только полную перезапись JSON).

**Эскиз починки.**
1. Доменный сервис `TasteEvolution.reinforce(axis, delta, *, weight)` (чистый): сдвигает `value`
   обратно-пропорционально conviction, инкрементит `experience_count`, растит `conviction` (RFC
   правила 1497-1503). `SOUL.with_taste(...)`/`with_baseline(...)` (новые frozen-копии).
2. `ReflectTick` (или отдельный `ApplyReflection` use-case) парсит рефлексию в сигналы
   (какие темы зашли/нет) и: (а) применяет `MoodDelta` от рефлексии к live-mood + baseline-сдвиг;
   (б) `reinforce` по затронутым осям; (в) персистит обновлённые `taste_profile`/`mood` через
   `SoulStore` (нужен метод частичного апдейта или re-write существующих JSON).
3. Так личность реально дрейфует от прототипа (VISION §4 «всё больше расходится с книжным Бобом»).

---

## 3. Прочие провалы глубины vs исходное видение

- **Off-days / уязвимость / «не знаю» (VISION §4.1, Фаза 3)** — анти-цель «вечный позитив» структурно
  не закрыта: `_SYSTEM_PROMPT` (`handle_message.py:79-82`) безусловно «warmly». Нет механики «сухого»
  Боба в плохом настроении кроме слова tone в контексте — но сам промпт всё равно велит быть тёплым,
  что конфликтует с low-valence.
- **Текущее увлечение, которое эволюционирует и всплывает (VISION §4.1, Фаза 3)** — отсутствует
  полностью; нет ни состояния «fascination», ни инъекции в разговор.
- **Эволюция фантомных предпочтений (PRD §5.3: затухают/крепнут/превращаются в вкус)** — нет; это
  статичный кортеж строк (`soul.py:35`), никогда не меняется после Genesis.
- **«Фантомный момент» / imprinting awakening-phase 48h (PRD §5.1, §4.2)** — не реализован; Genesis
  однократен и сразу обычный режим.
- **Inner monologue не сохраняется** — мысль эфемерна (`heartbeat.py:106-107` берёт только дельту),
  её нельзя «вспомнить» или процитировать («пока тебя не было, думал о…» из VISION Фаза 2 опирается на
  рефлексии-эпизоды, но не на монолог).
- **Богаче mood-сигналы** — реализованы только sentiment/частота/время/presence
  (`update_mood_from_text.py:79-120`). Замысел VISION §4 («онлайн/печатает», более тонкие сигналы) —
  частично; «печатает»/online-статус не используются.
- **RelationshipTracker / Exodus Mode (PRD §3.2.2)** — отсутствуют целиком (заявлены как Фаза 3 / вне
  P0, но это пробел относительно полного видения «двусторонних эмоций»).
- **Goal Engine / Planner / self-improvement rules (PRD §3.2.1, RFC §3.3.4)** — отсутствуют (часть
  заморожена/отнесена к эпику агентности #5-B/C, VISION §4.1 «где проходит граница»). Зафиксировано как
  ожидаемо-вне-P0, не как регрессия.

---

## 4. Рекомендуемый scope двух dev-эпиков

### Эпик «Negotiation-врезка» — Боб активно защищает свои ценности

**Цель.** `Negotiation.decide` начинает реально влиять на ответ: в своей/общей зоне при высокой
conviction Боб не поддакивает, а вежливо не соглашается / предлагает альтернативу.

- **Ключевые файлы:** `application/usecases/handle_message.py` (`_decide` 224-260,
  `_assemble_shareable_context` 297-325, `_SYSTEM_PROMPT` 79-82); `domain/personality/negotiation.py`
  (готов); `domain/personality/taste.py` (добавить геттер `axis_for(topic)` для conviction).
- **Шов:** в `_decide` перед сборкой запроса — классификация зоны + получение conviction оси →
  `Negotiation.decide(...)` → map `Stance` в текстовую директиву, добавляемую в `shareable_context`
  и/или в системный промпт. Tier 0 для классификации зоны (или чистая эвристика — без сети в тестах).
- **Порты/новое:** при LLM-классификации зоны — переиспользовать `LLMRouter` (`TaskType` новый, напр.
  `NEGOTIATION_ZONE`, Tier 0). Можно обойтись без нового порта, если зона — эвристика по ключам темы.
- **Тесты (фейки, без сети):** unit на map `Stance`→директива; интеграционный на `HandleMessage` с
  fake-router и заданной taste-осью (HATE+high conviction в BOB_PERSONAL) → проверить, что итоговый
  промпт содержит директиву «не соглашайся/предложи альтернативу». Регресс: USER_DOMAIN → `CONCEDE`,
  директива «прими».

### Эпик «Само-эволюция» — рефлексия реально меняет личность

**Цель.** Рефлексия (и опыт взаимодействий) сдвигает вкусы/убеждённость/настроение-baseline и
персистит их — Боб со временем расходится с книжным прототипом.

- **Ключевые файлы:** `application/usecases/heartbeat.py` (`ReflectTick` 124-163 — добавить шаг «apply»);
  новый `domain/personality/taste_evolution.py` (`reinforce`, чистый, по RFC 1480-1538);
  `domain/personality/soul.py` (добавить `with_taste`, `with_baseline`); `domain/personality/mood.py`
  (есть `update`); `infrastructure/persistence/soul_store.py` + `domain/ports.py` (метод частичного
  апдейта/перезаписи `taste_profile`/`mood`); `app.py:651-671` (`_load_soul` уже читает обратно — путь
  round-trip готов).
- **Шов:** после `_router.run(REFLECT)` в `ReflectTick.run` — новый use-case `ApplyReflection`: парс
  рефлексии в сигналы → `MoodDelta` (live+baseline drift) + `TasteEvolution.reinforce` по осям →
  `state.soul = soul.with_mood(...).with_taste(...)` → `SoulStore.write_json(...)` персист.
- **Порты:** `SoulStore` уже имеет `write_json` (`ports.py:369`); достаточно вызывать его из apply-шага
  (или добавить `update_json` для merge). RNG/Clock инъектируются как и везде.
- **Тесты (фейки, без сети):** unit на `TasteEvolution.reinforce` (conviction растёт, value сдвигается
  медленнее при высокой conviction, `experience_count++`); unit на `with_taste`/`with_baseline`
  (immutability); интеграционный `ReflectTick` с fake-router (рефлексия про «люблю X») + fake-SoulStore
  → проверить, что ось X усилилась И что `write_json("taste_profile", …)` вызван. Idempotency: повтор
  тика продолжает усиливать (не сбрасывает).
