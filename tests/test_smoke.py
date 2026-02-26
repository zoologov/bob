"""Smoke test: project imports correctly."""

import bob


def test_bob_package_is_importable() -> None:
    assert bob is not None
