# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the composition-root config readers — ``_str_list`` (BOB-087.D2).

The permissive value-coercion readers turn the layered YAML/env config into concrete
values. ``_str_list`` is the string twin of ``_int_list``: a YAML list of strings OR a
CSV env string, with non-string / blank entries dropped, so a malformed config degrades
to a shorter list instead of crashing the composition root.
"""

from __future__ import annotations

from bob.runtime.config import _str_list


def test_missing_key_is_an_empty_tuple() -> None:
    assert _str_list({}, "extra_dirs") == ()


def test_reads_a_yaml_list_of_strings() -> None:
    assert _str_list({"extra_dirs": ["/a", "/b"]}, "extra_dirs") == ("/a", "/b")


def test_reads_a_csv_env_string() -> None:
    # Env config arrives as a flat string — the CSV form mirrors ``_int_list``.
    assert _str_list({"extra_dirs": "/a, /b"}, "extra_dirs") == ("/a", "/b")


def test_csv_blank_parts_are_dropped() -> None:
    assert _str_list({"extra_dirs": "/a,,  ,/b,"}, "extra_dirs") == ("/a", "/b")


def test_non_string_items_are_dropped_not_fatal() -> None:
    section = {"extra_dirs": ["/a", 7, None, {"x": 1}, "/b"]}

    assert _str_list(section, "extra_dirs") == ("/a", "/b")


def test_blank_items_are_dropped() -> None:
    assert _str_list({"extra_dirs": ["", "   ", "/a"]}, "extra_dirs") == ("/a",)


def test_a_non_list_non_string_value_is_an_empty_tuple() -> None:
    assert _str_list({"extra_dirs": 42}, "extra_dirs") == ()
    assert _str_list({"extra_dirs": None}, "extra_dirs") == ()


def test_an_empty_string_value_is_an_empty_tuple() -> None:
    assert _str_list({"extra_dirs": ""}, "extra_dirs") == ()
