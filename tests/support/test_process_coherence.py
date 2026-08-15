# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Вердикты согласованности — проверка на КУСАЧЕСТЬ (BOB-098, волна 1б).

Здесь пинается сама логика гейта: на согласованном состоянии она молчит, на дрейфе —
называет виновника. Живая проводка (настоящий ``bd``, настоящее дерево, настоящий
``git``) пинается отдельно, в ``tests/test_process_drift_gate.py``: это разные вопросы —
«вердикт умеет краснеть» и «вердикт подключён к реальности».
"""

from __future__ import annotations

from datetime import date

from tests.support.process_coherence import (
    BRIEF_SPEC_SET,
    FULL_SPEC_SET,
    WorkItem,
    issue_key_of,
    map_freshness,
    read_declared_sync_date,
    required_spec_files,
    root_of,
    spec_gaps,
    work_missing_from_map,
)


def _item(
    bead_id: str,
    *,
    title: str = "[BOB-900] работа",
    kind: str = "task",
    status: str = "in_progress",
    priority: int = 1,
    parent_id: str | None = None,
) -> WorkItem:
    return WorkItem(
        bead_id=bead_id,
        title=title,
        kind=kind,
        status=status,
        priority=priority,
        parent_id=parent_id,
    )


class TestRequiredSpecFiles:
    """Комплект документов диктуется ТИПОМ работы (CLAUDE.md §3)."""

    def test_epic_and_feature_need_the_full_set(self) -> None:
        assert required_spec_files("epic") == FULL_SPEC_SET
        assert required_spec_files("feature") == FULL_SPEC_SET

    def test_bug_task_chore_need_brief_and_active(self) -> None:
        assert required_spec_files("bug") == BRIEF_SPEC_SET
        assert required_spec_files("task") == BRIEF_SPEC_SET
        assert required_spec_files("chore") == BRIEF_SPEC_SET

    def test_unknown_type_falls_back_to_the_minimum_set(self) -> None:
        # Незнакомый тип не должен ослаблять гейт до нуля: минимум BRIEF + ACTIVE.
        assert required_spec_files("molecule") == BRIEF_SPEC_SET


class TestIssueKey:
    """Ключ работы живёт в заголовке корневой беады — и у срезов он с суффиксом."""

    def test_plain_key(self) -> None:
        assert issue_key_of("[BOB-098] Актуализировать ROADMAP") == "BOB-098"

    def test_slice_suffix_after_the_bracket(self) -> None:
        assert issue_key_of("[BOB-048].7 tech-writer — architecture.md") == "BOB-048"

    def test_title_without_a_key(self) -> None:
        assert issue_key_of("Волна 1б: гейт против дрейфа") is None

    def test_key_must_open_the_title(self) -> None:
        # Упоминание чужого ключа в середине заголовка ключом работы не является.
        assert issue_key_of("починка по мотивам [BOB-089]") is None


class TestRootResolution:
    """🔴 Ловушка со срезами: у среза своей папки нет, он живёт в папке родителя."""

    def test_slice_resolves_to_its_parent(self) -> None:
        root = _item("bob-ck4", title="[BOB-098] карта", kind="chore")
        slice_ = _item("bob-ck4.2", title="Волна 1б", parent_id="bob-ck4")
        assert root_of(slice_, {"bob-ck4": root, "bob-ck4.2": slice_}) is root

    def test_two_level_chain_resolves_to_the_top(self) -> None:
        root = _item("a", title="[BOB-900] эпик", kind="epic")
        mid = _item("a.1", title="срез", parent_id="a")
        leaf = _item("a.1.1", title="под-срез", parent_id="a.1")
        index = {"a": root, "a.1": mid, "a.1.1": leaf}
        assert root_of(leaf, index) is root

    def test_broken_chain_stops_at_the_last_known_item(self) -> None:
        orphan = _item("x.1", title="срез", parent_id="ghost")
        assert root_of(orphan, {"x.1": orphan}) is orphan

    def test_parent_cycle_does_not_hang(self) -> None:
        left = _item("l", parent_id="r")
        right = _item("r", parent_id="l")
        assert root_of(left, {"l": left, "r": right}).bead_id in {"l", "r"}


class TestSpecGaps:
    """Проверка 1: у работы В РАБОТЕ есть папка спеки с комплектом по типу."""

    def test_silent_when_the_full_set_is_in_place(self) -> None:
        epic = _item("e", title="[BOB-900] эпик", kind="epic")
        assert spec_gaps([epic], lambda _key: frozenset(FULL_SPEC_SET)) == ()

    def test_names_the_missing_files_of_a_feature(self) -> None:
        feature = _item("f", title="[BOB-900] фича", kind="feature")
        present = frozenset({"PRD.md", "CONTEXT.md", "PLAN.md", "ACTIVE.md"})
        gaps = spec_gaps([feature], lambda _key: present)
        assert len(gaps) == 1
        assert gaps[0].issue_key == "BOB-900"
        assert gaps[0].missing == ("RFC.md",)

    def test_chore_with_brief_and_active_is_enough(self) -> None:
        chore = _item("c", title="[BOB-098] уборка", kind="chore")
        assert spec_gaps([chore], lambda _key: frozenset(BRIEF_SPEC_SET)) == ()

    def test_absent_folder_reports_the_whole_set(self) -> None:
        chore = _item("c", title="[BOB-098] уборка", kind="chore")
        gaps = spec_gaps([chore], lambda _key: frozenset())
        assert len(gaps) == 1
        assert gaps[0].missing == BRIEF_SPEC_SET

    def test_slice_is_looked_up_under_the_parent_key(self) -> None:
        # 🔴 Ловушка: гейт, ищущий папку «bob-ck4.2» или «BOB-098.2», краснел бы на
        # каждом срезе — и его выключили бы первым же раздражением.
        root = _item("bob-ck4", title="[BOB-098] карта", kind="chore")
        slice_ = _item("bob-ck4.2", title="Волна 1б", parent_id="bob-ck4")
        asked: list[str] = []

        def lookup(key: str) -> frozenset[str]:
            asked.append(key)
            return frozenset(BRIEF_SPEC_SET)

        assert spec_gaps([root, slice_], lookup) == ()
        assert set(asked) == {"BOB-098"}

    def test_slice_inherits_the_requirement_of_its_root_type(self) -> None:
        # Срез — task, но родитель — эпик: спрашивается ПОЛНЫЙ комплект.
        root = _item("e", title="[BOB-900] эпик", kind="epic")
        slice_ = _item("e.1", title="волна 1", kind="task", parent_id="e")
        gaps = spec_gaps([root, slice_], lambda _key: frozenset(BRIEF_SPEC_SET))
        assert len(gaps) == 1
        assert set(gaps[0].missing) == set(FULL_SPEC_SET) - set(BRIEF_SPEC_SET)

    def test_one_finding_per_work_even_with_several_slices_running(self) -> None:
        root = _item("e", title="[BOB-900] эпик", kind="epic", status="in_progress")
        first = _item("e.1", title="волна 1", parent_id="e")
        second = _item("e.2", title="волна 2", parent_id="e")
        gaps = spec_gaps([root, first, second], lambda _key: frozenset())
        assert len(gaps) == 1
        assert gaps[0].in_progress_beads == ("e", "e.1", "e.2")

    def test_swarm_molecule_is_a_container_not_a_work_item(self) -> None:
        # `bd swarm` заводит молекулу-обёртку («Swarm: [BOB-066] …»); сам эпик лежит в
        # том же снимке отдельной беадой и проверяется по-настоящему. Требовать папку и
        # с обёртки — гарантированное ложное красное на каждом рое.
        molecule = _item("s", title="Swarm: [BOB-066] эпик", kind="molecule")
        assert spec_gaps([molecule], lambda _key: frozenset()) == ()

    def test_open_work_not_yet_started_needs_no_spec(self) -> None:
        # Спека пишется ПРИ ВЗЯТИИ в работу, а не заранее на весь бэклог (CLAUDE.md §3).
        planned = _item("p", title="[BOB-900] потом", kind="feature", status="open")
        assert spec_gaps([planned], lambda _key: frozenset()) == ()

    def test_closed_work_is_not_reopened_by_the_gate(self) -> None:
        done = _item("d", title="[BOB-900] отгружено", kind="feature", status="closed")
        assert spec_gaps([done], lambda _key: frozenset()) == ()

    def test_work_in_progress_without_a_key_is_red(self) -> None:
        # Беаду без ключа негде искать в дереве спек — это тот же дрейф.
        nameless = _item("n", title="просто задача", kind="task")
        gaps = spec_gaps([nameless], lambda _key: frozenset(BRIEF_SPEC_SET))
        assert len(gaps) == 1
        assert gaps[0].issue_key is None
        assert "ключ" in str(gaps[0])

    def test_the_message_names_the_folder_and_the_missing_files(self) -> None:
        feature = _item("f", title="[BOB-900] фича", kind="feature")
        gaps = spec_gaps([feature], lambda _key: frozenset())
        message = str(gaps[0])
        assert "BOB-900" in message
        assert "PRD.md" in message


class TestDeclaredSyncDate:
    """Проверка 2, часть 1: карта несёт дату сверки."""

    def test_reads_the_declared_date(self) -> None:
        text = "## Статус отгрузки (сверено с main 2026-06-25)\n"
        assert read_declared_sync_date(text) == date(2026, 6, 25)

    def test_absent_marker_reads_as_none(self) -> None:
        assert read_declared_sync_date("# Карта\n\nПросто текст 2026-06-25\n") is None

    def test_the_newest_marker_wins(self) -> None:
        # 🔴 Живой случай: правило проекта требует править неверное ВИДИМО, поэтому карта
        # честно хранит «Предыдущая сверка — 2026-06-25» рядом со свежей датой. По самой
        # старой дате такая карта краснела бы вечно — гейт наказывал бы честную практику.
        text = (
            "## Статус отгрузки (сверено с main 2026-08-15)\n"
            "> Предыдущая сверка — 2026-06-25 (PR #74).\n"
        )
        assert read_declared_sync_date(text) == date(2026, 8, 15)

    def test_several_dates_on_one_marker_line(self) -> None:
        text = "### Отгружено после прежней сверки (2026-06-26 … 2026-08-15)\n"
        assert read_declared_sync_date(text) == date(2026, 8, 15)

    def test_marker_needs_a_date_on_the_same_line(self) -> None:
        assert read_declared_sync_date("сверено с main недавно\n") is None


class TestMapFreshness:
    """Проверка 2, часть 2: отставание карты от main ВИДНО и названо порогом."""

    def test_fresh_map_is_not_drifted(self) -> None:
        verdict = map_freshness(
            "сверено с main 2026-08-15\n", lambda _d: 12, commit_limit=60
        )
        assert not verdict.is_drifted
        assert verdict.commits_since == 12

    def test_map_outrun_by_main_is_drifted(self) -> None:
        verdict = map_freshness(
            "сверено с main 2026-06-25\n", lambda _d: 335, commit_limit=60
        )
        assert verdict.is_drifted
        assert "335" in verdict.explain()
        assert "60" in verdict.explain()

    def test_exactly_at_the_limit_is_still_green(self) -> None:
        verdict = map_freshness("сверено с main 2026-08-01\n", lambda _d: 60, commit_limit=60)
        assert not verdict.is_drifted

    def test_map_without_a_date_is_drifted(self) -> None:
        verdict = map_freshness("# Карта без даты\n", lambda _d: 0, commit_limit=60)
        assert verdict.is_drifted
        assert verdict.declared_date is None

    def test_explanation_says_what_to_do(self) -> None:
        verdict = map_freshness("# Карта без даты\n", lambda _d: 0, commit_limit=60)
        assert "сверено с main" in verdict.explain()


class TestWorkMissingFromMap:
    """Проверка 3: открытая работа P0/P1 имеет место в карте."""

    def test_silent_when_the_map_names_the_key(self) -> None:
        item = _item("a", title="[BOB-101] живая речь", kind="feature", status="open")
        assert work_missing_from_map([item], "Тир 1 … BOB-101 живая речь\n") == ()

    def test_names_the_work_the_map_forgot(self) -> None:
        item = _item("a", title="[BOB-094] VPS", kind="feature", status="open")
        gaps = work_missing_from_map([item], "Карта без него\n")
        assert len(gaps) == 1
        assert gaps[0].issue_key == "BOB-094"
        assert "BOB-094" in str(gaps[0])

    def test_low_priority_work_is_not_demanded_from_the_map(self) -> None:
        item = _item("a", title="[BOB-900] мелочь", kind="task", status="open", priority=2)
        assert work_missing_from_map([item], "Карта без него\n") == ()

    def test_closed_work_is_not_demanded_from_the_map(self) -> None:
        item = _item("a", title="[BOB-900] отгружено", status="closed")
        assert work_missing_from_map([item], "Карта без него\n") == ()

    def test_in_progress_work_is_demanded_too(self) -> None:
        item = _item("a", title="[BOB-098] карта", kind="chore", status="in_progress")
        gaps = work_missing_from_map([item], "Карта без него\n")
        assert len(gaps) == 1

    def test_slices_collapse_into_one_finding_for_the_root_key(self) -> None:
        root = _item("m", title="[BOB-048] мульти-репо", kind="feature", status="open")
        first = _item("m.5", title="test", status="open", parent_id="m")
        second = _item("m.6", title="review", status="open", parent_id="m")
        gaps = work_missing_from_map([root, first, second], "пусто\n")
        assert len(gaps) == 1
        assert gaps[0].beads == ("m", "m.5", "m.6")

    def test_swarm_molecule_is_not_demanded_from_the_map(self) -> None:
        molecule = _item("s", title="Swarm: [BOB-066] эпик", kind="molecule", status="open")
        assert work_missing_from_map([molecule], "пусто\n") == ()

    def test_open_work_without_a_key_has_no_place_in_the_map_either(self) -> None:
        nameless = _item("n", title="безымянная работа", status="open")
        gaps = work_missing_from_map([nameless], "пусто\n")
        assert len(gaps) == 1
        assert gaps[0].issue_key is None
