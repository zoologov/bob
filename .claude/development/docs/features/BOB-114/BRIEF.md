<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF — BOB-114: защита `main` включена, подавление снято

> **Type:** chore · **Status:** Approved (решение владельца 2026-10-21: «по находкам согласен, делаем»)
> **Created:** 2026-10-21 · **Беада:** `bob-933` (бывшая «снять suppress, когда репозиторий станет публичным»)

## Проблема

При проверке мёржа BOB-112 (PR #144) выяснилось: репозиторий `zoologov/bob` **публичный с 2026-02-26**,
и API защиты ветки отвечает `404 Branch not protected`, а не `403 Upgrade to GitHub Pro or make this
repository public`, как утверждали CLAUDE.md §6 (с BOB-089), заголовок `ci.yml`, фрагмент координатора
и объявленное подавление `overlays.suppress` «Git — Trunk-based development» в `.beadloom/flow.yml`.
Условие снятия подавления (`until: репозиторий станет публичным…`) наступило — и, судя по дате
PublicEvent, наступило задолго до того, как подавление было объявлено. `main` держался только
дисциплиной.

## Решение

1. Защита включена **до** этой работы, командой релизного beadloom с явным контекстом (имя job'а
   в `ci.yml` — `ci`, а не умолчания beadloom `gate`/`tests (3.x)`/…):
   `beadloom setup-branch-protection --repo zoologov/bob --check ci` (сначала `--dry-run`).
   Проверено API: `contexts: ["ci"]`, `strict: true`, `enforce_admins: true`, обязательных ревью 0.
2. Подавление «Git — Trunk-based development» снято из `flow.yml` (с датой и причиной в комментарии);
   композиция обновлена релизной сборкой (`config-check` 0).
3. Тексты по факту: П.6 проектного слоя (защита есть, CI required, чего CI не гоняет), фрагмент
   координатора, заголовок `ci.yml` (имя job'а `ci` — часть контракта с защитой), ROADMAP.
4. Попутно (решение владельца в том же сообщении): GitHub Pages для репозитория был выключен (API 404,
   сайт 404, последний деплой 2026-07-31) — включён `build_type: workflow`, `deploy-site.yml`
   перезапущен; результат — в ACTIVE.md.

## Что НЕ входит

- Второе подавление («Template rules», `bob-yjv`) — его условие (ядро `/task-init` читает `language`)
  не наступило.
- Переписывание исторических записей ROADMAP (строки про «403» в BOB-089/095) — история не
  переписывается; добавлена датированная запись о снятии.

## Acceptance

- [x] `gh api repos/zoologov/bob/branches/main/protection` — `ci` required, strict, enforce_admins
- [ ] `flow.yml` без подавления «Git — …»; `config-check` релизом exit 0; уведомление в конце
      композированных файлов содержит только «Template rules»
- [ ] П.6 / `ci.yml` / coordinator-фрагмент не содержат «403» и «информативный» как текущее состояние
- [ ] PR BOB-114 → `main` прошёл required `ci` и смержен (первый мёрж под защитой)
- [ ] Pages: деплой `deploy-site.yml` зелёный, `https://zoologov.github.io/bob/` отвечает 200
