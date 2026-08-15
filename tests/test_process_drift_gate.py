# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 Гейт против дрейфа процесса: трекер, дерево спек и карта не разъезжаются молча.

Правило «волна не запускается, пока у работы нет её документов» вписано в ``CLAUDE.md`` §3
13 августа — и осталось УТВЕРЖДЕНИЕМ. Без проверки утверждение гниёт: пять работ подряд
(BOB-092…095, 097) завелись беадами без единого документа, а ``ROADMAP.md`` семь недель
носил «сверено с main 2026-06-25», пока в ``main`` приезжало 335 коммитов. Здесь у правила
появляются зубы (BOB-098, беада ``bob-ck4.2``).

**Почему тест, а не правило ``beadloom lint`` и не шаг ``beadloom ci``.** Правила
``.beadloom/_graph/rules.yml`` судят АРХИТЕКТУРНЫЙ ГРАФ — узлы и рёбра, поднятые из
``src/``; примитивов (``require``/``forbid_import``/``check``…) хватает на «модуль
классифицирован», но не на «у беады в работе есть папка спеки»: ни трекера, ни
``.claude/`` граф не видит. ``beadloom ci`` — фиксированная композиция апстрима
(reindex → lint → sync-check → config-check → federate), своего шага туда не вставить, не
форкая инструмент. А ``uv run pytest`` гоняет КАЖДАЯ роль в своём гейт-цикле и
перепроверяет координатор на финальном дереве (``CLAUDE.md`` §0.3 п.8) — то есть тест
исполняется ровно там, где дрейф и заводится. Отдельный ``scripts/*.sh`` был бы гейтом,
которого никто не запускает.

**Гейт судит ПОВЕДЕНИЕ, а не форму текста** (``CLAUDE.md`` §0.3 п.12). Источник состояния —
живой ``bd`` (не экспортированный ``.beads/issues.jsonl``: снимок умеет отстать от базы, и
гейт унаследовал бы его иллюзии), живое дерево ``.claude/development/docs/features/`` и
живой ``git log main``. Логика вердиктов лежит отдельно
(``tests/support/process_coherence.py``) и пинается синтетическим дрейфом
(``tests/support/test_process_coherence.py``, 41 сценарий) — здесь проверяется, что она
подключена к реальности, включая отдельный анти-вакуумный тест: гейт, который ничего не
прочитал, зелёный ровно так же, как гейт, которому нечего сказать.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from functools import cache
from pathlib import Path

from tests.support.process_coherence import (
    WorkItem,
    map_freshness,
    spec_gaps,
    work_missing_from_map,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FEATURES_DIR = _REPO_ROOT / ".claude" / "development" / "docs" / "features"
_ROADMAP = _REPO_ROOT / ".claude" / "dev-docs" / "ROADMAP.md"

# 🔴 ПОРОГ СВЕЖЕСТИ КАРТЫ — в КОММИТАХ main, не в днях, и вот почему.
# Карта гниёт от ОТГРУЖЕННОГО, а не от календаря: тихая неделя её не портит, три слитых
# эпика — портят. Замер на этом репозитории (2026-08-15): 165 коммитов в main за 1–15
# августа, 149 за июль, 335 с даты сверки 2026-06-25 — то есть ~5 коммитов в день и ~20
# коммитов на отгруженный эпик (эпик приезжает в main историей ветки, не сквошем).
# 60 ≈ три отгруженных эпика ≈ двенадцать дней текущего темпа. Меньше (скажем, 20) —
# гейт краснел бы после каждого эпика и превратился бы в шум, который выключают; больше
# (150) — снова разрешили бы месяц дрейфа. И важное свойство: пока работа идёт на своей
# ветке, её коммиты в main не приезжают, поэтому счётчик не дёргает эпик в середине.
MAX_MAIN_COMMITS_SINCE_MAP_SYNC = 60

# `bd list` по умолчанию отдаёт ТОЛЬКО 50 записей (флаг --limit) и БЕЗ закрытых.
# Оба умолчания сделали бы гейт тихо-неполным, поэтому оба сняты явно.
_BD_LIST_ARGV = ("bd", "list", "--all", "--limit", "0", "--json")


class TrackerUnavailableError(RuntimeError):
    """Состояние трекера прочитать не удалось — это КРАСНОЕ, а не пропуск."""


@cache
def _tracker_snapshot() -> tuple[WorkItem, ...]:
    """Живой снимок трекера через настоящий ``bd`` (§0.3 п.4: не фейк и не экспорт)."""
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированный read-only argv, без shell
            _BD_LIST_ARGV,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover — среда без bd
        raise TrackerUnavailableError(
            "не найден bd: состояние трекера непроверяемо. Поставь beads CLI — "
            "процессный гейт BOB-098 без него не судит, а молчит"
        ) from exc
    except subprocess.TimeoutExpired as exc:  # pragma: no cover — залипший dolt
        raise TrackerUnavailableError("bd list не ответил за 45 с") from exc

    if proc.returncode != 0:  # pragma: no cover — сломанная база
        raise TrackerUnavailableError(
            f"bd list вернул {proc.returncode}: {proc.stderr.strip()[:400]}"
        )

    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover — смена формата bd
        raise TrackerUnavailableError(
            f"bd list --json отдал не JSON: {proc.stdout[:200]!r}"
        ) from exc

    return tuple(
        WorkItem(
            bead_id=str(entry["id"]),
            title=str(entry.get("title", "")),
            kind=str(entry.get("issue_type", "")),
            status=str(entry.get("status", "")),
            priority=int(entry.get("priority", 3)),
            parent_id=(str(entry["parent"]) if entry.get("parent") else None),
        )
        for entry in raw
    )


def _spec_files_of(issue_key: str) -> frozenset[str]:
    """Что реально лежит в папке спеки этого ключа (пусто — папки нет)."""
    folder = _FEATURES_DIR / issue_key
    if not folder.is_dir():
        return frozenset()
    return frozenset(path.name for path in folder.iterdir() if path.is_file())


def _main_ref() -> str:
    for ref in ("main", "origin/main"):
        proc = subprocess.run(  # noqa: S603 — фиксированный read-only argv, без shell
            ["git", "rev-parse", "--verify", "--quiet", ref],  # noqa: S607 — git через PATH
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode == 0:
            return ref
    raise TrackerUnavailableError(
        "в репозитории нет ни main, ни origin/main — не с чем сверять карту"
    )


def _count_main_commits_since(since: date) -> int:
    proc = subprocess.run(  # noqa: S603 — фиксированный read-only argv, без shell
        ["git", "rev-list", "--count", _main_ref(), f"--since={since.isoformat()}"],  # noqa: S607
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:  # pragma: no cover — сломанный git
        raise TrackerUnavailableError(
            f"git rev-list вернул {proc.returncode}: {proc.stderr.strip()}"
        )
    return int(proc.stdout.strip() or 0)


def test_every_bead_in_progress_has_its_spec() -> None:
    """🔴 Проверка 1: у работы В РАБОТЕ есть её документы — комплект по типу.

    Срез (``bob-xxx.N``) сворачивается в корень по родительской связи трекера: своей папки
    у него нет, он живёт в папке родителя. Гейт, искавший бы папку под ключом среза,
    краснел бы на каждой волне и был бы выключен первым же раздражением.
    """
    items = _tracker_snapshot()
    gaps = spec_gaps(items, _spec_files_of)
    running = [item.bead_id for item in items if item.status == "in_progress"]
    assert not gaps, (
        "Работа идёт без спеки (CLAUDE.md §3 — «волна не запускается, пока у работы нет её "
        f"документов»). В работе {len(running)} беад: {', '.join(sorted(running))}.\n  - "
        + "\n  - ".join(str(gap) for gap in gaps)
    )


def test_roadmap_declares_a_sync_date_that_main_has_not_outrun() -> None:
    """🔴 Проверка 2: карта несёт дату сверки, и её отставание от main видно.

    Смысловую правду карты машина не проверит. Проверяется слабее и честнее: карта делает
    ФАЛЬСИФИЦИРУЕМОЕ утверждение о своей свежести, а гейт считает, сколько работы приехало
    в main после него.
    """
    verdict = map_freshness(
        _ROADMAP.read_text(encoding="utf-8"),
        _count_main_commits_since,
        commit_limit=MAX_MAIN_COMMITS_SINCE_MAP_SYNC,
    )
    assert not verdict.is_drifted, verdict.explain()


def test_every_open_p0_p1_work_has_a_place_in_the_map() -> None:
    """🔴 Проверка 3: незакрытая работа P0/P1 названа в карте (сверка односторонняя).

    Планируем мы по карте — работа, которой в ней нет, планированию невидима. Обратная
    сторона (пункт карты «в работе» → беада) не проверяется осознанно: у пунктов карты нет
    машинного признака состояния, и угадывание его по форме прозы — ровно тот класс гарда,
    который §0.3 п.12 запрещает.
    """
    gaps = work_missing_from_map(_tracker_snapshot(), _ROADMAP.read_text(encoding="utf-8"))
    assert not gaps, (
        "Открытая работа P0/P1 без места в карте (.claude/dev-docs/ROADMAP.md):\n  - "
        + "\n  - ".join(str(gap) for gap in gaps)
    )


def test_the_gate_reads_the_live_tracker_tree_and_git() -> None:
    """🔴 Анти-вакуум: гейт, ничего не прочитавший, зелен ровно как гейт без замечаний.

    Поэтому здесь пинается сама проводка — что снимок трекера полон, что поиск папки
    РАЗЛИЧАЕТ существующую и несуществующую работу, и что счётчик коммитов живой. Без
    этого «зелёное» ничего не значит (§0.3 п.5: «не зелёное» ≠ «покраснело», и наоборот).
    """
    items = _tracker_snapshot()
    assert len(items) > 50, (
        f"снимок трекера подозрительно мал ({len(items)}): у `bd list` умолчание --limit 50, "
        "и гейт судил бы по обрезку"
    )
    assert any(item.status == "closed" for item in items), (
        "в снимке нет закрытых беад — значит --all не подействовал, и родителей срезов "
        "было бы не разрешить"
    )

    existing = sorted(path.name for path in _FEATURES_DIR.iterdir() if path.is_dir())
    assert existing, "дерево спек пусто — поиск папки нечем проверить"
    assert _spec_files_of(existing[-1]), f"живой поиск не видит файлов в {existing[-1]}"
    assert _spec_files_of("BOB-000-НЕСУЩЕСТВУЮЩАЯ") == frozenset(), (
        "поиск папки отвечает одинаково на существующую и несуществующую работу — "
        "проверка 1 была бы вакуумной"
    )

    probe = WorkItem(
        bead_id="probe-vacuum",
        title="[BOB-000] работа без спеки",
        kind="feature",
        status="in_progress",
        priority=1,
    )
    assert spec_gaps([*items, probe], _spec_files_of), (
        "вердикт проверки 1 не краснеет даже на беаде в работе с заведомо отсутствующей "
        "папкой — гейт не работает"
    )

    since_forever = _count_main_commits_since(date(2020, 1, 1))
    assert since_forever > 0, "счётчик коммитов main молчит — проверке 2 не на что опереться"
    assert since_forever >= _count_main_commits_since(date.today()), (  # noqa: DTZ011
        "счётчик коммитов не убывает с датой — он считает не то"
    )
