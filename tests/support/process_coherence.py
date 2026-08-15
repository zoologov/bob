# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Вердикты о согласованности трекера, дерева спек и дорожной карты (BOB-098, волна 1б).

Одна ответственность: **сказать, разъехались ли состояние трекера, дерево спек и карта** —
и назвать виновника поимённо. Ввод и вывод чистые: беады приходят готовыми записями,
файловая система и ``git`` — функциями обратного вызова. Поэтому логику можно пинать
синтетическим дрейфом (``test_process_coherence.py``), а живую проводку — отдельно
(``tests/test_process_drift_gate.py``).

Зачем модуль вообще существует: правило «волна не запускается, пока у работы нет её
документов» вписано в ``CLAUDE.md`` §3, но у него не было гейта — и август уехал. Пять
работ подряд (BOB-092…095, 097) завелись беадами без единого документа, а ``ROADMAP.md``
отстал на семь недель. Утверждение без проверки гниёт.

🔴 Честная граница вердиктов. Машина не умеет проверить, что карта описывает реальность
ПО СМЫСЛУ. Здесь проверяется слабее и честнее: карта несёт **фальсифицируемое
утверждение** о своей свежести (дату сверки), и это утверждение сверяется с числом
коммитов, приехавших в ``main`` после него; а трекер и дерево сверяются по факту наличия.
Смысловую правду карты держит человек — гейт держит её ВИДИМОСТЬ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

# Комплект по типу работы — CLAUDE.md §3 «Спека — источник, беада — состояние».
FULL_SPEC_SET: tuple[str, ...] = ("PRD.md", "RFC.md", "CONTEXT.md", "PLAN.md", "ACTIVE.md")
BRIEF_SPEC_SET: tuple[str, ...] = ("BRIEF.md", "ACTIVE.md")
_FULL_SET_KINDS = frozenset({"epic", "feature"})

# Ключ работы открывает заголовок корневой беады: «[BOB-098] …», «[BOB-048].7 …».
_KEY_RE = re.compile(r"^\s*\[(?P<key>[A-Z][A-Z0-9]*-\d+)\]")

# Строка сверки карты: слово с корнем «свер» и ISO-дата в одной строке.
_SYNC_LINE_RE = re.compile(r"свер\w*", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})")

# Обёртки, а не работа: `bd swarm` заводит молекулу поверх эпика, и сам эпик лежит в том
# же снимке отдельной беадой — она и проверяется. Требовать спеку с обёртки значит красить
# гейт на каждом рое.
_CONTAINER_KINDS = frozenset({"molecule"})

_ACTIVE_STATUS = "in_progress"
_CLOSED_STATUS = "closed"
_PLANNING_PRIORITIES: tuple[int, ...] = (0, 1)


@dataclass(frozen=True)
class WorkItem:
    """Беада как СОСТОЯНИЕ работы — ровно те поля, по которым судит гейт."""

    bead_id: str
    title: str
    kind: str
    status: str
    priority: int
    parent_id: str | None = None


@dataclass(frozen=True)
class SpecGap:
    """Работа в работе, у которой нет её документов."""

    issue_key: str | None
    root_id: str
    in_progress_beads: tuple[str, ...]
    missing: tuple[str, ...]

    def __str__(self) -> str:
        beads = ", ".join(self.in_progress_beads)
        if self.issue_key is None:
            return (
                f"{beads}: в заголовке корневой беады {self.root_id} нет ключа вида "
                f"[BOB-NNN] — спеку негде искать. Переименуй беаду и заведи "
                f".claude/development/docs/features/{{ISSUE-KEY}}/"
            )
        return (
            f"{beads} ({self.issue_key}): в "
            f".claude/development/docs/features/{self.issue_key}/ не хватает "
            f"{', '.join(self.missing)}. Спека пишется ПРИ ВЗЯТИИ в работу — "
            f"собери её (/task-init) или сними беаду со статуса in_progress"
        )


@dataclass(frozen=True)
class MapGap:
    """Открытая работа P0/P1, которой нет места в карте."""

    issue_key: str | None
    root_id: str
    root_title: str
    beads: tuple[str, ...]

    def __str__(self) -> str:
        beads = ", ".join(self.beads)
        if self.issue_key is None:
            return (
                f"{beads}: у корневой беады {self.root_id} нет ключа [BOB-NNN] — "
                f"её нечем найти в карте ({self.root_title})"
            )
        return (
            f"{self.issue_key} ({self.root_title}) — беады {beads}: карта о работе молчит. "
            f"Впиши её в ROADMAP.md (тир или раздел незакрытых линий) либо закрой беаду"
        )


@dataclass(frozen=True)
class MapFreshness:
    """Насколько карта отстала от ``main`` по её же собственному утверждению."""

    declared_date: date | None
    commits_since: int
    commit_limit: int

    @property
    def is_drifted(self) -> bool:
        return self.declared_date is None or self.commits_since > self.commit_limit

    def explain(self) -> str:
        if self.declared_date is None:
            return (
                "ROADMAP.md не несёт даты сверки: строки вида «сверено с main YYYY-MM-DD» "
                "в файле нет. Без неё отставание карты невидимо — сверь карту с git log "
                "main и поставь дату"
            )
        return (
            f"ROADMAP.md сверен с main {self.declared_date.isoformat()}, а после этого в "
            f"main приехало {self.commits_since} коммитов (порог {self.commit_limit}). "
            f"Пройди git log main --since={self.declared_date.isoformat()}, обнови «Статус "
            f"отгрузки» и поставь новую дату «сверено с main YYYY-MM-DD»"
        )


