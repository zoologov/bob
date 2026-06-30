<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-053 — «Веб-поиск» (`web_search`)

> **Status:** Approved
> **Created:** 2026-07-01
> **PRD:** `.claude/development/docs/features/BOB-053/PRD.md`
> **Решения (под утв.):** навык за capability-швом · провайдер Qwen MaaS нативно
> (`qwen3.7-plus`, `enable_search`+`enable_source`) · `permission="safe"`, привилегия по отправителю
> (authz/BOB-052) · синтез в голосе Боба со ссылками · сбой/пусто → честный нотис/оговорка.

---

## Идея решения

Новый навык **`web_search`** за существующим capability-швом (BOB-002): GUPPI через `ToolLoop` сам
выбирает его, когда вопрос требует свежей/внешней информации. Навык делает **один** вызов к провайдеру
поиска (Qwen MaaS, `qwen3.7-plus`, `enable_search`+`enable_source`), получает **обоснованный ответ +
источники** (title/url) и возвращает их в tool-loop; финальную реплику Боб **синтезирует своим голосом**
со ссылками. Привилегия — как у всех навыков: tool-loop запускается только для авторизованного отправителя
(owner/allowlist); не-авторизованный → флоу разрешения owner (BOB-052). Реюз всего шва — **никаких новых
потребителей**, только +1 capability и +1 порт с реализацией.

## Доменная модель (порт + значения)

В `domain/ports.py` — провайдер-агностичный порт (как `LLMProvider`/`RepoIntrospector`):

```python
@frozen(slots=True)
class WebSource:
    title: str
    url: str

@frozen(slots=True)
class WebSearchResult:
    answer: str                       # обоснованный ответ провайдера (grounded)
    sources: tuple[WebSource, ...]    # source list (title+url), возможно пустой

@runtime_checkable
class WebSearchProvider(Protocol):
    async def search(self, query: str) -> WebSearchResult: ...
```

Порт чист и провайдер-агностичен (первая реализация — Qwen-native; завтра Tavily/др. — без смены навыка).
Значения `WebSource`/`WebSearchResult` — frozen+slots в domain (как memory-entities).

## Навык (application capability)

`application/capabilities/web_search.py` — `make_web_search_capability(provider: WebSearchProvider)` →
`Capability` (по образцу `inspect_architecture`/`recall_memory`):

- `name = "web_search"`.
- `description` — модели: «искать в интернете свежую/внешнюю информацию и отвечать со ссылками; использовать,
  когда ответа нет в памяти/обучении или нужна актуальность».
- `input_schema` — `{ "query": {"type": "string"} }`, required `query`.
- `permission = "safe"` — read-only, без сайд-эффектов (как `read_code`/`inspect_architecture`). 🔴
  Привилегия НЕ здесь: tool-loop вообще не запускается для не-авторизованного отправителя (authz/BOB-051/
  052) — навык доступен только тем, кому уже разрешён инструментарий.
- `execute(args)` — валидирует `query` → `provider.search(query)` → возвращает компактную проекцию
  (ответ + источники) в tool-loop. **Сырой дамп не возвращается** — отдаём структурировано, финальный
  синтез делает модель в голосе Боба. Пустые источники / пустой ответ → честная проекция «не нашёл»
  (US-3/US-5), не выдумка.

Регистрация в `app.py` рядом с прочими `make_*_capability` → `CapabilityRegistry` (advertise +
dispatch). Преамбула манифеста (GUPPI исполняет навык для Боба) — как у существующих.

## Провайдер поиска (infrastructure)

`infrastructure/llm/web_search_qwen.py` — `QwenWebSearchProvider` реализует `WebSearchProvider`. 🔴
**Отдельный клиент Responses API** (НЕ chat/completions `OpenAICompatProvider`; verify .1 показал, что
именно Responses API отдаёт источники на нашем ключе — chat/completions и legacy-native не отдают):

- **Эндпоинт:** `{base}/compatible-mode/v1/responses` — **тот же workspace-хост и тот же `sk`-ключ
  Qwen MaaS**, что у текущего провайдера (не нужен отдельный/глобальный ключ). base — из конфига.
- **Payload:** `{ model: "qwen3.7-plus", input: <query>, tools: [{ "type": "web_search" }] }`.
- **Ответ** `output[]` (массив items): item `type=="web_search_call"` → `action.sources[*].url` →
  `sources` (источники, URL; `title` может отсутствовать — для v1 URL достаточно); item
  `type=="message"` → `content[*].output_text` → `answer`. (Items `reasoning`/прочее — игнорируем.)
