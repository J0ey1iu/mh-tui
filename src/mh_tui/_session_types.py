"""Session types used by mh-tui's own persistence layer.

These are local copies of the types that previously lived in
``minimal_harness.session`` / ``minimal_harness.memory_store``. They
were moved to ``mh-orchestration-service`` (a downstream service that
the TUI does not depend on), so the TUI ships its own minimal versions
here for the JSONL-backed session store.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict

from minimal_harness.memory import (
    Memory,
    MemoryData,
    Message,
    TokenUsage,
)


class SessionSummary(TypedDict):
    session_id: str
    agent_name: str
    user_id: str
    scenario_id: str | None
    title: str | None
    created_at: str
    message_count: int
    status: str
    display_name_locale: str | None


class Session(Protocol):
    @property
    def session_id(self) -> str: ...
    @property
    def memory_id(self) -> str: ...
    @property
    def agent_name(self) -> str: ...
    @property
    def display_name_locale(self) -> str | None: ...
    @property
    def user_id(self) -> str: ...
    @property
    def scenario_id(self) -> str | None: ...
    @property
    def title(self) -> str | None: ...
    @property
    def created_at(self) -> str: ...
    @property
    def memory(self) -> Memory: ...

    async def add_message(self, message: Message) -> None: ...
    def get_all_messages(self) -> list[Message]: ...
    def get_forward_messages(self) -> list[Message]: ...
    def get_replay_messages(self) -> list[Message]: ...
    def clear_messages(self) -> None: ...
    def set_message_usage(self, usage: TokenUsage) -> None: ...
    def get_message_usage(self) -> TokenUsage: ...
    def dump_memory(self) -> MemoryData: ...
    def load_memory(self, data: MemoryData) -> None: ...


MemoryFactory = Any  # Callable[[], Memory]


class SessionStoreProtocol(Protocol):
    """Minimal persistence contract used by mh-tui.

    Mirrors the shape of the orchestration service's protocol but is
    kept local so the TUI can stay independent.
    """

    async def create_session(
        self,
        session_id: str | None = None,
        agent_name: str = "",
        user_id: str = "",
        scenario_id: str | None = None,
        transient: bool = False,
        display_name_locale: str | None = None,
    ) -> Session: ...

    async def get_session(self, session_id: str) -> Session | None: ...

    async def save_memory(
        self, memory: Memory, session_id: str, extra: dict[str, Any] | None = None
    ) -> None: ...

    async def delete_session(self, session_id: str) -> bool: ...

    async def list_sessions(self) -> list[SessionSummary]: ...

    async def list_user_sessions(
        self, user_id: str, scenario_id: str | None = None
    ) -> list[SessionSummary]: ...

    async def get_session_messages(self, session_id: str) -> list[dict]: ...

    def get_messages_as_items(self, session: Session) -> list[dict]: ...
