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

🔴 **Названные границы** (ревью ``bob-ck4.3`` пробило гейт семью способами; три из них —
не дыры, а граница выразимости, и они названы здесь, чтобы их не читали как проверку):
``issue_key`` берётся из заголовка беады НА ВЕРУ — беада под чужим ключом пройдёт по чужой
папке (M-8); комплект документов диктуется ТИПОМ беады, поэтому эпик, заведённый как
``task``, спрошен будет как ``task`` (M-9); «место в карте» — упоминание ключа где угодно
в файле, включая таблицу ошибок (M-10). Всё это вопросы смысла: отличить их машинно можно
было бы только гаданием по форме прозы — тем самым классом гарда, который ``CLAUDE.md``
§0.3 п.12 запрещает. Остальные четыре обхода закрыты по-настоящему: строгий якорь даты
сверки, размер файла вместо имени, словарь статусов, обёртка-молекула.
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

# 🔴 Пол «документ, а не заглушка» — в БАЙТАХ, потому что `touch BRIEF.md ACTIVE.md`
# проходил гейт в одну команду (ревью bob-ck4.3, M-7): спрашивались только ИМЕНА файлов.
# Величина выбрана замером, а не на глаз: самая короткая живая ACTIVE.md в дереве на
# 2026-08-15 — 778 байт (BOB-084), медиана заметно больше. 200 байт — это примерно три
# строки прозы: с большим запасом ниже любого настоящего документа и заведомо выше пустого
# файла или строки-затычки. Гейт судит ЗАГЛУШКУ, а не краткость: содержательность
# документа машине недоступна, и порог не претендует её измерять.
MIN_SPEC_BYTES = 200

# Словарь статусов `bd` (`bd list --status`: open, in_progress, blocked, deferred, closed).
# 🔴 Зафиксирован явно, потому что «в работе» для гейта — РОВНО in_progress, и появление
# шестого статуса сделало бы работу под ним невидимой молча (ревью bob-ck4.3, M-12).
# `blocked` и `deferred` намеренно не считаются работой в работе: обе означают, что работа
# СТОИТ, — но незнакомый статус гейт судить отказывается и краснеет.
KNOWN_STATUSES: frozenset[str] = frozenset(
    {"open", "in_progress", "blocked", "deferred", "closed"}
)

# Ключ работы открывает заголовок корневой беады: «[BOB-098] …», «[BOB-048].7 …».
_KEY_RE = re.compile(r"^\s*\[(?P<key>[A-Z][A-Z0-9]*-\d+)\]")

# 🔴 ЯКОРЬ СВЕРКИ — именованная фраза целиком, а не корень «свер».
# Прежняя редакция искала `свер\w*` и брала максимум из всех дат строки; ревью пробило её
# живым прогоном дважды: «сверх плана на 2027-01-01» и «следующая сверка запланирована на
# 2027-03-01» гасили проверку свежести навсегда. Якорь — «сверено с main <штамп>» в ОДНОЙ
# строке (`[ \t]`, а не `\s`: иначе фраза склеивалась бы через перенос строки с чужой
# датой). Штамп берётся как есть и разбирается отдельно — чтобы опечатка стала вердиктом,
# а не голым ValueError из date() (M-11).
_SYNC_ANCHOR_RE = re.compile(r"сверено[ \t]+с[ \t]+main[ \t]+(?P<stamp>[^\s)»,;]+)", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"^(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})$")

