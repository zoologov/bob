> **Status:** Approved
> **Type:** feature (Тир-3 T3.C, срез 1)
> **Created:** 2026-08-01
> **Issue:** BOB-082

# RFC — Dev-канал в личке: лайв-стрим + сквозная память + scope-по-месту

## Резюме решения

Пять потоков, заземлённых на разведку: (1) **сигнал канала** (chat_type/is_group) прокинуть
gateway→event→scope — сейчас его НЕТ вообще; (2) **авторизовать owner-DM** (сейчас DM дропается); (3)
**scope по МЕСТУ** (личка→`owner_private`, группа→`public`) вместо текущего «по КТО» (латентная
неточность: сейчас даже owner-в-группе штампуется private); (4) **лайв-стрим сырых событий CLI** в
DM-канал (progressive `editMessageText`, без капа; группа — короткий указатель); (5) **раскрытие по
согласию owner'а** — net-new (консент-детектор Tier-0 + per-turn override фильтра). Сквозная память —
не трогаем recall (нет chat_id-фильтра), INV-1 держится.

## Разведанные seam-точки (авторитетно)

- **Сигнал канала (НЕТ):** `_ChatLike` (`gateway.py:188-190`) отдаёт только `id`; `MessageReceived`
  (`application/runtime/events.py:55-62`) без `chat_type`/`is_group`. Вход — `_to_message_received`
  (`gateway.py:606-621`, `chat.id` @614). Сигнал добавить здесь.
- **Authz:** `Authorizer.is_authorized` (`social/usecases/authorizer.py:55-67`) — chat-scope FIRST,
  вяжет даже owner'а → DM (chat_id==owner_id, не в `allowed_chat_ids`) отклоняется. Дроп —
  `_passes_gate` (`gateway.py:530-553`). Wiring — `runtime/wiring/access.py:40-42`.
- **Scope-по-КТО (чинить):** `_turn_is_shared_scope` (`handle_message.py:2190-2201`) → `owner_private`
  для ЛЮБОГО owner-хода (в т.ч. в группе); `_turn_visibility` (`:2095-2104`) → `visibility_for_scope`
  (`social/disclosure.py:71-79`, чистая).
- **Стрим:** `claude_runner.run` (`coding/adapters/claude_runner.py:87-122`) yield-ит сырые stream-json;
  `narrate` (`coding/narrate.py:129-137`) — lossy (глотает большинство → для лички НЕ он);
  `_narrate_run` (`coding_assistant.py:421-461`, кап `_MAX_NARRATION`); порт `OwnerNotifier`
  (`:103-113`, transport-free); порт `StatusPanel` (`:144-160`) + `EditableStatusBot`/`StatusPanel`
  (`coding/adapters/indicator.py:57-161`) — **прецедент progressive `edit_message_text`**; адаптер
  выбора чата `_CodingOwnerNotifier` (`coding/adapters/owner_notifier.py:47-58`) через
  `RichMarkdownSender.send(chat_id, message_thread_id)` (`gateway.py:866-920`). Wiring —
  `runtime/wiring/coding.py:84-149` + `composition.py:504-515` (сейчас шлёт в супергруппу-топик).
- **Disclosure (консент net-new):** `may_surface(visibility, trust)` (`disclosure.py:55-68`) — чисто по
  аудитории (trust текущего собеседника), БЕЗ консент-параметра; `filter_surfaceable(recalled, trust)`
  (`:82-96`), единственный вызыватель — `_recall_surfaceable` (`handle_message.py:2106-2125`).
  `DisclosureGuard` (`application/usecases/disclosure_guard.py:55-84`) — guest-only, только смягчает
  отказ, не разрешает. Консент-override нигде нет.
- **Память (сквозная, подтверждено):** `episodic_log` без `chat_id` (`schema.sql:6-38`); recall
  глобальный `fts_recall.py:85-98`; персист `_persist` (`handle_message.py:2133-2174`, пишет `visibility`).
- **Config:** `telegram.*` / `coder.*` (`config/bob.yaml`), хелперы `runtime/config.py:185-235`.

## Поток 1 — Сигнал канала (foundational)

`_ChatLike` + `MessageReceived` получают `is_group: bool` (или `chat_type: str`), проставляемый в
`_to_message_received` из `update.effective_chat.type` (`private` → is_group=False; `group/supergroup`
→ True). Прокинуть до `handle_message`. Чистая часть: маппинг `chat_type → is_group`.

## Поток 2 — Авторизация owner-DM (owner-only)

В `is_authorized` спец-кейс: разрешить, когда `chat_id == owner_id и user_id == owner_id` (личка owner'а
= его собственный chat.id). Только owner (в 1:1 DM chat.id == user.id — чужой туда не напишет). Гость/
чужой в DM невозможен by construction; не расширяем allowlist для группы. Wiring `access.py:40-42`.
Опц. явный `telegram.owner_dm_chat_id` (дефолт = owner_id). 🔴 Feasibility: бот пишет в DM только если
owner нажал Start — проверить живым смоуком.

## Поток 3 — Scope по МЕСТУ (+ фикс латентной неточности)

`_turn_is_shared_scope` решает по **каналу** (is_group из потока 1), НЕ по `interlocutor.kind`:
- личка (is_group=False) → `owner_private`;
- группа (is_group=True) → `public` (в т.ч. owner-в-группе — исправляет текущее ошибочное `owner_private`).
`visibility_for_scope(is_group)` уже это выражает — переключить вход с «кто» на «где». 🔴 Регресс-риск:
не сломать surface owner'у (owner TRUSTED → may_surface=True сохранён) и групповое поведение BOB-066/078.

