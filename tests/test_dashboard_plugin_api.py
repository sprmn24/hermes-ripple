"""Regression: the plugin host loads ``dashboard/plugin_api.py`` as a standalone
module via ``spec_from_file_location`` (see hermes_cli/plugin_host_child.py
op_asgi) and then calls the FastAPI route handlers. The ``_store()`` accessor
must return a ``Store``, never the function object itself. The name-shadowing
bug (``_store`` cache var overwritten by ``def _store``) made ``_store()``
return the function, so ``get_graph()`` raised
``AttributeError: 'function' object has no attribute 'graph'`` — surfaced to the
desktop as 502 "plugin 'ripple' could not run in this profile's plugin host".
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from ripple import engine

# plugin_api.py imports fastapi at module top. The dashboard only ever runs
# inside the plugin host (hermes agent venv), which ships fastapi. In a bare
# interpreter without it, skip rather than fail so `pytest -q` stays green.
pytest.importorskip(
    "fastapi", reason="dashboard backend imports fastapi (plugin-host venv)"
)

API_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "plugin_api.py"


def _load_host_style():
    """Import plugin_api.py exactly as the plugin host child does."""
    module_name = "hermes_dashboard_plugin_ripple"
    spec = importlib.util.spec_from_file_location(module_name, API_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_host_loaded_store_returns_store_not_function(monkeypatch, tmp_path):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "ripple.db"))
    monkeypatch.setenv("RIPPLE_RELEASES_DIR", str(tmp_path / "releases"))

    module = _load_host_style()

    store = module._store()
    assert isinstance(store, engine.Store), (
        f"_store() returned {type(store).__name__}, not engine.Store"
    )

    # The route handler must return a graph, not raise AttributeError.
    graph = module.get_graph()
    assert set(graph) >= {"nodes", "edges", "approvals", "releases"}
