"""Smoke tests for the built-in tools (bash, local file operation)."""

import pytest
from minimal_harness.types import LocalToolBinding, ToolMetadata

from mh_tui.built_in import (
    bash_tool,
    collect_builtin_tools,
    get_builtin_tool_names,
    get_tools,
    local_file_operation_tool,
)


def test_get_tools_returns_both():
    tools = get_tools()
    assert set(tools) == {"bash", "local_file_operation"}


def test_get_builtin_tool_names():
    assert get_builtin_tool_names() == {"bash", "local_file_operation"}


def test_bash_tool_metadata():
    assert bash_tool.name == "bash"
    assert bash_tool.display_name == "Bash"
    assert bash_tool.display_name_locale == {"zh": "命令行"}
    assert "command" in bash_tool.parameters["required"]


def test_local_file_operation_tool_metadata():
    assert local_file_operation_tool.name == "local_file_operation"
    assert local_file_operation_tool.display_name == "File Operation"
    assert local_file_operation_tool.display_name_locale == {"zh": "文件操作"}
    props = local_file_operation_tool.parameters["properties"]
    assert set(props["mode"]["enum"]) == {"read", "write", "patch", "delete"}


@pytest.mark.asyncio
async def test_collect_builtin_tools_registers_both():
    class _FakeRegistry:
        def __init__(self):
            self.registered: list[ToolMetadata] = []

        async def register(self, metadata: ToolMetadata) -> None:
            self.registered.append(metadata)

    reg = _FakeRegistry()
    names = await collect_builtin_tools(reg)  # type: ignore[arg-type]

    assert names == {"bash", "local_file_operation"}
    assert {m.name for m in reg.registered} == {"bash", "local_file_operation"}
    for m in reg.registered:
        assert isinstance(m.binding, LocalToolBinding)
        assert m.binding.fn is not None
        assert m.metadata_id == m.name