- **Ключ:** тот же `BOB_LLM__TIER1_API_KEY` (Qwen MaaS), через factory/конфиг, не хардкод; транспорт —
  `httpx` (как `_post_json` в `openai_compat`).
- Сетевые/HTTP-ошибки и неожиданная форма ответа → **поднять исключение** (caller решает) — паттерн
  Tier-0 джаджей (`LlmPrivilegeJudge` raise-on-failure). NB: Responses API + поиск медленнее обычного
  (несколько секунд) → таймаут с запасом (как `timeout_seconds: 180` для reasoning-моделей).

Сборка — через `infrastructure/llm/factory.py` (как прочие LLM-клиенты): из конфига
(`search.provider=qwen`, `search.model=qwen3.7-plus`, endpoint/флаги) → `QwenWebSearchProvider`; в `app.py`
прокидывается в `make_web_search_capability`. Навык включается флагом конфига (как `coder.enabled`) —
по умолчанию можно on (owner-only через authz).

## 🔴 Отказоустойчивость («полный Боб или честный GUPPI-нотис»)

- `web_search` — **essential** для запроса, который Боб решил «пойти поискать» (не декоративный addon).
  Поэтому при сбое провайдера: ограниченный ретрай → **честный GUPPI-нотис** о недоступности поиска ИЛИ
  явная оговорка «не нашёл / отвечаю по памяти». 🔴 **Боб НЕ выдаёт ответ из обучения под видом
  найденного** — это и есть «никаких degraded полу-ответов».
- Пустой результат (поиск прошёл, ничего релевантного) → честное «не нашёл», без конфабуляции (US-5),
  как `_NOT_FOUND` в `inspect_architecture`.
- Сбой не ломает обычный диалог: tool-loop уже умеет ронять упавший вызов; финальная реплика — честная.

## Слои (DDD)

- **domain:** `WebSource`/`WebSearchResult`, порт `WebSearchProvider` (чистые, без I/O).
- **application:** `web_search.py` (`make_web_search_capability`) — валидация + делегирование порту +
  компактная проекция; регистрация в registry; гейт по отправителю — существующий (authz/BOB-052).
- **infrastructure:** `QwenWebSearchProvider` (нативный DashScope-вызов, парсинг `search_info`), сборка в
  `factory.py`; конфиг `search.*`.

## Риски и митигации

- **~~Нативный эндпоинт/ключ~~ — ВЕРИФИЦИРОВАНО ✅** (verify .1, 2026-07-01): источники доступны на нашем
  текущем workspace-ключе через **Responses API** (`/compatible-mode/v1/responses` + `tools:[web_search]`);
  chat/completions и legacy-native их НЕ отдают. Глобальный/отдельный ключ НЕ нужен.
- **Гипер-вызов** (Боб ищет где не надо / на каждый вопрос) → точная `description` (только свежее/внешнее/
  чего нет в памяти); тюнинг формулировки; tool-loop сам решает.
- **Конфабуляция «найденного»** при сбое → essential-путь с честным нотисом, ответ из обучения под видом
  поиска запрещён (тест-инвариант).
- **Сырой дамп сниппетов** → навык возвращает структурированную проекцию, синтез — модель в голосе Боба.
- **Регрессии шва** → +1 capability за стабильным контрактом; потребители (tool-loop/GUPPI) не меняются.
- **Источников нет/много** → разумный дефолт (напр. топ-N), пустой список допустим (честное «не нашёл»).

## Открытые решения (под утверждение)

1. **Провайдер:** Qwen MaaS через **Responses API** (`qwen3.7-plus`, `tools:[web_search]`) — **рекомендую**
   (тот же ключ, бесплатно, **с источниками-URL**; verify .1 подтвердил). Tavily — позже, за тем же
   портом, если понадобятся титлы источников / иное качество.
2. **Привилегия:** `permission="safe"` + гейт по отправителю (authz/BOB-052), без отдельного `confirm` —
   **рекомендую** (web_search read-only; кто-доступ решает authz, не capability-уровень).
3. **Сбой/пусто:** essential → честный GUPPI-нотис/оговорка, БЕЗ ответа-из-обучения под видом поиска —
   **рекомендую**.
4. **Объём v1:** атомарный один проход; `web_research` (многошаг) — отдельно, ROADMAP T2.3 —
   **рекомендую**.
