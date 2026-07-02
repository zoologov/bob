<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-064 — «Актуализация README.md + README-ru.md»

> **Status:** Done
> **Updated:** 2026-07-02

---

## Что сделано

- **README.md** (EN) переписан: shipped-упор, beadloom-стиль, компактно.
- **README-ru.md** — точное зеркало EN.
- Структура: What is Bob → **What Bob does today (shipped)** → Installation → Quick start (`./bob`)
  → Architecture (DDD/Clean) → Tech stack → Roadmap/bigger vision (frozen) → Project status →
  Development tools → License → Disclaimer.
- Убрана замороженная визия-как-shipped (камера/планшет/FLUX/food-order/VR).

## Review (inline) — факты сверены с репо

- Telegram = **aiogram** (не python-telegram-bot); **FastAPI отсутствует** в зависимостях ✓.
- Config-пример = `config/bob.example.yaml` (исправлено с ошибочного `bob.yaml.example`).
- Env: `BOB_TELEGRAM__TOKEN` / `BOB_TELEGRAM__OWNER_ID` / `BOB_LLM__TIER1_API_KEY` (реальные имена из loader).
- `assets/` не существует → убран из лицензионной таблицы (остался `bob-soul/`).
- Ссылки живые: `LICENSE`, `LICENSE-CC-BY-NC-SA.md`, `.claude/dev-docs/ROADMAP.md`, `docs/`, `./bob`.
- RU = EN по структуре и содержанию.

## Беады

- ✅ `bob-2ao.1` (dev) · ✅ `bob-2ao.2` (review) · ✅ `bob-2ao` (parent).

## Трекер

- BOB-Issues.md: #23/#24 → Closed; заодно согласованы #6/#19–22/#29 (BOB-063). Header: Open 22 / Closed 8.
