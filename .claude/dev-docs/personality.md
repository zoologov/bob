<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Личность Боба — карта (Mermaid)

> 📌 **Снапшот** (перенесён в `dev-docs` 2026-07-02, BOB-063). Исторический слепок; актуальную
> архитектуру см. `docs/` + `.claude/dev-docs/BOB-Issues.md`.
> Визуализация всей личностной системы Боба на 2026-06-24 (main `0452890`).
> Север: **никогда не выглядеть программно** — шаг за шагом к полноценной симуляции личности.
> Архитектура: DDD/Clean (домен чист ← application ← infrastructure); GUPPI — исполнитель;
> Qwen Tier-0/1 — подключаемый мозг; SQLite+FTS5 — память, переживающая рестарты.

---

## 1. Кто такой Боб — карта компонентов

```mermaid
flowchart TB
    SOUL["SOUL — рождён в Genesis<br/>ядро идентичности, переживает рестарты"]

    SOUL --> EMO
    SOUL --> SELF
    SOUL --> MEM
    SOUL --> SOC
    SOUL --> AUTO

    subgraph EMO["Эмоции и состояние"]
        MOOD["Mood — глубокое настроение<br/>valence · arousal · openness · social · stability"]
        OFF["off-days / спады настроения · BOB-020"]
        FASC["Fascination — текущее увлечение"]
        SULK["Обида (sulk) — холоден, но всё ещё он<br/>анти-Exodus, гарантированный выход · BOB-014"]
    end

    subgraph SELF["Вкус и самовыражение"]
        TASTE["Taste — вкус, самоэволюция · BOB-013"]
        PHANT["Phantom prefs — фантомные предпочтения"]
        VOICE["Голос / язык / форма ответа · BOB-018, BOB-012"]
        BREV["Краткость: длина = demand x интерес x mood · BOB-024"]
    end

    subgraph MEM["Память"]
        EPI["Эпизоды — SQLite+FTS5, recall по архиву"]
        FACTS["Семантические факты"]
        CONS["консолидация + дедуп фактов · BOB-021"]
        REFL["Рефлексия — внутренний монолог<br/>грундинг свежим контекстом · BOB-026"]
    end

    subgraph SOC["Социальное"]
        IDENT["Interlocutor — свои и чужие<br/>owner / гость (restricted) · BOB-019"]
        REL["Отношения по людям + обида/мат · BOB-014"]
        ADDRC["Адресность — кому сообщение · BOB-023"]
        FLOORC["Непрерывность диалога — кто 'у микрофона' · BOB-025"]
    end

    subgraph AUTO["Автономность — стадия B, ДРЕМЛЕТ"]
        PROACT["Проактивность — drive-model, governance · BOB-010"]
        GOALS["Goal Engine + Planner — свои цели · BOB-015"]
        PURSUE["самонаправленность под governance + kill-switch<br/>OFF по умолчанию"]
        GOALS --> PURSUE
    end
```

---

## 2. Поток одного хода — как Боб решает и отвечает

```mermaid
flowchart TD
    MSG["Сообщение в топике Боба"] --> PERC

    subgraph PERC["1 · Восприятие"]
        MD["Mood: обновить из текста · BOB-020"]
        WHO["Interlocutor: owner / гость · BOB-019"]
        INT["Topic interest · BOB-014.2a"]
    end

    PERC --> GATE

    subgraph GATE["2 · Адресность — отвечать ли"]
        CL["classify_addressivity<br/>mention / reply / 'Боб,…' / форум-гард BOB-027"]
        FL["conversation floor — поднять непрерывность<br/>floor=БОБ: безметочное от любого → к Бобу · BOB-025"]
        DR["decide_response"]
        CL --> FL --> DR
    end

    DR -->|SILENT| STOP["Молчит — прочитал, не его ход"]
    DR -->|REACT| LIKE["Лайк-реакция · BOB-018"]
    DR -->|ENGAGE| HOW

    subgraph HOW["3 · Как отвечать"]
        APP["engagement appetite<br/>FULL / PLAYFUL / TERSE / DECLINE · BOB-014.2a"]
        VB["verbosity: answer-demand → терс/норм/развёрнуто · BOB-024"]
        EP["ExpressionPlan / form_hint / REACT_ONLY · BOB-018"]
    end

    HOW --> GUEST{гость?}
    GUEST -->|да| RESTR["restricted: без owner-памяти,<br/>без инструментов · BOB-019"]
    GUEST -->|нет| RCL["recall памяти + grounding · BOB-011/021"]

    RESTR --> CMP
    RCL --> CMP

    subgraph CMP["4 · Сочинение"]
        LLM["LLM Tier-1 (Qwen) + голос:<br/>tone · anti-bait few-shot · sulk · relationship · brevity few-shot"]
        AR["анти-повтор: окно последних N ответов<br/>verbatim + near-verbatim · BOB-022/026"]
        LLM --> AR
    end

    AR --> OUT["Ответ — typing-keepalive + один rich-финал · BOB-008/009"]
    OUT --> PST["Персист: эпизод + mood-снимок ·<br/>advance floor · relationship/engagement feedback"]
```

