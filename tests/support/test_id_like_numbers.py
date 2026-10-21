# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Скан чисел, похожих на id, — общий для гардов трекаемой конфигурации (BOB-116 T).

Каждая форма, которой id прячут в тексте, — отдельный случай: гард, который ловит
подчёркивание и пропускает пробел, однажды уже пропустил настоящий id группы (находка D8b).
Обратная сторона так же важна: честный текст конфигурации (списки, даты, дроби, время)
не должен давать находок, иначе гард выключат как шумный.
"""

from __future__ import annotations

import pytest

from tests.support.id_like_numbers import (
    DigitRun,
    has_log_rotation_value,
    id_like_digit_runs,
)
from tests.support.repository_root import repository_root

_GROUP_ID = "1004372947307"


@pytest.mark.parametrize(
    "line",
    [
        "chat_id: -1004372947307",
        "# группа -100_437_294_7307",
        "# группа -100 4372 9473 07",
        "# группа -100  4372  9473  07",
        "# группа -100\t4372\t9473\t07",
        "# группа -100 4372 9473 07",
        "# группа -100 4372 9473 07",
        "# группа -100 4372 9473 07",
        "# группа -100 _ 4372 _ 9473 _ 07",
        "# группа -100-4372-9473-07",
        'home_group: "-100.4372.9473.07"',
        "# группа -100 - 4372 - 9473 - 07",
        "# группа -100.4372-9473_07",
    ],
    ids=[
        "plain",
        "underscores",
        "spaces",
        "double-spaces",
        "tabs",
        "nbsp",
        "thin-space",
        "narrow-nbsp",
        "mixed",
        "hyphens",
        "dots",
        "spaced-hyphens",
        "mixed-punctuation",
    ],
)
def test_a_split_group_id_is_found_as_one_run(line: str) -> None:
    runs = id_like_digit_runs(f"telegram:\n  {line}\n")

    assert runs == [DigitRun(line=2, digits=_GROUP_ID)]


# Типографские тире и апостроф (ревью m1, bob-i83.24): en dash — обычный знак русской
# типографики, и до правки им серия рвалась. Символы записаны кодами, чтобы случай был виден
# в исходнике, а не терялся среди похожих на дефис глифов.
@pytest.mark.parametrize(
    "separator",
    [
        "\u2010",  # дефис
        "\u2011",  # неразрывный дефис
        "\u2012",  # цифровое тире
        "\u2013",  # en dash
        "\u2014",  # em dash
        "\u2212",  # минус — категория Sm, не Pd, назван отдельно
        "'",  # апостроф — разделитель разрядов в швейцарской записи
        "\u2019",  # типографский апостроф
        "\u2003",  # em space — любой пробел категории Zs
        " \u2013 ",  # тире в пробелах
    ],
    ids=[
        "hyphen-u2010",
        "nb-hyphen-u2011",
        "figure-dash-u2012",
        "en-dash-u2013",
        "em-dash-u2014",
        "minus-u2212",
        "apostrophe",
        "right-quote-u2019",
        "em-space-u2003",
        "spaced-en-dash",
    ],
)
def test_a_group_id_split_by_typographic_separators_is_one_run(separator: str) -> None:
    line = "# группа -" + separator.join(("100", "4372", "9473", "07"))

    assert id_like_digit_runs(f"telegram:\n  {line}\n") == [DigitRun(line=2, digits=_GROUP_ID)]


@pytest.mark.parametrize(
    "line",
    [
        "reminders_seconds: [600, 3600, 21600, 86400]",
        "# замерено 2026-10-21, REFLECT 116 с при пороге 90",
        "# 5.9 + 1.2 = 7.1 ГБ > 5.8 ГБ",
        "# с 06:10 по 06:42",
        "failures_threshold: 5",
        "owner_id: 12345",
        "# beadloom==9.0.0, CPython 3.12.12, claude 2.1.233",
        "# BOB-082.4, bob-i83.13, BOB-112 .5",
        "# замерено 2026-10-21 116 с при пороге 90",
        "# с 2026-10-21 06:10 по 2026-10-22 06:42",
        "# 2026-08-15-2026-10-21",
        "timeout_s: 30  # BOB-116 2026-10-21",
        "# 90-120 с",
        "# 5 + 4372 + 9473",
        "# 4372/9473 и 4372:9473",
    ],
    ids=[
        "list",
        "date",
        "fractions",
        "clock",
        "small",
        "five-digits",
        "versions",
        "bead-ids",
        "date-then-number",
        "date-and-clock",
        "date-range",
        "timeout-and-date",
        "short-range",
        "plus-is-not-a-separator",
        "slash-and-colon",
    ],
)
def test_honest_config_text_has_no_finding(line: str) -> None:
    assert id_like_digit_runs(line) == []


@pytest.mark.parametrize(
    ("line", "digits"),
    [
        ("# 1.004.372", "1004372"),
        ("# 2026-10-21-1004372947307", "1004372947307"),
        ("# 1004372947307-2026-10-21", "1004372947307"),
        ("# 2026-13-21", "20261321"),
        ("# 2746-08-15", "27460815"),
        ("# 127.0.0.1:11434", "127001"),
        ("# 21600-86400 с", "2160086400"),
    ],
    ids=[
        "version-shaped-id",
        "id-after-a-date",
        "id-before-a-date",
        "no-such-month",
        "not-a-year",
        "ipv4-literal",
        "long-range",
    ],
)
def test_only_a_real_date_breaks_a_hyphenated_run(line: str, digits: str) -> None:
    # Дата 19YY/20YY-MM-DD снимается целиком и рвёт серию; всё остальное, похожее на
    # дату, версию, адрес или диапазон, склеивается и считается — цена правила, названная
    # в докстринге помощника (IPv4-литерал в конфигурации пишется localhost).
    assert id_like_digit_runs(line) == [DigitRun(line=1, digits=digits)]


def test_the_log_rotation_value_is_exempt_on_its_line() -> None:
    assert id_like_digit_runs("runtime:\n  log_max_bytes: 33554432  # 32 MiB\n") == []


def test_an_id_glued_to_the_log_rotation_value_is_still_found() -> None:
    # Без порядка «исключение до склейки» id ушёл бы вместе со значением ротации.
    runs = id_like_digit_runs("  log_max_bytes: 33554432 4372 9473 07\n")

    assert runs == [DigitRun(line=1, digits="4372947307")]


def test_an_id_in_the_comment_of_the_log_rotation_line_is_found() -> None:
    runs = id_like_digit_runs("  log_max_bytes: 33554432  # owner 27468732\n")

    assert runs == [DigitRun(line=1, digits="27468732")]


def test_the_exemption_applies_only_to_the_log_rotation_key() -> None:
    assert id_like_digit_runs("  log_max_owner: 27468732\n") == [
        DigitRun(line=1, digits="27468732")
    ]


def test_line_numbers_survive_the_separator_join() -> None:
    runs = id_like_digit_runs("a: 1\nb: 2\n# 274 687 32\n")

    assert runs == [DigitRun(line=3, digits="27468732")]


def test_digits_on_adjacent_lines_are_not_glued() -> None:
    assert id_like_digit_runs("a: 123\n456: b\n") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [("  log_max_bytes: 33554432\n", True), ("  log_max_bytes: none\n", False), ("", False)],
    ids=["value", "no-value", "empty"],
)
def test_log_rotation_value_presence(text: str, expected: bool) -> None:
    assert has_log_rotation_value(text) is expected


def test_repository_root_is_the_directory_with_the_manifest() -> None:
    root = repository_root()

    assert (root / "pyproject.toml").is_file()
    assert (root / "tests" / "support" / "repository_root.py").is_file()
