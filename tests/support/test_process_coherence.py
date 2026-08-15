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
    MIN_SPEC_BYTES,
    WorkItem,
    issue_key_of,
    map_freshness,
    read_sync_claim,
    required_spec_files,
    root_of,
    spec_gaps,
    unknown_statuses,
    work_missing_from_map,
)

_TODAY = date(2026, 8, 15)


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


def _written(*names: str, size: int = 4096) -> dict[str, int]:
    """Папка спеки, в которой лежат НАПИСАННЫЕ документы (имя → размер в байтах)."""
    return dict.fromkeys(names, size)


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

    def test_known_limit_an_epic_filed_as_a_chore_is_asked_only_for_a_brief(self) -> None:
        # 🔴 НАЗВАННАЯ ГРАНИЦА (ревью bob-ck4.3, M-9), а не недосмотр: «эпик это или
        # задача» — суждение автора беады, машинного признака у него нет. Гейт судит по
        # ТИПУ в трекере; тип занижен — занижен и комплект. Тест держит границу видимой:
        # если её однажды закроют, он покраснеет и заставит переписать честную оговорку.
        assert required_spec_files("chore") == BRIEF_SPEC_SET
        assert "PRD.md" not in required_spec_files("chore")
        assert len(required_spec_files("chore")) < len(FULL_SPEC_SET)


class TestUnknownStatuses:
    """🔴 Словарь статусов не расширяется молча (ревью bob-ck4.3, M-12).

    «В работе» для гейта — ровно ``in_progress``. Появись у ``bd`` шестой статус
    (``in_review``, ``paused``…) — работа под ним стала бы гейту невидимой, и никто бы
    этого не заметил: проверка молча зеленела бы. Поэтому незнакомый статус — красное.
    """

    def test_silent_on_the_known_vocabulary(self) -> None:
        items = [
            _item("a", status="open"),
            _item("b", status="in_progress"),
            _item("c", status="blocked"),
            _item("d", status="deferred"),
            _item("e", status="closed"),
        ]
        assert unknown_statuses(items) == ()

    def test_names_a_status_the_gate_does_not_classify(self) -> None:
        items = [_item("a", status="in_review"), _item("b", status="open")]
        assert unknown_statuses(items) == ("in_review",)

    def test_each_unknown_status_is_named_once_and_sorted(self) -> None:
        items = [
            _item("a", status="paused"),
            _item("b", status="in_review"),
            _item("c", status="paused"),
        ]
        assert unknown_statuses(items) == ("in_review", "paused")


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

    def test_a_molecule_over_the_epic_is_stepped_over_not_taken_as_root(self) -> None:
        # 🔴 Ревью bob-ck4.3, M-13: корень-молекула освобождал ВСЮ ветку. `bd swarm`
        # заводит обёртку поверх эпика, обёртка спеки не требует — и вместе с ней из
        # проверки выпадала вся настоящая работа под ней. Молекулу перешагиваем: корень
        # работы — самый верхний НЕ-контейнер.
        molecule = _item("s", title="Swarm: [BOB-900] эпик", kind="molecule")
        epic = _item("e", title="[BOB-900] эпик", kind="epic", parent_id="s")
        slice_ = _item("e.1", title="волна 1", parent_id="e")
        index = {"s": molecule, "e": epic, "e.1": slice_}
        assert root_of(slice_, index) is epic
        assert root_of(epic, index) is epic