# Обёртки, а не работа: `bd swarm` заводит молекулу поверх эпика, и сам эпик лежит в том
# же снимке отдельной беадой — она и проверяется. Требовать спеку с обёртки значит красить
# гейт на каждом рое. 🔴 Но обёртка освобождает ТОЛЬКО СЕБЯ: при подъёме к корню молекула
# перешагивается, иначе из проверок выпадала бы вся ветка под ней (ревью, M-13).
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
    """Работа в работе, у которой нет её документов.

    ``missing`` — документа нет вовсе; ``placeholders`` — файл есть, но он заглушка
    (меньше ``MIN_SPEC_BYTES``). Разведены, потому что лечатся разным: первое — завести
    документ, второе — дописать его.
    """

    issue_key: str | None
    root_id: str
    in_progress_beads: tuple[str, ...]
    missing: tuple[str, ...]
    placeholders: tuple[str, ...] = ()

    def __str__(self) -> str:
        beads = ", ".join(self.in_progress_beads)
        if self.issue_key is None:
            return (
                f"{beads}: в заголовке корневой беады {self.root_id} нет ключа вида "
                f"[BOB-NNN] — спеку негде искать. Переименуй беаду и заведи "
                f".claude/development/docs/features/{{ISSUE-KEY}}/"
            )
        faults: list[str] = []
        if self.missing:
            faults.append(f"не хватает {', '.join(self.missing)}")
        if self.placeholders:
            faults.append(
                f"заглушки вместо документов (меньше {MIN_SPEC_BYTES} байт): "
                f"{', '.join(self.placeholders)}"
            )
        return (
            f"{beads} ({self.issue_key}): в "
            f".claude/development/docs/features/{self.issue_key}/ {'; '.join(faults)}. "
            f"Спека пишется ПРИ ВЗЯТИИ в работу — собери её (/task-init) или сними беаду "
            f"со статуса in_progress"
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
class SyncClaim:
    """Утверждение карты о собственной свежести — разобранное СТРОГО.

    ``declared`` — дата, которую гейт принял; ``problems`` — почему не принял. Пустое и
    то и другое означает «карта о своей свежести молчит»: это тоже красное, но по другой
    причине, и человеку надо сказать разное.
    """

    declared: date | None
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class MapFreshness:
    """Насколько карта отстала от ``main`` по её же собственному утверждению."""

    claim: SyncClaim
    commits_since: int
    commit_limit: int

    @property
    def declared_date(self) -> date | None:
        return self.claim.declared

    @property
    def is_drifted(self) -> bool:
        return self.claim.declared is None or self.commits_since > self.commit_limit

    def explain(self) -> str:
        if self.claim.problems:
            return (
                "ROADMAP.md заявляет сверку негодным якорем: "
                + "; ".join(self.claim.problems)
                + ". Поставь «сверено с main YYYY-MM-DD» с настоящей (не будущей) датой "
                "той сверки, которая действительно состоялась"
            )
        if self.claim.declared is None:
            return (
                "ROADMAP.md не несёт даты сверки: строки вида «сверено с main YYYY-MM-DD» "
                "в файле нет. Без неё отставание карты невидимо — сверь карту с git log "
                "main и поставь дату"
            )
        return (
            f"ROADMAP.md сверен с main {self.claim.declared.isoformat()}, а после этого в "
            f"main приехало {self.commits_since} коммитов (порог {self.commit_limit}). "
            f"Пройди git log main --since={self.claim.declared.isoformat()}, обнови «Статус "
            f"отгрузки» и поставь новую дату «сверено с main YYYY-MM-DD»"
        )


def required_spec_files(kind: str) -> tuple[str, ...]:
    """Комплект документов по типу работы; незнакомый тип — минимум, а не пустота.

    🔴 Названная граница (M-9): «эпик это или задача» — суждение автора беады, машинного
    признака у него нет. Тип занижен в трекере — занижен и комплект; границу «что считать
    эпиком» держит честность автора, а не гейт.
    """
    return FULL_SPEC_SET if kind in _FULL_SET_KINDS else BRIEF_SPEC_SET


def unknown_statuses(items: Iterable[WorkItem]) -> tuple[str, ...]:
    """Статусы трекера, которых гейт не знает, — по одному разу и по алфавиту.

    🔴 Зачем: «в работе» для проверки 1 — ровно ``in_progress``. Появись у ``bd``
    шестой статус, работа под ним стала бы гейту невидимой МОЛЧА (ревью, M-12). Молчаливая
    неполнота — худший исход: зелёное, ничего не проверившее.
    """
    return tuple(sorted({item.status for item in items} - KNOWN_STATUSES))


def issue_key_of(title: str) -> str | None:
    """Ключ работы из заголовка беады; None — если заголовок его не несёт.

    🔴 Названная граница (M-8): ключ берётся НА ВЕРУ. «Тот ли это ключ» — вопрос смысла,
    и в трекере на него нет ответа: беада под чужим ключом пройдёт по чужой папке.
    """
    match = _KEY_RE.match(title)
    return match.group("key") if match else None


def root_of(item: WorkItem, index: Mapping[str, WorkItem]) -> WorkItem:
    """Корень работы: у среза своей папки нет, он живёт в папке родителя.

    🔴 Обёртку роя (``molecule``) подъём ПЕРЕШАГИВАЕТ — не поднимается в неё. Иначе корнем
    всей ветки становился контейнер, а контейнер спеки не требует, и из проверок молча
    выпадала вся настоящая работа под ним (ревью bob-ck4.3, M-13; сегодня риск спящий —
    у всех шести молекул ноль детей, — но спящий риск тем и опасен).
    """
    seen = {item.bead_id}
    current = item
    while current.parent_id is not None:
        parent = index.get(current.parent_id)
        if parent is None or parent.bead_id in seen or parent.kind in _CONTAINER_KINDS:
            break
        seen.add(parent.bead_id)
        current = parent
    return current


def spec_gaps(
    items: Iterable[WorkItem],
    list_spec_files: Callable[[str], Mapping[str, int]],
) -> tuple[SpecGap, ...]:
    """Работы В РАБОТЕ, у которых нет комплекта НАПИСАННЫХ документов по типу.

    ``list_spec_files`` отвечает на «что лежит в папке этого ключа»: имя файла → его
    размер в байтах (пустое отображение = папки нет). 🔴 Размер, а не только имя:
    ``touch BRIEF.md ACTIVE.md`` проходил гейт в одну команду (ревью, M-7). Срезы
    сворачиваются в корень: спрашивается ОДНА папка на работу и комплект по типу КОРНЯ.
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
        required = required_spec_files(root.kind)
        missing = tuple(name for name in required if name not in present)
        placeholders = tuple(
            name for name in required if name in present and present[name] < MIN_SPEC_BYTES
        )
        if missing or placeholders:
            gaps.append(SpecGap(key, root_id, bead_ids, missing, placeholders))
    return tuple(gaps)


def _parse_stamp(stamp: str, *, today: date) -> tuple[date | None, str | None]:
    """Штамп якоря → дата либо названная причина, почему она не годится."""
    iso = _ISO_DATE_RE.match(stamp)
    if iso is None:
        return None, f"«{stamp}» после «сверено с main» — не дата вида YYYY-MM-DD"
    try:
        parsed = date(int(iso.group("y")), int(iso.group("m")), int(iso.group("d")))
    except ValueError:
        return None, f"«{stamp}» — такой даты не существует"
    if parsed > today:
        return None, (
            f"«{stamp}» — дата из будущего: сверка, которая ещё не состоялась, "
            f"свежести карте не даёт"
        )
    return parsed, None


def read_sync_claim(roadmap_text: str, *, today: date) -> SyncClaim:
    """Утверждение карты о своей свежести: строгий разбор якоря «сверено с main <дата>».

    🔴 Почему строго. Прежняя редакция искала корень «свер» в строке и брала МАКСИМУМ из
    всех дат этой строки — и ревью (bob-ck4.3, MAJOR-2) выключило проверку живым прогоном
    двумя обычными фразами карты: «следующая сверка запланирована на 2027-03-01» и «сверх
    плана на 2027-01-01». Обе давали дату из будущего, счётчик коммитов отдавал ноль, и
    гейт зеленел НАВСЕГДА. Это класс ``CLAUDE.md`` §0.3 п.12 в чистом виде: гард читал
    форму текста — того самого текста, который обязан сторожить. Поэтому здесь: якорь —
    именованная фраза целиком, а не корень; дата обязана быть настоящей; будущая дата —
    не «свежесть», а названный дефект карты.

    🔴 Из годных дат берётся самая СВЕЖАЯ — по факту, а не из доверчивости. Правило
    проекта требует править неверное ВИДИМО, поэтому карта честно цитирует прежний якорь
    («до этой даты карта была помечена „сверено с main 2026-06-25“»). По самой старой
    такая карта краснела бы вечно — гейт наказывал бы ровно ту практику, ради которой
    заведён, и его выключили бы первым же раздражением. Остаточная слабость названа
    прямо: заявление о свежести — утверждение ЧЕЛОВЕКА, и поставить сегодняшнюю дату, не
    сверив карту, можно при любом разборе. Гейт делает это утверждение существующим и
    измеримым, а не правдивым.
    """
    candidates: list[date] = []
    problems: list[str] = []
    for line in roadmap_text.splitlines():
        for match in _SYNC_ANCHOR_RE.finditer(line):
            parsed, problem = _parse_stamp(match.group("stamp"), today=today)
            if parsed is not None:
                candidates.append(parsed)
            if problem is not None:
                problems.append(problem)
    if problems:
        return SyncClaim(declared=None, problems=tuple(problems))
    return SyncClaim(declared=max(candidates) if candidates else None)


def map_freshness(
    roadmap_text: str,
    count_commits_since: Callable[[date], int],
    *,
    commit_limit: int,
    today: date,
) -> MapFreshness:
    """Отставание карты: сколько коммитов приехало в main после её даты сверки."""
    claim = read_sync_claim(roadmap_text, today=today)
    commits = count_commits_since(claim.declared) if claim.declared is not None else 0
    return MapFreshness(claim=claim, commits_since=commits, commit_limit=commit_limit)


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

    🔴 Названная граница (M-10): «место в карте» — упоминание ключа ГДЕ УГОДНО в файле,
    включая таблицу «что карта утверждала неверно». То есть проверяется ВИДИМОСТЬ работы
    в карте, а не её место в плане; отличить одно от другого можно было бы только
    разбором прозы. Ключ при этом ищется как ЦЕЛОЕ СЛОВО: подстрока «BOB-09» находилась
    внутри «BOB-098» и давала работе чужое место.
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
        if key is None or not _mentions_key(roadmap_text, key):
            gaps.append(MapGap(key, root_id, root.title, bead_ids))
    return tuple(gaps)


def _mentions_key(text: str, key: str) -> bool:
    """Карта называет ключ как целое слово (а не как часть более длинного номера)."""
    return re.search(rf"\b{re.escape(key)}\b", text) is not None
