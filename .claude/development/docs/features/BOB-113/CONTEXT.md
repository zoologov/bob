<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-113

> **Status:** Approved
> **Created:** 2026-10-21
> **PRD:** [PRD.md](PRD.md) · **RFC:** [RFC.md](RFC.md) · **PLAN:** [PLAN.md](PLAN.md)
> **Ветка:** `features/BOB-113` от `features/BOB-112` (коммит `bd7e877`), PR в `features/BOB-112`

---

## Где мы

- BOB-112 (beadloom 2.1.0 → 9.0.0) закоммичен срезами `.1` и `.2` на `features/BOB-112`.
  На чистом индексе релизным 9.0.0: `sync-check` 0, `docs audit` 0, `doctor` без графовых
  предупреждений, **`lint --strict` красный только циклами** — 904 строки, 15 пар, все из
  type-only импортов. Эта работа возвращает lint в 0 **на `error`**.
- Решение owner'а (2026-10-21): **без полумер** — никакого `warn`/`exempt`/`until`.
  Зафиксировано в `CLAUDE.md` §0.2, проектном слое `.beadloom/flow/claude/CLAUDE.md` и в
  памяти агента. Любой агент этой работы читает §0.2 «Без полумер» как часть задания.
- Инструмент: **`uvx --from beadloom==9.0.0 beadloom …`** для всего, что судит дерево.
  Локальный editable из `~/beadloom` — не для гейтов Боба (та же сборка, что CI/VPS, иначе
  «у меня зелено» ничего не доказывает).

## Решения (из RFC, кратко — полный разбор там)

- Runtime-порядок вертикалей — константа этой работы:
  `usecases → capabilities → social → telegram → proactivity → memory → runtime-app → conversation → personality`.
- Три исхода по предпочтению: **владельцу → `ports.py` вертикали → kernel** (ISP-Protocol у
  потребителя — когда нужен один метод/поле).
- 22 имени: A (2) владельцу · B (6) в `social/ports.py` и `personality/ports.py` · C (13) в
  `kernel/{events,ports,episode_types,modulators}.py` · D (7) социальный словарь в
  `kernel/{interlocutor,relationship,roster,sulk}.py` · E (1) `VerifySearch` в `conversation/ports.py`.
- **Ни одного ре-экспорта по старому пути.** Один дом у каждого имени.
- **Поведение не меняется.** Diff тестов — только пути импорта и патчи `monkeypatch` по новым
  путям; ни один ассерт не ослабляется.

## Стандарты

- Python 3.12+, `ruff check src/ tests/` (без `ruff format` на дереве — репо не format-clean,
  §7 CLAUDE.md), `mypy --strict` на `src/` и `tests/`.
- DDD + Clean Architecture Боба: вертикали `domain + usecases/ + adapters/ + ports.py`;
  `kernel` — инфра-нейтральные кросс-модульные контракты, **импортирует только stdlib/typing**.
- Коммиты `[BOB-113] <type>: …` на `features/BOB-113`, одна волна — один коммит; длинные
  тексты только через файл (`git commit -F`, `bd comments add "$(cat …)"` — §0.3 п.11).
- Чекпоинты: `bd comments add <bead> "CHECKPOINT: …"` каждые ~5 шагов; ACTIVE.md после каждой
  волны.

## Гейты каждой волны (не только в конце)

```bash
uv run pytest -q -rs -p no:randomly            # полный прогон — патчи по старым путям mypy не ловит
uv run ruff check src/ tests/ && uv run mypy src/ && uv run mypy tests/
rm -f .beadloom/beadloom.db && uvx --from beadloom==9.0.0 beadloom reindex \
  && uvx --from beadloom==9.0.0 beadloom lint --strict --no-reindex      # число cycle-строк ↓ каждую волну
uv run pytest -q tests/test_no_runtime_import_cycles.py
```

После волны в ACTIVE — **числа**: производных рёбер / type-only рёбер / cycle-строк /
пар циклов. Не цвет.

## Ловушки этого места

- **`handle_message.py` — 2426 строк, оркестратор всего.** Из него уходят только объявления
  (9 Protocol + 2 dataclass). Не переписывать, не «заодно» чистить; diff должен читаться по
  именам.
- **Тесты патчат по строковым путям** (`monkeypatch.setattr("bob.social.interlocutor.…")`).
  mypy/ruff их не видят → полный `pytest` после каждого переезда, а не в конце.
- **`Gender`**: переезжает только Enum; `detect_self_gender`/`GenderRead` (логика
  самоидентификации BOB-078) остаются в `social/gender.py` и импортируют Enum из kernel.
- **`Relationship.__post_init__`** — валидация полей, не поведение; переезжает с dataclass.
  `RelationshipDeltas`, `apply_interaction` и пр. — остаются в social.
- **`events.py` переезжает целиком** (две сущности, одна ответственность). 21 src + 61 tests
  импорт-сайтов — механика; делать скриптом по списку, затем ruff/mypy/pytest.
- **Докстринги со старыми путями** (`:class:`~bob.social.interlocutor.Interlocutor``) —
  `docs audit`/`sync-check` 9.0.0 их читают; править в той же волне.
- **`rules.yml` генерируется** `scripts/gen_boundary_rules.py` для boundary-правил — если
  переезд потребует правки правил (не должен: kernel уже разрешённая цель), только через
  генератор (`--check` исполняется тестом).
- **Сосед по дереву — BOB-112 `.3`/`.4`** (проектный слой, сайт) ещё не делались; эта работа
  не трогает `.claude/`, `.beadloom/flow/`, `site/`.
