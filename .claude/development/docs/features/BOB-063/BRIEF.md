<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-063 — «Гигиена репозитория» (Фаза 1)

> **Status:** Approved
> **Created:** 2026-07-02
> **Type:** chore · Фаза 1 аудита (быстрые победы) · BOB-Issues #19–22, #29, #20, #6

---

## Проблема

Аудит нашёл мусор/захламление — «не по делу» в корне и трекере (BOB-Issues #19–22,#29). Нужно чисто.

## Решение (только чистка; кода не трогаем)

1. **#19 — удалить orphan-транскрипты** `dialog.txt` + `test.txt` (корень, трекнуты, не ссылаются нигде;
   `test.txt` вводит в заблуждение — похоже на тест). `git rm`. **+ gitignore:** добавить правило под
   dialogue-дампы (рядом с `first_dialogue.txt`), например `*dialog*.txt` / `test.txt`.
2. **#21 — перенести** `personality.md` (корень, Mermaid-снапшот личности) → `.claude/dev-docs/`
   (`git mv`) + дата-штамп «snapshot», чтобы не путали с актуальным.
3. **#20 — gitignore-пробел:** добавить `.claude/worktrees/` (агентские worktree светятся в `git status`).
4. **#22 — прун трекнутых бинарников** в `.claude/dev-docs/archive/`: `old-tooling-state-20260618.tar.gz`
   + `bob-vr/bob-preview/*.png` (2 шт) — история в git их сохраняет; блобы раздувают репо. 🔴 **под
   подтверждение** (archive — намеренный; если хочешь сохранить — пропустим этот пункт).
5. **#29 — локальная чистка** `data/*.bak-pre-*` (~130МБ, НЕ в git): оставить 1–2 свежих, старые удалить
   локально. (Не репо-изменение — операционная гигиена.)
6. **#6 — .DS_Store:** проверено — уже в `.gitignore` (стр. 25), НЕ трекнут → **no-op** (аудит ① ошибся;
   на диске они есть, но игнорируются — не трогаем).

## Беады

- `.1` **dev** — выполнить чистку (git rm dialog/test, gitignore-правила worktrees+dialogue, git mv
  personality.md, [опц.] git rm archive-бинарники). Локальный `data/*.bak` прун — отдельным шагом.
- `.2` **review** — 🔴 убедиться, что удалено только реально ненужное (ничего важного/референсного не
  снесли), gitignore-правила корректны, `git status` чист, тесты/`beadloom ci` зелёные (переезд
  personality.md код не задевает).

## Критерии приёмки

- `dialog.txt`/`test.txt` удалены + покрыты gitignore; `personality.md` в `.claude/dev-docs/`;
  `.claude/worktrees/` игнорируется; (опц.) archive-бинарники убраны.
- Ничего важного не потеряно; `beadloom ci` + pytest зелёные; репо «только по делу».
- BOB-Issues #19–22 (+#6,#20,#29) закрыть/отметить в логе.

## Связи

BOB-Issues.md #19–22,#29,#20,#6 (Фаза 1). Параллельно с README (#23–24). Перед Фазой 2 (ports+layer-rule).