class TestSpecGaps:
    """Проверка 1: у работы В РАБОТЕ есть папка спеки с комплектом по типу."""

    def test_silent_when_the_full_set_is_in_place(self) -> None:
        epic = _item("e", title="[BOB-900] эпик", kind="epic")
        assert spec_gaps([epic], lambda _key: _written(*FULL_SPEC_SET)) == ()

    def test_names_the_missing_files_of_a_feature(self) -> None:
        feature = _item("f", title="[BOB-900] фича", kind="feature")
        present = _written("PRD.md", "CONTEXT.md", "PLAN.md", "ACTIVE.md")
        gaps = spec_gaps([feature], lambda _key: present)
        assert len(gaps) == 1
        assert gaps[0].issue_key == "BOB-900"
        assert gaps[0].missing == ("RFC.md",)

    def test_chore_with_brief_and_active_is_enough(self) -> None:
        chore = _item("c", title="[BOB-098] уборка", kind="chore")
        assert spec_gaps([chore], lambda _key: _written(*BRIEF_SPEC_SET)) == ()

    def test_absent_folder_reports_the_whole_set(self) -> None:
        chore = _item("c", title="[BOB-098] уборка", kind="chore")
        gaps = spec_gaps([chore], lambda _key: {})
        assert len(gaps) == 1
        assert gaps[0].missing == BRIEF_SPEC_SET

    def test_touched_empty_files_are_a_placeholder_not_a_spec(self) -> None:
        # 🔴 Ревью bob-ck4.3, M-7: гейт спрашивал только ИМЕНА, поэтому
        # `touch BRIEF.md ACTIVE.md` проходил — обход в одну команду. Комплект — это
        # написанные документы, а не имена файлов.
        chore = _item("c", title="[BOB-098] уборка", kind="chore")
        gaps = spec_gaps([chore], lambda _key: _written(*BRIEF_SPEC_SET, size=0))
        assert len(gaps) == 1
        assert gaps[0].placeholders == BRIEF_SPEC_SET
        assert gaps[0].missing == ()
        assert "заглушк" in str(gaps[0])

    def test_a_file_just_under_the_floor_is_still_a_placeholder(self) -> None:
        chore = _item("c", title="[BOB-098] уборка", kind="chore")
        present = _written("BRIEF.md", size=MIN_SPEC_BYTES - 1) | _written("ACTIVE.md")
        gaps = spec_gaps([chore], lambda _key: present)
        assert len(gaps) == 1
        assert gaps[0].placeholders == ("BRIEF.md",)

    def test_a_file_at_the_floor_counts_as_written(self) -> None:
        chore = _item("c", title="[BOB-098] уборка", kind="chore")
        present = _written(*BRIEF_SPEC_SET, size=MIN_SPEC_BYTES)
        assert spec_gaps([chore], lambda _key: present) == ()

    def test_absent_and_placeholder_files_are_reported_apart(self) -> None:
        feature = _item("f", title="[BOB-900] фича", kind="feature")
        present = _written("PRD.md", "RFC.md", "CONTEXT.md") | _written("PLAN.md", size=0)
        gaps = spec_gaps([feature], lambda _key: present)
        assert gaps[0].missing == ("ACTIVE.md",)
        assert gaps[0].placeholders == ("PLAN.md",)
        message = str(gaps[0])
        assert "ACTIVE.md" in message
        assert "PLAN.md" in message

    def test_known_limit_the_key_is_taken_on_trust_from_the_title(self) -> None:
        # 🔴 НАЗВАННАЯ ГРАНИЦА (ревью bob-ck4.3, M-8): беада, озаглавленная чужим ключом,
        # проходит по чужой папке. «Тот ли это ключ» — вопрос смысла, машине он не задан
        # ни в трекере, ни в дереве. Гейт держит НАЛИЧИЕ спеки, а не её принадлежность;
        # тест фиксирует границу явно, чтобы её не приняли за проверку.
        impostor = _item("x", title="[BOB-096] на самом деле другая работа", kind="task")
        assert spec_gaps([impostor], lambda _key: _written(*BRIEF_SPEC_SET)) == ()

    def test_slice_is_looked_up_under_the_parent_key(self) -> None:
        # 🔴 Ловушка: гейт, ищущий папку «bob-ck4.2» или «BOB-098.2», краснел бы на
        # каждом срезе — и его выключили бы первым же раздражением.
        root = _item("bob-ck4", title="[BOB-098] карта", kind="chore")
        slice_ = _item("bob-ck4.2", title="Волна 1б", parent_id="bob-ck4")
        asked: list[str] = []

        def lookup(key: str) -> dict[str, int]:
            asked.append(key)
            return _written(*BRIEF_SPEC_SET)

        assert spec_gaps([root, slice_], lookup) == ()
        assert set(asked) == {"BOB-098"}

    def test_slice_inherits_the_requirement_of_its_root_type(self) -> None:
        # Срез — task, но родитель — эпик: спрашивается ПОЛНЫЙ комплект.
        root = _item("e", title="[BOB-900] эпик", kind="epic")
        slice_ = _item("e.1", title="волна 1", kind="task", parent_id="e")
        gaps = spec_gaps([root, slice_], lambda _key: _written(*BRIEF_SPEC_SET))
        assert len(gaps) == 1
        assert set(gaps[0].missing) == set(FULL_SPEC_SET) - set(BRIEF_SPEC_SET)

    def test_one_finding_per_work_even_with_several_slices_running(self) -> None:
        root = _item("e", title="[BOB-900] эпик", kind="epic", status="in_progress")
        first = _item("e.1", title="волна 1", parent_id="e")
        second = _item("e.2", title="волна 2", parent_id="e")
        gaps = spec_gaps([root, first, second], lambda _key: {})
        assert len(gaps) == 1
        assert gaps[0].in_progress_beads == ("e", "e.1", "e.2")

    def test_swarm_molecule_is_a_container_not_a_work_item(self) -> None:
        # `bd swarm` заводит молекулу-обёртку («Swarm: [BOB-066] …»); сам эпик лежит в
        # том же снимке отдельной беадой и проверяется по-настоящему. Требовать папку и
        # с обёртки — гарантированное ложное красное на каждом рое.
        molecule = _item("s", title="Swarm: [BOB-066] эпик", kind="molecule")
        assert spec_gaps([molecule], lambda _key: {}) == ()

    def test_a_molecule_does_not_free_the_work_under_it(self) -> None:
        # 🔴 Ревью bob-ck4.3, M-13: обёртка освобождала себя И всю ветку под собой.
        molecule = _item("s", title="Swarm: [BOB-900] эпик", kind="molecule")
        epic = _item("e", title="[BOB-900] эпик", kind="epic", parent_id="s")
        gaps = spec_gaps([molecule, epic], lambda _key: {})
        assert len(gaps) == 1
        assert gaps[0].root_id == "e"
        assert gaps[0].missing == FULL_SPEC_SET

    def test_open_work_not_yet_started_needs_no_spec(self) -> None:
        # Спека пишется ПРИ ВЗЯТИИ в работу, а не заранее на весь бэклог (CLAUDE.md §3).
        planned = _item("p", title="[BOB-900] потом", kind="feature", status="open")
        assert spec_gaps([planned], lambda _key: {}) == ()

    def test_closed_work_is_not_reopened_by_the_gate(self) -> None:
        done = _item("d", title="[BOB-900] отгружено", kind="feature", status="closed")
        assert spec_gaps([done], lambda _key: {}) == ()

    def test_work_in_progress_without_a_key_is_red(self) -> None:
        # Беаду без ключа негде искать в дереве спек — это тот же дрейф.
        nameless = _item("n", title="просто задача", kind="task")
        gaps = spec_gaps([nameless], lambda _key: _written(*BRIEF_SPEC_SET))
        assert len(gaps) == 1
        assert gaps[0].issue_key is None
        assert "ключ" in str(gaps[0])

    def test_the_message_names_the_folder_and_the_missing_files(self) -> None:
        feature = _item("f", title="[BOB-900] фича", kind="feature")
        gaps = spec_gaps([feature], lambda _key: {})
        message = str(gaps[0])
        assert "BOB-900" in message
        assert "PRD.md" in message


