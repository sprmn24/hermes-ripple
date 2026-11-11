"""Ripple — incremental build system for agent work (Hermes plugin entry point)."""

from __future__ import annotations

from typing import Any


def register(ctx: Any) -> None:
    from .ripple import hooks, tools

    ctx.register_hook("pre_tool_call", hooks.pre_tool_call)
    ctx.register_tool(
        name="ripple_put_source",
        toolset="ripple",
        schema=tools.PUT_SOURCE_SCHEMA,
        handler=tools.handle_put_source,
        description="Append a new immutable source revision and mark descendants stale.",
    )
    ctx.register_tool(
        name="ripple_derive",
        toolset="ripple",
        schema=tools.DERIVE_SCHEMA,
        handler=tools.handle_derive,
        description="Derive a typed compute/artifact node from a recipe, pinning input revisions.",
    )
    ctx.register_tool(
        name="ripple_impact",
        toolset="ripple",
        schema=tools.IMPACT_SCHEMA,
        handler=tools.handle_impact,
        description="Return a node's descendants and the cause path of its impact.",
    )
    ctx.register_tool(
        name="ripple_rebuild",
        toolset="ripple",
        schema=tools.REBUILD_SCHEMA,
        handler=tools.handle_rebuild,
        description="Recompute stale deterministic nodes in topological order.",
    )
    ctx.register_tool(
        name="ripple_publish",
        toolset="ripple",
        schema=tools.PUBLISH_SCHEMA,
        handler=tools.handle_publish,
        description=(
            "Publish an artifact (authoritative re-validation of freshness and "
            "approval; a pre_tool_call hook refuses stale publications early)."
        ),
    )
    ctx.register_tool(
        name="ripple_graph",
        toolset="ripple",
        schema=tools.GRAPH_SCHEMA,
        handler=tools.handle_graph,
        description="Return a full snapshot of the Ripple graph (nodes, edges, approvals, releases).",
    )
