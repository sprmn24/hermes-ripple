"""Ripple dashboard backend: REST surface for the Desktop pane.

Exposes ``router`` (FastAPI ``APIRouter``) which Hermes mounts under
``/api/plugins/ripple/``. The pane drives the demo through here; approvals and
the demo reset are human actions, never agent tools.

Resolves the same profile-local database as the agent tools through
``ripple.paths.db_path()`` (one shared helper), imported via ``__file__`` so
the plugin package resolves regardless of how Hermes imports this module.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent.parent))

from fastapi import APIRouter, Body, HTTPException  # noqa: E402

from ripple import demo, engine  # noqa: E402

router = APIRouter()

_store_cache = None


def _store() -> "engine.Store":
    global _store_cache
    if _store_cache is None:
        _store_cache = engine.Store.from_default()
    return _store_cache


def _http_error(exc: engine.RippleError, status: int) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={
            "error": exc.code,
            "message": exc.message,
            "cause_path": exc.cause_path,
        },
    )


@router.get("/graph")
def get_graph():
    return _store().graph()


@router.get("/releases")
def get_releases():
    return {"releases": _store().list_releases()}


@router.post("/approve")
def approve(payload: dict = Body(...)):
    artifact_id = payload.get("artifact_id")
    revision = payload.get("revision")
    if artifact_id is None or revision is None:
        raise HTTPException(
            status_code=400,
            detail={"error": "E_BAD_REQUEST", "message": "artifact_id and revision are required"},
        )
    try:
        return _store().approve(str(artifact_id), int(revision))
    except engine.RippleError as exc:
        raise _http_error(exc, 409)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail={"error": "E_BAD_REQUEST", "message": "revision must be an integer"})


@router.post("/demo/reset")
def demo_reset():
    try:
        return demo.load_demo(_store(), publish=True)
    except engine.RippleError as exc:
        raise _http_error(exc, 409)