class TestSyncClaim:
    """🔴 Проверка 2, часть 1: карта несёт ЯКОРЬ сверки, и он разбирается строго.

    Первая редакция искала корень «свер» и брала максимум из всех дат строки — и ревью
    (bob-ck4.3, MAJOR-2) пробило её живым прогоном ДВАЖДЫ: фраза «сверх плана на
    2027-01-01» и фраза «следующая сверка запланирована на 2027-03-01» гасили проверку
    свежести НАВСЕГДА, без единого красного сигнала. Это ровно класс ``CLAUDE.md`` §0.3
    п.12 — гард читал ФОРМУ текста, который сам же обязан сторожить.

    Теперь якорь один и явный — фраза «сверено с main <ISO-дата>» в одной строке, — а
    дата обязана быть настоящей и не из будущего.
    """

    def test_reads_the_anchored_claim(self) -> None:
        text = "## Статус отгрузки (сверено с main 2026-06-25)\n"
        assert read_sync_claim(text, today=_TODAY).declared == date(2026, 6, 25)

    def test_a_bare_date_is_not_a_claim(self) -> None:
        claim = read_sync_claim("# Карта\n\nПросто текст 2026-06-25\n", today=_TODAY)
        assert claim.declared is None
        assert claim.problems == ()

    def test_bypass_1_a_planned_next_sync_does_not_speak_for_the_map(self) -> None:
        # 🔴 ОБХОД РЕВЬЮ №1 (живой прогон): строка «следующая сверка запланирована на
        # 2027-03-01» давала гейту дату из будущего → 0 коммитов → вечное зелёное.
        text = (
            "## Статус отгрузки (сверено с main 2026-06-25)\n"
            "Следующая сверка запланирована на 2027-03-01.\n"
        )
        assert read_sync_claim(text, today=_TODAY).declared == date(2026, 6, 25)

    def test_bypass_2_the_word_sverh_is_not_a_sync_marker(self) -> None:
        # 🔴 ОБХОД РЕВЬЮ №2 (живой прогон): «сверх плана на 2027-01-01 — переезд на VPS»
        # попадал под корень «свер\\w*» и выключал проверку одной обычной фразой карты.
        text = (
            "## Статус отгрузки (сверено с main 2026-06-25)\n"
            "Сверх плана на 2027-01-01 — переезд на VPS.\n"
        )
        assert read_sync_claim(text, today=_TODAY).declared == date(2026, 6, 25)

    def test_a_future_claim_is_refused_and_named(self) -> None:
        # Прямая подделка якоря будущим числом теперь не «свежесть», а красное.
        claim = read_sync_claim("сверено с main 2027-03-01\n", today=_TODAY)
        assert claim.declared is None
        assert len(claim.problems) == 1
        assert "2027-03-01" in claim.problems[0]

    def test_todays_claim_is_accepted(self) -> None:
        claim = read_sync_claim("сверено с main 2026-08-15\n", today=_TODAY)
        assert claim.declared == _TODAY

    def test_a_malformed_date_is_a_verdict_not_a_crash(self) -> None:
        # 🔴 Ревью M-11: опечатка роняла тест голым ValueError из date(), и сообщение
        # гейта в этот момент не звучало вовсе.
        claim = read_sync_claim("сверено с main 2026-13-45\n", today=_TODAY)
        assert claim.declared is None
        assert len(claim.problems) == 1
        assert "2026-13-45" in claim.problems[0]

    def test_the_newest_anchor_wins(self) -> None:
        # 🔴 Живой случай: правило проекта требует править неверное ВИДИМО, поэтому карта
        # честно цитирует прежний якорь рядом со свежим. По самой старой дате такая карта
        # краснела бы вечно — гейт наказывал бы честную практику и был бы выключен.
        text = (
            "## Статус отгрузки (сверено с main 2026-08-15)\n"
            "> До этой даты карта была помечена «сверено с main 2026-06-25».\n"
        )
        assert read_sync_claim(text, today=_TODAY).declared == date(2026, 8, 15)

    def test_dates_next_to_the_anchor_line_do_not_win(self) -> None:
        # Соседняя дата в той же строке якорем не является: якорь — фраза, а не строка.
        text = "### Отгружено после прежней сверки (2026-06-26 … 2026-08-15)\n"
        assert read_sync_claim(text, today=_TODAY).declared is None

    def test_the_anchor_needs_a_date_on_the_same_line(self) -> None:
        claim = read_sync_claim("сверено с main\n2026-08-15\n", today=_TODAY)
        assert claim.declared is None
        assert claim.problems == ()

    def test_an_unreadable_stamp_after_the_anchor_is_named(self) -> None:
        claim = read_sync_claim("сверено с main недавно\n", today=_TODAY)
        assert claim.declared is None
        assert len(claim.problems) == 1
        assert "недавно" in claim.problems[0]