---

## 3. Фоновая жизнь — Боб живёт между сообщениями

```mermaid
flowchart LR
    HB["Heartbeat — фоновые тики под supervision"]

    HB --> RT
    HB --> PT
    HB --> GT

    subgraph RT["ReflectTick — рефлексия"]
        R0["сгенерировать мысль 'про сейчас'<br/>грундинг + дедуп near-дублей · BOB-026"]
        R0 --> R1["эволюция fascination / phantom · BOB-020"]
        R0 --> R2["консолидация памяти · BOB-021"]
        R0 --> R3["восстановление обиды по времени · BOB-014"]
    end

    PT["Proactive tick<br/>'стоит ли заговорить?' + Tier-0 гейт<br/>quiet-hours / rate-limit / kill-switch · BOB-010"]

    GT["PursueGoalsTick — самонаправленность · BOB-015<br/>governance + safe-allowlist · OFF по умолчанию"]
```

---

## 4. Машины состояний

### Настроение (sulk / обида) · BOB-014

```mermaid
stateDiagram-v2
    state "Спокоен" as calm
    state "Обижен" as hurt
    [*] --> calm
    calm --> hurt: задели / направленное оскорбление
    hurt --> hurt: холодный тон, память цела — НЕ сброс
    hurt --> calm: распад по времени — гарантированный выход
```

### Непрерывность диалога (conversational floor) · BOB-025

```mermaid
stateDiagram-v2
    state "БОБ держит реплику" as bob
    state "у микрофона другой" as other
    state "IDLE — нить остыла" as idle
    [*] --> idle
    idle --> bob: прямое обращение / ответ Боба
    bob --> bob: безметочное в живой нити — до 5 мин
    bob --> other: явный поворот к другому
    bob --> idle: тайм-аут 300с / 2 молчания подряд
    other --> bob: обращение к Бобу
    other --> idle: тайм-аут
```

### Цель (Goal Engine, автономность) · BOB-015

```mermaid
stateDiagram-v2
    [*] --> PROPOSED
    PROPOSED --> APPROVED: owner апрув
    PROPOSED --> CANCELLED
    APPROVED --> ACTIVE: апрув плана (двойной гейт)
    ACTIVE --> BLOCKED
    BLOCKED --> ACTIVE
    ACTIVE --> PAUSED
    PAUSED --> ACTIVE
    ACTIVE --> DONE: критерий выполнен
    ACTIVE --> CANCELLED
```

---

## 5. Легенда — компоненты и эпики

| Эпик | Что дал личности | Статус |
|------|------------------|--------|
| **BOB-001** | Личность MVP, SOUL/Genesis, Mood/Taste/Negotiation | ✅ |
| **BOB-010** | Проактивность (drive-model, governance) | ✅ |
| **BOB-011/021** | Память: гибридный recall + консолидация/дедуп | ✅ |
| **BOB-013** | Вкус + самоэволюция | ✅ |
| **BOB-014** | Отношения по людям + обида (анти-Exodus) + мат | ✅ |
| **BOB-018** | Выражение: ExpressionPlan / form_hint / REACT_ONLY | ✅ |
| **BOB-019** | Социальная идентичность: свои/чужие, гость (restricted) | ✅ |
| **BOB-020** | Эмоц. глубина: off-days, fascination, phantom-эволюция | ✅ |
| **BOB-022/026** | Анти-повтор: окно ответов + грундинг/дедуп рефлексии | ✅ |
| **BOB-023** | Адресность: кому сообщение (к Бобу / другому / в воздух) | ✅ |
| **BOB-024** | Краткость по запросу: длина как характер | ✅ |
| **BOB-025** | Непрерывность диалога (conversational floor) | ✅ |
| **BOB-027** | Фикс адресности в форум-топике (псевдо-reply на корень) | ✅ |
| **BOB-015** | Автономность (Goal Engine + Planner + самонаправленность) | ✅ дремлет |

> **Тир 1 «Личность в диалоге» — закрыт.** **Тир 2 «Автономность»** — T2.1 отгружено (дремлет).
> Дальше по роадмапу: T2.2 self-improvement, Тир 3 «Боб-кодер», Тир 4 медиа/FLUX.
