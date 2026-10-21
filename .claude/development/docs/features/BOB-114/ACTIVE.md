<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE — BOB-114

> **Беада:** `bob-933` (P2, chore) · **Ветка:** `features/BOB-114` · **Спека:** [BRIEF.md](BRIEF.md)
> **Обновлено:** 2026-10-21

## Фокус

Защита `main` включена и описана по факту; подавление снято; Pages снова деплоит портал.

## Прогресс

- [x] Защита включена: `beadloom setup-branch-protection --repo zoologov/bob --check ci`
      (dry-run показал payload: `enforce_admins: true`, `required_approving_review_count: 0`,
      `required_status_checks: {contexts: ["ci"], strict: true}`); API подтвердил.
- [x] Pages включён (`gh api -X POST repos/zoologov/bob/pages -F build_type=workflow`,
      `html_url: https://zoologov.github.io/bob/`), `deploy-site.yml` перезапущен на `main`.
- [x] `flow.yml` (подавление снято с датой/причиной), П.6 (защита есть, CI required, чего CI не
      гоняет, урок про `--check ci`), coordinator-фрагмент, заголовок `ci.yml` (имя job'а `ci` —
      контракт с защитой), ROADMAP (запись BOB-114; история «403» не переписана). Перекомпозиция
      релизом: `config-check` exit 0, в уведомлении композированных файлов осталось только
      «Template rules»; «403» остаётся лишь как предыстория («здесь стояло»). Процессный гейт 4/4.
- [x] Pages: `deploy-site.yml` на `main` — build ✓ deploy ✓, `https://zoologov.github.io/bob/`
      → HTTP 200, `<title>Bob</title>` (портал 9.0.0 опубликован впервые).
- [ ] Коммит, пуш, PR → `main` под защитой, required `ci`, мёрж владельцем.

## Результаты

- Защита `main`: `contexts: ["ci"]`, `strict: true`, `enforce_admins: true`, ревью 0 (API).
- Экспорт трекера (`.beads/*.jsonl`, закрытые беады BOB-112/113 и `bob-933` в работе) едет этим же PR.