class TestMapFreshness:
    """Проверка 2, часть 2: отставание карты от main ВИДНО и названо порогом."""

    def test_fresh_map_is_not_drifted(self) -> None:
        verdict = map_freshness(
            "сверено с main 2026-08-15\n", lambda _d: 12, commit_limit=60, today=_TODAY
        )
        assert not verdict.is_drifted
        assert verdict.commits_since == 12

    def test_map_outrun_by_main_is_drifted(self) -> None:
        verdict = map_freshness(
            "сверено с main 2026-06-25\n", lambda _d: 335, commit_limit=60, today=_TODAY
        )
        assert verdict.is_drifted
        assert "335" in verdict.explain()
        assert "60" in verdict.explain()

    def test_exactly_at_the_limit_is_still_green(self) -> None:
        verdict = map_freshness(
            "сверено с main 2026-08-01\n", lambda _d: 60, commit_limit=60, today=_TODAY
        )
        assert not verdict.is_drifted

    def test_map_without_a_date_is_drifted(self) -> None:
        verdict = map_freshness("# Карта без даты\n", lambda _d: 0, commit_limit=60, today=_TODAY)
        assert verdict.is_drifted
        assert verdict.declared_date is None

    def test_explanation_says_what_to_do(self) -> None:
        verdict = map_freshness("# Карта без даты\n", lambda _d: 0, commit_limit=60, today=_TODAY)
        assert "сверено с main" in verdict.explain()

    def test_a_future_anchor_does_not_buy_freshness(self) -> None:
        # 🔴 ПОВЕДЕНИЕ, а не форма: даже если счётчик коммитов отдаёт ноль (как он и
        # отдавал ревьюеру на будущей дате), вердикт красный — карта не сверена.
        counted: list[date] = []

        def count(since: date) -> int:
            counted.append(since)
            return 0

        verdict = map_freshness(
            "сверено с main 2027-03-01\n", count, commit_limit=60, today=_TODAY
        )
        assert verdict.is_drifted
        assert counted == [], "счётчик коммитов не должен вызываться на негодной дате"
        assert "2027-03-01" in verdict.explain()

    def test_a_neighbouring_future_phrase_leaves_the_real_anchor_in_force(self) -> None:
        # 🔴 Сборка обоих обходов ревью разом: карта с настоящим отставанием и обеими
        # «выключающими» фразами обязана краснеть по НАСТОЯЩЕЙ дате.
        text = (
            "## Статус отгрузки (сверено с main 2026-06-25)\n"
            "Следующая сверка запланирована на 2027-03-01.\n"
            "Сверх плана на 2027-01-01 — переезд на VPS.\n"
        )
        verdict = map_freshness(
            text, lambda since: 333 if since == date(2026, 6, 25) else 0,
            commit_limit=60, today=_TODAY,
        )
        assert verdict.is_drifted
        assert "333" in verdict.explain()

    def test_the_explanation_of_a_broken_anchor_names_the_defect(self) -> None:
        verdict = map_freshness(
            "сверено с main 2026-13-45\n", lambda _d: 0, commit_limit=60, today=_TODAY
        )
        assert verdict.is_drifted
        assert "2026-13-45" in verdict.explain()


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

    def test_a_longer_key_does_not_cover_a_shorter_one(self) -> None:
        # 🔴 Подстрока «BOB-09» находилась внутри «BOB-098» — работа получала место в
        # карте от чужого номера. Ключ ищется как целое слово.
        item = _item("a", title="[BOB-09] старая работа", kind="task", status="open")
        gaps = work_missing_from_map([item], "Тир 3 … BOB-098 актуализация карты\n")
        assert len(gaps) == 1
        assert gaps[0].issue_key == "BOB-09"

    def test_the_key_is_found_next_to_punctuation(self) -> None:
        item = _item("a", title="[BOB-094] VPS", kind="feature", status="open")
        assert work_missing_from_map([item], "линия С2 (**BOB-094**, P1) — переезд\n") == ()

    def test_known_limit_a_mention_anywhere_counts_as_a_place(self) -> None:
        # 🔴 НАЗВАННАЯ ГРАНИЦА (ревью bob-ck4.3, M-10): «место в карте» — это упоминание
        # ключа ГДЕ УГОДНО, включая таблицу ошибок и историю PR. Отличить «работа
        # спланирована» от «работа помянута» можно только разбором прозы — то есть
        # гаданием по форме текста, ровно тем классом, который §0.3 п.12 запрещает.
        # Гейт держит ВИДИМОСТЬ работы в карте, а не её место в плане.
        item = _item("a", title="[BOB-094] VPS", kind="feature", status="open")
        assert work_missing_from_map([item], "| «BOB-094 отгружен» | неверно |\n") == ()

    def test_a_molecule_does_not_free_the_work_under_it(self) -> None:
        # 🔴 Ревью bob-ck4.3, M-13 — та же дыра во второй проверке.
        molecule = _item("s", title="Swarm: [BOB-900] эпик", kind="molecule", status="open")
        epic = _item("e", title="[BOB-900] эпик", kind="epic", status="open", parent_id="s")
        gaps = work_missing_from_map([molecule, epic], "пусто\n")
        assert len(gaps) == 1
        assert gaps[0].root_id == "e"
