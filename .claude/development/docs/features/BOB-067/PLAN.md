> **Status:** Approved
> **Type:** feature
> **Created:** 2026-07-30
> **Issue:** BOB-067

# PLAN — BOB-067 Repo-navigation (DAG)

## Беады

```
BOB-067 [feature] — Боб видит и навигирует весь репозиторий
├── BOB-067.1 [dev]         — repo-navigation: PrivacyGuard полный-репо + list_dir + find_file
│                              (порт + адаптер + фабрики + wiring). ОДИН cohesive юнит.
├── BOB-067.2 [test]        — unit (PrivacyGuard full-repo/escape/sanitize; адаптер list/find) +
│                              BDD .feature (листинг/поиск/«не найдено»/escape) + mutation ядра. deps: .1
├── BOB-067.3 [review]      — корректность/DDD/безопасность (escape-deny, sanitize) + doc-freshness. deps: .2
└── BOB-067.4 [tech-writer] — обновить docs (capabilities README/architecture) под новые tools. deps: .3
```

## Почему один dev-беад

Guard + list_dir + find_file касаются одних файлов (privacy_guard, subprocess_introspector, ports,
wiring) — это ОДИН логический юнит «Боб видит репо». УРОК BOB-066: параллельные dev на общем
worktree = плохо. Поэтому — один dev-агент, последовательно.

## Волны

- **Wave 1 (dev):** BOB-067.1.
- **Test wave:** BOB-067.2 (после .1).
- **Review wave:** BOB-067.3 (после .2). ISSUES → fix-беады → dev→test→review.
- **Docs wave:** BOB-067.4 (после review = OK).
- **Gate wave:** beadloom ci → tech-writer до зелёного → push → PR → self-merge → restart → живой прогон.

## Критический путь

BOB-067.1 → .2 → .3 → .4 → PR → merge → активация (restart) → live-verify.

## Риски

- `ALLOWED_ROOTS` используется адаптером (`:394`) — dev не должен сломать это использование при
  переходе на full-repo (сверить семантику, сохранить совместимость).
- `find_file` без `.git`-skip раздует вывод — обязательный skip + кап.
- Персона может продолжить нарративить даже с tools — review решает про анти-нарратив nudge.