## Поток 4 — Лайв-стрим в dev-канал (личка)

- Новый renderer поверх `OwnerNotifier`/`StatusPanel`, целящий в **DM chat_id** (не thread-locked
  `_ReplyGateway`, а `RichMarkdownSender.send(chat_id=owner_dm, message_thread_id=None)` — как
  `_CodingOwnerNotifier`).
- **Сырые события, без капа:** рендер `stream-json` событий (не lossy `narrate`) — чистый
  `render_stream_event(event) -> str | None` (tool-call/файл/тест/вывод/прогресс), прогрессивно катящееся
  сообщение через `StatusPanel.update` (`edit_message_text`) + отдельные сообщения на крупные шаги.
  Кап `_MAX_NARRATION` НЕ применяется в DM (флуд там уместен); для группы кап/указатель сохраняются.
- **Группа — только указатель (S2/INV-5):** при dev-сессии в групповой топик максимум одна строка
  «работаю над кодом — детали в личке» (или ничего). Firehose — только в личку.
- **Флаг** `coder.dev_dm` (bool, default OFF) + `coder.dev_dm_chat_id` (дефолт owner_id). OFF → поведение
  как сейчас (нарратив в группу). Wiring `coding.py`/`composition.py:504-515` выбирает DM-цель при ON.
- **Использование:** `/code` (или dev-режим) из лички → стрим в личку; сессия/worktree/PR-гейт — как в
  BOB-039 (не трогаем). Use-case не меняется (порт transport-free) — только новый адаптер + wiring.

## Поток 5 — Раскрытие по согласию owner'а (net-new, самый тонкий)

- **Консент-детектор (Tier-0, семантика, не ключевые слова — north star):** новый чистый предикат-намерение
  + Tier-0 адаптер (образец `permission/intent.py` is_grant/`update_mood_from_text`): «owner сейчас
  разрешает вынести приватное в ЭТОТ чат?» (`«расскажи ребятам…», «да, можешь рассказать»`). Только
  owner-ход, только в группе (в личке всё и так доступно). Консервативно: неуверенность → НЕ раскрывать.
- **Per-turn override:** `owner_consented_disclosure: bool` прокинуть в `_recall_surfaceable` →
  `filter_surfaceable(recalled, trust, *, owner_consented=False)` (чистое ядро расширяется параметром):
  при `owner_consented=True` пропускать `owner_private` элементы в surface этого хода (recall-time
  override, без мутации хранимого `visibility` — раскрытие разовое, не переклассификация).
- **Дефолт (S4):** без консента owner_private не выносится по инициативе Боба; existing такт для гостей
  сохранён. 🔴 BDD чётко пиннит S4 (без согласия — молчит) vs S5 (с согласием — раскрывает).

## Инварианты → реализация

- INV-1 сквозная память → recall не трогаем (нет chat_id-фильтра); DM пишет в тот же архив.
- INV-2 scope+согласие → поток 3 (scope по месту) + поток 5 (консент-override, консервативный).
- INV-3 односторонность → без stdin; гейты/worktree BOB-039 не трогаем.
- INV-4 owner-only → поток 2 спец-кейс только owner-DM.
- INV-5 группа не флудится → поток 4 (firehose только в личку + указатель).

## Флаг / безопасность

Всё новое за `coder.dev_dm` (default OFF) + консент-детектор за тем же/консервативный. OFF → нулевое
изменение (стрим в группу как сейчас, scope-фикс — обсудить: поток 3 меняет поведение даже при OFF, т.к.
это корректность; вынести scope-фикс под отдельный аккуратный контроль или принять как bugfix — решает
review). worktree-изоляция + PR-гейт (main неприкосновенен) + owner-only — сохранены.

## Риски и меры

- **Scope-фикс ломает группу** (поток 3) → owner TRUSTED (surface к нему цел); BDD на BOB-066/078
  групповое поведение; поток 3 — минимальная правка входа `visibility_for_scope`.
- **Консент триггерит ложно** (выносит приватное без спроса) → консервативный Tier-0 (неуверен → нет),
  только owner+группа, BDD S4/S5, живой смоук.
- **DM недостижима** (owner не нажал Start) → feasibility-смоук в потоке 2; при недоступности — честный лог.
- **Утечка приватного firehose в группу** → поток 4 строго целит DM chat_id; группа — только указатель.
- **Память силосится** → НЕ добавлять chat_id-фильтр; тест на сквозной recall (S3).

## Тест-стратегия

- **Unit/TDD:** `chat_type→is_group`; `visibility_for_scope` по месту (DM→private, group→public, owner-в-
  группе→public); `render_stream_event` все виды событий; `filter_surfaceable(..., owner_consented)`
  (**mutation ≥85%** на расширенном ядре disclosure + render). authz owner-DM спец-кейс (owner allow,
  чужой в группе — как раньше).
- **BDD `.feature`** (через границу): S1 стрим в DM (fake notifier ловит сырые события, не капнутые),
  S2 группа получает только указатель, S3 сквозной recall (эпизод из «DM» находится в «группе» и наоборот),
  S4 owner_private НЕ в группу по умолчанию, S5 owner-консент → раскрывает, S6 owner-only (гость/чужой не
  получает dev-канал).
- **Живой смоук (после активации флага):** `/code` из лички → живой стрим в личку; группа чистая; спросить
  в личке про группу и наоборот (память); S5 «расскажи ребятам про X» в группе → раскрывает; без спроса —
  молчит.
