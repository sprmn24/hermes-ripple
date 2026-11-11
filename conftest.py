"""Shared fixtures. Every store is opened against a per-test temp directory so
tests never touch the active profile's plugin data dir."""

from __future__ import annotations

import pytest

from ripple import engine


@pytest.fixture
def store(tmp_path):
    s = engine.Store.from_path(
        tmp_path / "ripple.db", releases_dir=tmp_path / "releases"
    )
    yield s
    s.close()


@pytest.fixture
def make_store(tmp_path):
    """Factory for independent Store instances over the same temp DB file."""
    created = []

    def _make(name="ripple.db"):
        s = engine.Store.from_path(
            tmp_path / name, releases_dir=tmp_path / "releases"
        )
        created.append(s)
        return s

    yield _make

    for s in created:
        s.close()
