"""pre_tool_call hook: early refusal for ripple_publish.

This is the *early* refusal with a human-readable cause path; ``Store.publish``
remains the authoritative gate and re-validates inside its write transaction.
"""

from __future__ import annotations

from . import engine


def pre_tool_call(tool_name: str, args: dict) -> dict:
    if tool_name != "ripple_publish":
        return {"action": "allow"}
    artifact_id = (args or {}).get("artifact_id")
    if not artifact_id:
        return {
            "action": "block",
            "message": "Refusing publish: missing artifact_id.",
        }
    try:
        reason = engine.get_store().publish_block_reason(artifact_id)
    except engine.RippleError as exc:
        return {"action": "block", "message": exc.message}
    except Exception as exc:  # pragma: no cover - defensive
        return {"action": "block", "message": f"Refusing publish: {exc}"}
    if reason is None:
        return {"action": "allow"}
    message, _cause_path = reason
    return {"action": "block", "message": message}
