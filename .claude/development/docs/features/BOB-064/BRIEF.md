<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-064 — «Актуализация README.md + README-ru.md» (Фаза 1)

> **Status:** Approved
> **Created:** 2026-07-02
> **Type:** chore · Фаза 1 аудита · BOB-Issues #23, #24

---

## Проблема

`README.md` + `README-ru.md` не трогались с **2026-02-27** (до пивота). Продают замороженную визию
(камера/PTZ, планшет-аватар Godot, FLUX-облик, food-order, VR) **как отгруженное**; стек неверный
(**FastAPI** — которого нет в зависимостях; **Telegram/FTS5/Ollama не упомянуты**); нет Installation/
Quick-start (у эталона beadloom — есть). BOB-Issues #23/#24.

## Решение (утв. owner: beadloom-стиль · упор на shipped · компактно)

Переписать оба README (EN + RU-зеркало) по структуре:
1. `# Bob` + tagline (+ бейджи как у beadloom) — компактно.
2. **What is Bob?** — Telegram-нативный компаньон-агент (Bobiverse-inspired), личный инструмент. Кратко.
3. **What Bob does today (shipped)** ← ЯДРО: Telegram-чат с личностью (mood/taste/negotiation/настроение);
   персистентная память SQLite+FTS5 + recall; **web_search** (со ссылками) + **read_url** (SSRF-safe);
   эпистемическая самопроверка (сам сверяет волатильные факты); **Боб-кодер** (гейтед, ведёт Claude Code на
   своём репо); проактивность (heartbeat/рефлексия); групповая нить (multi-party). Честный отказ вместо
   выдумки.
4. **Installation** — prereqs (Ollama + модели Qwen, токены в `.env`), `uv sync`.
5. **Quick start** — `./bob start | stop | restart | status | logs`.
6. **Architecture** — DDD/Clean (domain ← application ← infrastructure; GUPPI-исполнитель; Qwen Tier-0/1;
   SQLite+FTS5); ссылка на `docs/` + `.claude/dev-docs/`.
7. **Tech stack** (ПОЧИНИТЬ): Python 3.12/asyncio · aiogram (Telegram) · Ollama + Qwen 2.5 (7B/0.5B) +
   Qwen MaaS (tier-провайдеры) · Claude Code CLI (кодинг) · SQLite+FTS5. **Убрать FastAPI**; voice/vision —
   не сюда.
8. **Roadmap / bigger vision** — замороженное (визуальный облик/камера/планшет/FLUX/голос) явно как
   *planned/frozen*, не как отгруженное.
9. Project status · License · Disclaimer — оставить, подрезать.

🔴 **Не переусердствовать:** компактно, ссылаться на `docs/` за деталями; RU — точное зеркало EN; только
правда (ничего не отгруженного не выдавать за готовое).

## Беады

- `.1` **dev/tech-writer** — переписать `README.md` (EN) + `README-ru.md` (RU-зеркало) по структуре выше;
  сверить каждый факт стека с `pyproject.toml`/кодом; добавить Installation + Quick-start (`./bob`).
- `.2` **review** — 🔴 точность (ничего замороженного как shipped; стек верен — нет FastAPI, есть Telegram/
  FTS5/Ollama); RU=EN по структуре; компактность; ссылки живые; beadloom-parity (Installation+Quick-start).

## Критерии приёмки

- Оба README актуальны: shipped отдельно от vision; стек верный; Installation + Quick-start (`./bob`) есть.
- RU — зеркало EN; компактно; ничего не отгруженного не подаётся как готовое.
- BOB-Issues #23/#24 закрыть.

## Связи

BOB-Issues #23/#24 (Фаза 1). Эталон: `/Users/v.zoologov/beadloom/README.md`. Стек: `pyproject.toml`.
Лаунчер: `./bob` (BOB-#74). После — Фаза 2 (ports-split + layer-rule).
