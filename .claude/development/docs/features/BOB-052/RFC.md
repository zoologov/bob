<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-052 — «Разрешение на привилегированное»

> **Status:** Approved
> **Created:** 2026-06-30
> **PRD:** `.claude/development/docs/features/BOB-052/PRD.md`
> **Решения (утв.):** семантический `PrivilegeJudge` · NL+команды · per-request по умолчанию (durable по
> «авторизуй») · сбой флоу → тихо опускается, безопасный дефолт = отказ.

---

## Идея решения

На сообщение **не-авторизованного** участника, требующее привилегированного (инструмент/внутрянка/owner-
данные), Боб НЕ молчит и НЕ делает сам, а заводит **pending permission-request** и **спрашивает owner**.
Owner approve → Боб исполняет запрос для этого участника (разово или durable-авторизация); deny → мягкий
отказ. Авторизованные — как сейчас, без спроса. Реюз `Authorizer` (BOB-019), capability/tool-loop,
паттерн approve (BOB-039).

## Детект привилегированного запроса

Только для **не-авторизованного** отправителя (owner/allowlisted — путь как сейчас). Семантический
**`PrivilegeJudge`** (Tier-0, в духе `ResponseJudge` BOB-049): {текст запроса + список доступных
capability + контекст} → `PrivilegeNeed` {`needs_permission: bool`, `kind: tool|internal|owner_data`,
`what: str` (что просят, человекочитаемо)}. Консервативно: обычная болтовня/общее знание (BOB-051 публично)
→ `needs_permission=False` (обычный ответ). Семантика покрывает и инструменты, и внутрянку, и owner-данные
(не только capability-мап).

## Доменная модель

```python
class PermissionState(StrEnum):
    PENDING = "pending"      # ждёт решения owner
    APPROVED = "approved"    # owner разрешил → исполнить
    DENIED = "denied"        # owner отказал → мягкий отказ
    EXPIRED = "expired"      # протух/отменён

@frozen(slots=True)
class PermissionRequest:
    id: str
    requester_id: int        # кто просит (не-owner)
    requester_name: str
    request_text: str        # исходный запрос (для исполнения на approve)
    kind: str                # tool|internal|owner_data
    what: str                # человекочит. «показать задачи проекта»
    state: PermissionState
    created_at: datetime
```

`PermissionRequestStore` (SQLite, как `coding_session`): сохранить/получить активный/сменить состояние;
идемпотентная миграция.

## Флоу (application `PermissionFlow`, провязка в handle_message)

1. **Запрос.** Не-авторизованный участник → `PrivilegeJudge`. `needs_permission=True` → создать
   `PermissionRequest(PENDING)`; **уведомить owner** в топике/группе: «Вова, Норман просит *<what>* —
   разрешить?» (голос Боба); просящему — лёгкое «спрошу Вову». `needs_permission=False` → обычный ответ
   (BOB-049/051), флоу не трогает.
2. **Решение owner.** ТОЛЬКО `is_owner`. Естественно: «да/разреши/покажи» → approve; «нет/откажи» → deny;
   «авторизуй Нормана» → durable. Команды-резерв: `/allow` `/deny` `/authorize <user>`. NL-детект approve/
   deny (консервативный, как BOB-042 `is_approval`/`is_stop`).
3. **Approve → исполнить (с привилегией для ЭТОГО запроса).** Перепрогнать `request_text` через
   capability/tool-loop / раскрытие внутрянки/owner-данных — **с временно поднятой привилегией только для
   этого запроса** — и ответить просящему результатом (голос Боба). **Durable:** `Authorizer.authorize
   (requester)` → дальше как allowlisted (без спроса).
4. **Deny → мягкий отказ** просящему: «спросил Вову — пока не могу».

## Исполнение на approve (детали)

- `request_text` сохранён → на approve Боб исполняет именно его. Технически: запустить tool-loop/capability
  для запроса с флагом «авторизовано для этого запроса» (одноразовый elevated-контекст), или (durable) —
  обычным авторизованным путём после `authorize`. Результат → реплика просящему.
- Внутрянка: на approve Боб может раскрыть запрошенный inner-life-кусок; без approve — нет (BOB-051 гейт цел).

## 🔴 Безопасность

- **Только owner** approve/deny/authorize (`is_owner`); не-owner не может разрешить (даже себе).
- **Привилегия — только для одобренного запроса** (per-request) или явной durable-авторизации; по умолчанию
  ничего не раскрывается без owner.
- Внутрянка/owner-приват/инструменты неавторизованным — **только через approve**. BOB-051 (память публична)
  не ослабляется; BOB-052 добавляет КОНТРОЛИРУЕМЫЙ путь к привилегированному, не дыру.
- Тест-инвариант: не-авторизованный приват-запрос без approve → НЕ исполнен (только owner-нотис + «спрошу»);
  approve только от owner; deny → отказ; durable → allowlist.

## Отказоустойчивость (принцип «полный Боб»)

Флоу разрешения — **поверх** обычного пути. Сбой `PrivilegeJudge`/стора/нотиса → **тихо опускается**
(`_safe_addon`-стиль BOB-050): обычный ответ Боба не ломается, привилегия НЕ выдаётся (безопасный дефолт —
не раскрывать). НЕ GUPPI-нотис (это не essential для обычного ответа). Безопасный дефолт при сбое = отказ.

## Слои (DDD)

- **domain:** `PermissionState`/`PermissionRequest`, `PrivilegeNeed`, `PrivilegeJudge` порт, NL-предикаты
  approve/deny/authorize.
- **application:** `PrivilegeJudge`-вызов, `PermissionFlow` (детект→pending→нотис→решение→исполнение),
  провязка в `handle_message`; durable через `Authorizer.authorize`.
- **infrastructure:** `SqlitePermissionRequestStore` (+ миграция), Tier-0 `LlmPrivilegeJudge`; owner-нотис
  через существующий шов.

## Риски и митигации

- **Гипер-детект** (всё подряд как привилегированное) → консервативный judge (общее знание BOB-051 →
  обычный ответ); тюнинг порога.
- **Зависший pending** → один активный на просящего; протухание по времени/новому запросу.
- **Исполнение с elevated** не должно «протекать» на другие запросы → привилегия строго на сохранённый
  `request_text`, одноразово; durable — только явный `authorize`.
- Регрессии BOB-049/051 → флоу поверх; обычный путь не меняется при `needs_permission=False`.

## Открытые решения (под утверждение)

1. **Детект:** семантический `PrivilegeJudge` (Tier-0) — **рекомендую** (покрывает tool+внутрянку+owner-
   данные единообразно). Чисто структурный capability-мап — уже; рекомендую семантику.
2. **Owner-решение:** NL «да/нет/авторизуй» (основное) + команды `/allow`/`/deny`/`/authorize` (резерв) —
   **рекомендую**.
3. **Грант по умолчанию:** per-request (разово); durable только по явному «авторизуй» — **рекомендую**.
4. **Сбой флоу:** тихо опускается, безопасный дефолт = отказ (не раскрывать), не GUPPI-нотис — **рекомендую**.
