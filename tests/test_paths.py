"""Shared-path helper tests: agent plugin and dashboard backend resolve the same
profile-local DB through one helper (``ripple.paths.db_path``)."""

from __future__ import annotations

from pathlib import Path

from ripple import engine, paths


def test_env_override_applies_to_shared_helper(monkeypatch, tmp_path):
    target = tmp_path / "custom" / "ripple.db"
    monkeypatch.setenv("RIPPLE_DB", str(target))
    assert paths.db_path() == target


def test_agent_store_uses_shared_helper(monkeypatch, tmp_path):
    target = tmp_path / "shared.db"
    monkeypatch.setenv("RIPPLE_DB", str(target))
    assert engine.Store.default_db_path() == target
    assert engine.resolve_db_path() == target
    assert engine.Store.default_db_path() == paths.db_path()


def test_dashboard_backend_resolves_same_engine_helper():
    """The dashboard backend must derive its DB path through the same engine
    helper (Store.from_default -> paths.db_path), never a separate path."""
    src = Path("dashboard/plugin_api.py").read_text()
    assert "from ripple import demo, engine" in src
    assert "engine.Store.from_default()" in src
    assert "engine.Store.from_path" not in src


def test_releases_dir_override(monkeypatch, tmp_path):
    target = tmp_path / "rel"
    monkeypatch.setenv("RIPPLE_RELEASES_DIR", str(target))
    assert paths.releases_dir() == target
    assert target.is_dir()
