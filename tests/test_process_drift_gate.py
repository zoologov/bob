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
(``tests/support/test_process_coherence.py``, 65 сценариев) — здесь проверяется, что она
подключена к реальности, включая отдельный анти-вакуумный тест: гейт, который ничего не
прочитал, зелёный ровно так же, как гейт, которому нечего сказать.

🔴 **Где трекера структурно нет — честный SKIP с причиной, а не ERROR и не тихое зелёное.**
Первая редакция роняла три теста из четырёх в ``ERROR`` везде, где нет ``bd`` и базы: в
отдельном клоне, в котором работает Боб-кодер (``git clone file://…``, решение BOB-089), и
на будущем раннере CI (BOB-095). Гейт, краснеющий НЕ ПО ДЕЛУ, выключают первым же
раздражением — и мы возвращаемся туда, откуда пришли. Но тихое зелёное было бы ХУЖЕ
красного: оно утверждало бы проверку, которой не было (``§0.3`` п.1). Поэтому разведены
две вещи: «инструмента/базы тут нет» → ``skip`` с текстом «согласованность НЕ
проверялась»; «инструмент есть и ответил ошибкой» → красное.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from functools import cache
from pathlib import Path

import pytest

from tests.support.process_coherence import (
    MIN_SPEC_BYTES,
    WorkItem,
    map_freshness,
    spec_gaps,
    unknown_statuses,
    work_missing_from_map,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FEATURES_DIR = _REPO_ROOT / ".claude" / "development" / "docs" / "features"
_ROADMAP = _REPO_ROOT / ".claude" / "dev-docs" / "ROADMAP.md"
_BEADS_DIR = _REPO_ROOT / ".beads"

# 🔴 ПОРОГ СВЕЖЕСТИ КАРТЫ — в КОММИТАХ main, не в днях, и вот почему.
# Карта гниёт от ОТГРУЖЕННОГО, а не от календаря: тихая неделя её не портит, слитые эпики
# — портят. Замер на этом репозитории (2026-08-15): 165 коммитов в main за 1–15 августа,
# 149 за июль, 335 с даты сверки 2026-06-25 — то есть ~5–6 коммитов в день.
# 🔴 Обоснование поправлено по замеру (ревью bob-ck4.3): здесь стояло «60 ≈ три
# отгруженных эпика ≈ ~20 коммитов на эпик» — это не подтвердилось. Пять последних слияний
# эпиков принесли 8, 15, 7, 10 и 10 коммитов, то есть 60 ≈ четыре-восемь эпиков ≈ 10–14
# дней текущего темпа. Само число остаётся разумным: меньше (скажем, 20) — гейт краснел бы после
# каждого эпика и превратился бы в шум, который выключают; больше (150) — снова разрешили
# бы месяц дрейфа. И важное свойство: пока работа идёт на своей ветке, её коммиты в main не
# приезжают, поэтому счётчик не дёргает эпик в середине.
# 🔴 Настоящий риск порога — не шум, а цена выхода из красного: честная сверка карты стоит
# волны работы, а дешёвый выход — правка одной даты, и этого гейт не различает. Он держит
# ВИДИМОСТЬ утверждения о свежести, а не его правдивость (см. read_sync_claim).
MAX_MAIN_COMMITS_SINCE_MAP_SYNC = 60

# `bd list` по умолчанию отдаёт ТОЛЬКО 50 записей (флаг --limit) и БЕЗ закрытых.
# Оба умолчания сделали бы гейт тихо-неполным, поэтому оба сняты явно.
_BD_LIST_ARGV = ("bd", "list", "--all", "--limit", "0", "--json")


class CheckNotPossibleError(RuntimeError):
    """Проверять структурно НЕЧЕМ (нет инструмента, нет базы, нет ``main``) — это SKIP.

    Не «всё хорошо», а «не проверялось»: причина уходит в текст пропуска целиком, чтобы
    зелёный прогон нигде не читался как подтверждение согласованности.
    """


class CheckBrokenError(RuntimeError):
    """Инструмент на месте, но ответил ошибкой — это КРАСНОЕ, а не пропуск."""


def _tracker_database_present() -> bool:
    """Есть ли в этом дереве база трекера (а не только её экспорт в ``.beads/*.jsonl``).

    Проверяется ФАКТ наличия базы, а не текст ошибки ``bd``: разбирать stderr значило бы
    судить по форме сообщения — тот же класс, что и остальные находки этой работы.
    База под ``.gitignore`` (``.beads/embeddeddolt``), поэтому в свежем клоне её нет.
    """
    if not _BEADS_DIR.is_dir():
        return False
    return (_BEADS_DIR / "embeddeddolt").is_dir() or any(_BEADS_DIR.glob("*.db"))


@cache
def _tracker_snapshot() -> tuple[WorkItem, ...]:
    """Живой снимок трекера через настоящий ``bd`` (§0.3 п.4: не фейк и не экспорт).

    ``@cache`` замораживает состояние в пределах прогона намеренно: иначе тесты одного
    прогона судили бы по разным снимкам и могли бы разъезжаться между собой.
    """
    if not _tracker_database_present():
        raise CheckNotPossibleError(
            f"в этом дереве нет базы трекера ({_BEADS_DIR}/embeddeddolt) — "
            f"согласованность трекера, спек и карты НЕ ПРОВЕРЯЛАСЬ. Это нормально в клоне "
            f"Боба-кодера и на раннере CI; в основном репозитории — повод насторожиться"
        )
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированный read-only argv, без shell
            _BD_LIST_ARGV,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CheckNotPossibleError(
            "не найден bd (beads CLI) — согласованность трекера, спек и карты НЕ "
            "ПРОВЕРЯЛАСЬ. Поставь beads CLI, если это основной репозиторий"
        ) from exc
    except subprocess.TimeoutExpired as exc:  # pragma: no cover — залипший dolt
        raise CheckBrokenError("bd list не ответил за 45 с") from exc

    if proc.returncode != 0:  # pragma: no cover — сломанная база
        raise CheckBrokenError(f"bd list вернул {proc.returncode}: {proc.stderr.strip()[:400]}")

    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover — смена формата bd
        raise CheckBrokenError(f"bd list --json отдал не JSON: {proc.stdout[:200]!r}") from exc

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


def _spec_files_of(issue_key: str) -> dict[str, int]:
    """Что реально лежит в папке спеки этого ключа: имя файла → размер (пусто — папки нет).

    Размер, а не только имя: ``touch BRIEF.md ACTIVE.md`` проходил гейт в одну команду.
    """
    folder = _FEATURES_DIR / issue_key
    if not folder.is_dir():
        return {}
    return {path.name: path.stat().st_size for path in folder.iterdir() if path.is_file()}


def _main_refs() -> tuple[str, ...]:
    """Все доступные представления ``main`` — локальное и удалённое.

    🔴 Оба, а не первое попавшееся: локальный ``main`` без ``git fetch`` умеет отстать от
    ``origin/main``, и счётчик тогда ЗАНИЖАЛ бы отставание карты — то есть гейт молча
    зеленел бы (ревью bob-ck4.3, «хрупкость к окружению»). Ложное зелёное здесь опаснее
    ложного красного.
    """
    refs = tuple(
        ref
        for ref in ("main", "origin/main")
        if subprocess.run(  # noqa: S603 — фиксированный read-only argv, без shell
            ["git", "rev-parse", "--verify", "--quiet", ref],  # noqa: S607 — git через PATH
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).returncode
        == 0
    )
    if not refs:
        raise CheckNotPossibleError(
            "в репозитории нет ни main, ни origin/main — свежесть карты НЕ ПРОВЕРЯЛАСЬ"
        )
    return refs


def _count_main_commits_since(since: date) -> int:
    """Сколько коммитов приехало в ``main`` с полуночи даты сверки.

    🔴 Время суток задано явно (``00:00:00``): ``--since=<голая дата>`` — approxidate, и
    git разворачивает её в «эта дата, ТЕКУЩЕЕ время суток». Счётчик не видел коммиты дня
    сверки, сделанные раньше часа прогона, и зависел от того, когда запущен (ревью, M-6).
    """
    counts: list[int] = []
    for ref in _main_refs():
        proc = subprocess.run(  # noqa: S603 — фиксированный read-only argv, без shell
            ["git", "rev-list", "--count", ref, f"--since={since.isoformat()} 00:00:00"],  # noqa: S607
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:  # pragma: no cover — сломанный git
            raise CheckBrokenError(f"git rev-list вернул {proc.returncode}: {proc.stderr.strip()}")
        counts.append(int(proc.stdout.strip() or 0))
    return max(counts)


@pytest.fixture
def tracker() -> tuple[WorkItem, ...]:
    """Снимок трекера — либо честный пропуск с причиной, если трекера тут нет."""
    try:
        return _tracker_snapshot()
    except CheckNotPossibleError as exc:
        pytest.skip(str(exc))


def test_every_bead_in_progress_has_its_spec(tracker: tuple[WorkItem, ...]) -> None:
    """🔴 Проверка 1: у работы В РАБОТЕ есть её документы — комплект по типу.

    Срез (``bob-xxx.N``) сворачивается в корень по родительской связи трекера: своей папки
    у него нет, он живёт в папке родителя. Гейт, искавший бы папку под ключом среза,
    краснел бы на каждой волне и был бы выключен первым же раздражением.
    """
    items = tracker
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

    Трекер этой проверке не нужен — она живёт и в клоне без базы беад; но без ``main`` и
    ``origin/main`` сверять не с чем, и это честный пропуск, а не зелёное.
    """
    try:
        _main_refs()
    except CheckNotPossibleError as exc:
        pytest.skip(str(exc))
    verdict = map_freshness(
        _ROADMAP.read_text(encoding="utf-8"),
        _count_main_commits_since,
        commit_limit=MAX_MAIN_COMMITS_SINCE_MAP_SYNC,
        today=date.today(),  # noqa: DTZ011 — локальная дата репозитория, как у git --since
    )
    assert not verdict.is_drifted, verdict.explain()


def test_every_open_p0_p1_work_has_a_place_in_the_map(tracker: tuple[WorkItem, ...]) -> None:
    """🔴 Проверка 3: незакрытая работа P0/P1 названа в карте (сверка односторонняя).

    Планируем мы по карте — работа, которой в ней нет, планированию невидима. Обратная
    сторона (пункт карты «в работе» → беада) не проверяется осознанно: у пунктов карты нет
    машинного признака состояния, и угадывание его по форме прозы — ровно тот класс гарда,
    который §0.3 п.12 запрещает.
    """
    gaps = work_missing_from_map(tracker, _ROADMAP.read_text(encoding="utf-8"))
    assert not gaps, (
        "Открытая работа P0/P1 без места в карте (.claude/dev-docs/ROADMAP.md):\n  - "
        + "\n  - ".join(str(gap) for gap in gaps)
    )


def test_the_gate_reads_the_live_tracker_tree_and_git(tracker: tuple[WorkItem, ...]) -> None:
    """🔴 Анти-вакуум: гейт, ничего не прочитавший, зелен ровно как гейт без замечаний.

    Поэтому здесь пинается сама проводка — что снимок трекера полон, что поиск папки
    РАЗЛИЧАЕТ существующую и несуществующую работу, и что счётчик коммитов живой. Без
    этого «зелёное» ничего не значит (§0.3 п.5: «не зелёное» ≠ «покраснело», и наоборот).
    """
    items = tracker
    assert len(items) > 50, (
        f"снимок трекера подозрительно мал ({len(items)}): у `bd list` умолчание --limit 50, "
        "и гейт судил бы по обрезку"
    )
    assert any(item.status == "closed" for item in items), (
        "в снимке нет закрытых беад — значит --all не подействовал, и родителей срезов "
        "было бы не разрешить"
    )
    strangers = unknown_statuses(items)
    assert not strangers, (
        f"трекер отдаёт статусы, которых гейт не знает: {', '.join(strangers)}. «В работе» "
        "для проверки 1 — ровно in_progress, поэтому работа под новым статусом стала бы "
        "невидимой МОЛЧА. Реши, что этот статус значит, и внеси его в KNOWN_STATUSES"
    )

    existing = sorted(path.name for path in _FEATURES_DIR.iterdir() if path.is_dir())
    assert existing, "дерево спек пусто — поиск папки нечем проверить"
    files = _spec_files_of(existing[-1])
    assert files, f"живой поиск не видит файлов в {existing[-1]}"
    assert max(files.values()) >= MIN_SPEC_BYTES, (
        f"живой поиск отдаёт размеры {files} — ни один документ в {existing[-1]} не дотягивает "
        f"до порога заглушки: либо порог оторван от реальности, либо размеры не читаются"
    )
    assert _spec_files_of("BOB-000-НЕСУЩЕСТВУЮЩАЯ") == {}, (
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
