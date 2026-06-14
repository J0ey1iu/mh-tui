"""Tool collection — registers built-in + external tools."""

from __future__ import annotations

from typing import Any

from minimal_harness.tool.registry import ToolRegistry

from mh_tui.built_in import collect_tools as _collect


async def collect_tools(
    config: dict[str, Any],
    registry: ToolRegistry,
) -> None:
    await _collect(config, registry)