def required_spec_files(kind: str) -> tuple[str, ...]:
    """Комплект документов по типу работы; незнакомый тип — минимум, а не пустота."""
    return FULL_SPEC_SET if kind in _FULL_SET_KINDS else BRIEF_SPEC_SET


def issue_key_of(title: str) -> str | None:
    """Ключ работы из заголовка беады; None — если заголовок его не несёт."""
    match = _KEY_RE.match(title)
    return match.group("key") if match else None


def root_of(item: WorkItem, index: Mapping[str, WorkItem]) -> WorkItem:
    """Корень работы: у среза своей папки нет, он живёт в папке родителя."""
    seen = {item.bead_id}
    current = item
    while current.parent_id is not None:
        parent = index.get(current.parent_id)
        if parent is None or parent.bead_id in seen:
            break
        seen.add(parent.bead_id)
        current = parent
    return current


def spec_gaps(
    items: Iterable[WorkItem],
    list_spec_files: Callable[[str], frozenset[str]],
) -> tuple[SpecGap, ...]:
    """Работы В РАБОТЕ, у которых нет комплекта документов по типу.

    ``list_spec_files`` отвечает на «какие файлы лежат в папке этого ключа» (пустое
    множество = папки нет). Срезы сворачиваются в корень: спрашивается ОДНА папка на
    работу и комплект по типу КОРНЯ.
    """
    index = {item.bead_id: item for item in items}
    running: dict[str, list[WorkItem]] = {}
    for item in index.values():
        if item.status != _ACTIVE_STATUS:
            continue
        running.setdefault(root_of(item, index).bead_id, []).append(item)

    gaps: list[SpecGap] = []
    for root_id, beads in sorted(running.items()):
        root = index[root_id]
        if root.kind in _CONTAINER_KINDS:
            continue
        key = issue_key_of(root.title)
        bead_ids = tuple(sorted(bead.bead_id for bead in beads))
        if key is None:
            gaps.append(SpecGap(None, root_id, bead_ids, required_spec_files(root.kind)))
            continue
        present = list_spec_files(key)
        missing = tuple(name for name in required_spec_files(root.kind) if name not in present)
        if missing:
            gaps.append(SpecGap(key, root_id, bead_ids, missing))
    return tuple(gaps)


def read_declared_sync_date(roadmap_text: str) -> date | None:
    """Дата сверки, которую карта заявляет о себе; самая СВЕЖАЯ из заявленных.

    🔴 Самая свежая — по факту, а не из доверчивости. Первая редакция брала самую старую
    (анти-игра: «свежую строку сверху приписать дёшево»), и живая карта тут же показала,
    чем это кончается: правило проекта требует править неверное ВИДИМО, поэтому в шапке
    честно сохранены «Предыдущая сверка — 2026-06-25» и «Отгружено после прежней сверки».
    По «самой старой» такая карта краснеет вечно — то есть гейт наказывал бы ровно ту
    практику, ради которой заведён, и его выключили бы первым же раздражением.
    Заявление о свежести — утверждение человека; гейт делает его существующим и
    измеримым, а не правдивым: соврать в дате можно и при любом выборе.
    """
    declared: list[date] = []
    for line in roadmap_text.splitlines():
        if not _SYNC_LINE_RE.search(line):
            continue
        declared.extend(
            date(int(year), int(month), int(day))
            for year, month, day in _ISO_DATE_RE.findall(line)
        )
    return max(declared) if declared else None


def map_freshness(
    roadmap_text: str,
    count_commits_since: Callable[[date], int],
    *,
    commit_limit: int,
) -> MapFreshness:
    """Отставание карты: сколько коммитов приехало в main после её даты сверки."""
    declared = read_declared_sync_date(roadmap_text)
    commits = count_commits_since(declared) if declared is not None else 0
    return MapFreshness(declared_date=declared, commits_since=commits, commit_limit=commit_limit)


def work_missing_from_map(
    items: Iterable[WorkItem],
    roadmap_text: str,
    *,
    priorities: tuple[int, ...] = _PLANNING_PRIORITIES,
) -> tuple[MapGap, ...]:
    """Незакрытые работы P0/P1, которых карта не называет.

    🔴 Сверка ОДНОСТОРОННЯЯ (трекер → карта) осознанно. Обратная сторона — «пункт карты
    в работе имеет беаду» — не выражается без разбора свободной прозы: у пунктов карты нет
    машинного признака «в работе», а угадывание его по форме текста — ровно тот класс
    гарда, который CLAUDE.md §0.3 п.12 запрещает (проверяли бы форму, а не факт). И шум
    был бы асимметричным: карта законно поминает сотни отгруженных ключей. Направление
    трекер → карта — то самое, по которому уехал август: работа шла, а карта, по которой
    мы планируем, о ней молчала.
    """
    index = {item.bead_id: item for item in items}
    pending: dict[str, list[WorkItem]] = {}
    for item in index.values():
        if item.status == _CLOSED_STATUS or item.priority not in priorities:
            continue
        pending.setdefault(root_of(item, index).bead_id, []).append(item)

    gaps: list[MapGap] = []
    for root_id, beads in sorted(pending.items()):
        root = index[root_id]
        if root.kind in _CONTAINER_KINDS:
            continue
        key = issue_key_of(root.title)
        bead_ids = tuple(sorted(bead.bead_id for bead in beads))
        if key is None or key not in roadmap_text:
            gaps.append(MapGap(key, root_id, root.title, bead_ids))
    return tuple(gaps)
