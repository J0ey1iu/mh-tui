"""Standalone smoke test for the CompactionAgent pipeline.

Drives the full agent loop with a scripted LLM provider that returns
high ``prompt_tokens`` on demand. Prints every event (CompactionStart,
CompactionChunk, CompactionEnd, etc.) to stdout as it flows.

Run:
    python examples/dev-with-mh/verify_compaction.py

No real LLM, no API key, no TUI launch. Exits 0 on success, 1 on
assertion failure.

This script is the *fast* verification surface (Stage 1). For full
visual verification through the TUI, see Stage 2: launch ``mhc`` with
the ``compacting_assistant`` agent preset and have a long conversation.
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any, AsyncIterator, Sequence, cast

from minimal_harness.agent.compacting import CompactionAgent
from minimal_harness.llm.llm import LLMResponse, Stream
from minimal_harness.memory import (
    ConversationMemory,
    Message,
    assistant_message,
    user_message,
)
from minimal_harness.types import (
    AgentEvent,
    LLMChunkDelta,
)

# ── mock LLM provider ─────────────────────────────────────────────────


class ScriptedLLMProvider:
    """Returns a pre-canned sequence of LLMResponses, simulating a long
    conversation where the LLM eventually exceeds the threshold.

    Each call also yields one LLMChunkDelta so the streaming path is
    exercised. The summarizer is invoked on its own private provider
    (see :class:`SummarizerLLMProvider`).
    """

    def __init__(
        self,
        responses: list[LLMResponse],
        call_log: list[list[Message]] | None = None,
    ) -> None:
        self._responses = list(responses)
        self._call_log = call_log if call_log is not None else []

    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[Any] = (),
        stop_event: asyncio.Event | None = None,
        **kwargs: Any,
    ) -> Stream[LLMChunkDelta]:
        self._call_log.append(list(messages))
        if not self._responses:
            raise RuntimeError("ScriptedLLMProvider: ran out of scripted responses")
        resp = self._responses.pop(0)

        async def _gen() -> AsyncIterator[Any]:
            if resp.content:
                yield LLMChunkDelta(content=resp.content)
            yield resp

        return Stream(_gen())


class SummarizerLLMProvider:
    """A second mock LLM provider used by the summarizer. Yields a
    fixed stream of 'tokens' to simulate a streaming summary response.
    """

    def __init__(self, words: list[str], call_log: list[list[Message]] | None = None):
        self._words = list(words)
        self._call_log = call_log if call_log is not None else []

    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[Any] = (),
        stop_event: asyncio.Event | None = None,
        **kwargs: Any,
    ) -> Stream[LLMChunkDelta]:
        self._call_log.append(list(messages))

        async def _gen() -> AsyncIterator[Any]:
            for w in self._words:
                yield LLMChunkDelta(content=w)
                await asyncio.sleep(0.005)
            yield LLMResponse(
                content="".join(self._words),
                reasoning_content=None,
                tool_calls=[],
                finish_reason="stop",
                usage={
                    "prompt_tokens": 200,
                    "completion_tokens": 50,
                    "total_tokens": 250,
                },
            )

        return Stream(_gen())


# ── the summarizer (mirrors what mh-tui will build) ──────────────────


async def make_summarizer(summarizer_provider: SummarizerLLMProvider):
    """Returns a streaming summarizer that calls the LLM, with a
    deterministic simulated stream driven by :class:`SummarizerLLMProvider`.
    """

    async def summarizer(
        messages: list[Message], existing_summary: str | None
    ) -> AsyncIterator[str]:
        sys_msg: Message = cast(
            Message,
            {
                "role": "system",
                "content": "You compress old conversation turns into a short summary.",
            },
        )
        user_msg: Message = cast(
            Message,
            {
                "role": "user",
                "content": (
                    f"existing summary: {existing_summary!r}\n"
                    f"messages to fold: {len(messages)}"
                ),
            },
        )
        stream = await summarizer_provider.chat(messages=[sys_msg, user_msg], tools=[])
        async for chunk in stream:
            if chunk.content:
                yield chunk.content

    return summarizer


# ── helpers ──────────────────────────────────────────────────────────


def _user(text: str) -> Message:
    return user_message([{"type": "text", "text": text}])


def _assistant(text: str) -> Message:
    return assistant_message(text, None)


def _log(event: AgentEvent, t0: float) -> None:
    elapsed = time.time() - t0
    tag = f"t+{elapsed:6.3f}s"
    from minimal_harness.types import (
        AgentEnd,
        AgentStart,
        CompactionChunk,
        CompactionEnd,
        CompactionStart,
        LLMEnd,
        LLMStart,
        MemoryUpdate,
        MessageEvent,
    )

    if isinstance(event, AgentStart):
        print(f"  {tag}  [agent.start]")
    elif isinstance(event, LLMStart):
        print(f"  {tag}  [llm.start]    messages={len(event.messages)}")
    elif isinstance(event, LLMEnd):
        u = event.usage
        usage = (
            f"prompt={u['prompt_tokens']} completion={u['completion_tokens']}"
            if u
            else "usage=None"
        )
        print(f"  {tag}  [llm.end]      {usage}")
    elif isinstance(event, MemoryUpdate):
        pass
    elif isinstance(event, MessageEvent):
        m = event.message
        if m.get("role") == "compaction":
            # Compaction summary surfaced as a CompactionMessage. The
            # frontend should re-project to assistant for the LLM but
            # keep the original form for storage; here we just print
            # it so the smoke test shows what's flowing through.
            content = m.get("content", "")
            preview = (
                content[:60].replace("\n", "\\n")
                if isinstance(content, str)
                else str(content)[:60]
            )
            meta = m.get("meta") or {}
            dropped = meta.get("dropped_count", "?")
            print(
                f"  {tag}  [msg.compaction]  ↳ summary (dropped={dropped}): "
                f"{preview!r}{'…' if isinstance(content, str) and len(content) > 60 else ''}"
            )
        else:
            print(f"  {tag}  [msg.{m.get('role')}]")
    elif isinstance(event, CompactionStart):
        print(
            f"  {tag}  [compact.start]  dropped={event.dropped_message_count} "
            f"kept={event.keep_recent} prompt_tokens={event.prompt_tokens}"
        )
    elif isinstance(event, CompactionChunk):
        # Truncate long chunks for the log line
        d = event.delta.replace("\n", "\\n")
        a = event.accumulated
        print(f"  {tag}  [compact.chunk]  +{d!r}  (acc={len(a)} chars)")
    elif isinstance(event, CompactionEnd):
        e = f"  err={event.error}" if event.error else ""
        print(
            f"  {tag}  [compact.end]    summary={len(event.summary)} chars "
            f"dropped={event.dropped_message_count} new_offset={event.new_offset} "
            f"duration={event.duration:.3f}s{e}"
        )
    elif isinstance(event, AgentEnd):
        print(
            f"  {tag}  [agent.end]    response={event.response[:50]!r} "
            f"error={event.error!r}"
        )
    else:
        print(f"  {tag}  [{type(event).__name__}]")


# ── scenarios ────────────────────────────────────────────────────────


async def scenario_under_threshold() -> None:
    print("\n=== Scenario 1: prompt_tokens BELOW threshold (no compaction) ===")
    t0 = time.time()
    provider = ScriptedLLMProvider(
        responses=[
            LLMResponse(
                content="ok",
                reasoning_content=None,
                tool_calls=[],
                finish_reason="stop",
                usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 5,
                    "total_tokens": 105,
                },
            ),
        ]
    )
    summarizer_provider = SummarizerLLMProvider(words=["never", " called"])
    summarizer = await make_summarizer(summarizer_provider)

    agent = CompactionAgent(
        llm_provider=provider,
        summarizer=summarizer,
        prompt_token_threshold=8000,
        keep_recent=4,
        max_iterations=1,
    )
    memory = ConversationMemory()
    for i in range(6):
        await memory.add_message(_user(f"q{i}"))
        await memory.add_message(_assistant(f"a{i}"))

    events: list[AgentEvent] = []
    async for evt in agent.run(
        user_input=[{"type": "text", "text": "hi"}], memory=memory, tools=[]
    ):
        events.append(evt)
        _log(evt, t0)

    from minimal_harness.types import CompactionEnd, CompactionStart

    compact_events = [
        e for e in events if isinstance(e, (CompactionStart, CompactionEnd))
    ]
    assert len(compact_events) == 0, (
        f"expected zero compaction events, got {len(compact_events)}"
    )
    assert len(summarizer_provider._call_log) == 0, "summarizer must NOT be called"
    print("  ✓ no compaction fired, summarizer not invoked")


async def scenario_over_threshold() -> None:
    print("\n=== Scenario 2: prompt_tokens ABOVE threshold (compaction fires) ===")
    t0 = time.time()
    provider = ScriptedLLMProvider(
        responses=[
            LLMResponse(
                content="done",
                reasoning_content=None,
                tool_calls=[],
                finish_reason="stop",
                usage={
                    "prompt_tokens": 9200,
                    "completion_tokens": 5,
                    "total_tokens": 9205,
                },
            ),
        ]
    )
    summarizer_provider = SummarizerLLMProvider(
        words=["alpha", " beta", " gamma", " delta"]
    )
    summarizer = await make_summarizer(summarizer_provider)

    agent = CompactionAgent(
        llm_provider=provider,
        summarizer=summarizer,
        prompt_token_threshold=8000,
        keep_recent=4,
        max_iterations=1,
    )
    memory = ConversationMemory()
    for i in range(6):
        await memory.add_message(_user(f"q{i}"))
        await memory.add_message(_assistant(f"a{i}"))
    memory.set_message_usage({"prompt_tokens": 9200, "completion_tokens": 0, "total_tokens": 9200})

    events: list[AgentEvent] = []
    async for evt in agent.run(
        user_input=[{"type": "text", "text": "go"}], memory=memory, tools=[]
    ):
        events.append(evt)
        _log(evt, t0)

    from minimal_harness.types import CompactionChunk, CompactionEnd, CompactionStart

    starts = [e for e in events if isinstance(e, CompactionStart)]
    chunks = [e for e in events if isinstance(e, CompactionChunk)]
    ends = [e for e in events if isinstance(e, CompactionEnd)]
    assert len(starts) == 1, f"expected 1 start, got {len(starts)}"
    assert len(chunks) == 4, f"expected 4 chunks, got {len(chunks)}"
    assert len(ends) == 1, f"expected 1 end, got {len(ends)}"
    assert starts[0].prompt_tokens == 9200
    assert ends[0].error is None
    assert ends[0].summary == "alpha beta gamma delta"
    # 12 pre-populated + 1 user input + 1 assistant (added before
    # compact) = 14 messages; 14 - 4 recent = 10 folded.
    assert ends[0].dropped_message_count == 10
    assert len(summarizer_provider._call_log) == 1, "summarizer called exactly once"
    print("  ✓ compaction fired with 1 start + 4 chunks + 1 end")
    print("  ✓ summarizer invoked once, summary='alpha beta gamma delta'")

    # Verify memory state after compaction
    msgs = memory.get_all_messages()
    # Storage uses a CompactionMessage (role="compaction"), distinct
    # from a real assistant response so the TUI can render the
    # summary with a "Folded summary" marker.
    assert msgs[0]["role"] == "compaction", f"msgs[0] role: {msgs[0].get('role')}"
    assert msgs[0]["content"] == "alpha beta gamma delta"
    assert msgs[0].get("meta") is not None
    # New design: the just-added assistant message is part of the
    # keep_recent tail (it was added BEFORE compact ran). So the
    # buffer is 1 compaction + 4 recent tail = 5 msgs, with the
    # assistant being the last entry in the tail.
    assert len(msgs) == 5
    # The last message in the tail is the just-added assistant
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["content"] == "done"
    # offset stays at 0 — the summary is the natural start of the
    # compacted conversation; get_forward_messages() re-projects it
    # to role="assistant" for the LLM.
    assert memory._forward_offset == 0
    print(
        f"  ✓ memory buffer: [compaction_summary, ...3 recent, assistant] = "
        f"{len(msgs)} msgs, offset=0"
    )

    # Verify forward view the LLM sees — compaction is re-projected
    # to role="assistant" so the LLM sees a normal historical turn.
    forward = memory.get_forward_messages()
    assert forward[0]["role"] == "assistant"
    assert forward[0]["content"] == "alpha beta gamma delta"
    assert len(forward) == 5
    print("  ✓ get_forward_messages() re-projects compaction to assistant")


async def scenario_repeated_compaction() -> None:
    print("\n=== Scenario 3: second compaction folds old summary into new one ===")
    t0 = time.time()

    # Stage the memory so that AFTER a first compaction (in-memory) the
    # second LLM call would also cross the threshold, forcing a second
    # compaction. We do this by manually priming the buffer with a
    # pre-existing summary + many recent messages, so the first call
    # already exceeds the threshold.
    provider = ScriptedLLMProvider(
        responses=[
            LLMResponse(
                content="r1",
                reasoning_content=None,
                tool_calls=[],
                finish_reason="stop",
                usage={
                    "prompt_tokens": 9000,
                    "completion_tokens": 1,
                    "total_tokens": 9001,
                },
            ),
        ]
    )
    summarizer_provider = SummarizerLLMProvider(words=["v2"])
    summarizer = await make_summarizer(summarizer_provider)

    seen_summarizer_calls: list[str | None] = []
    original_summarizer = summarizer

    async def tracking_summarizer(messages, existing):
        seen_summarizer_calls.append(existing)
        async for c in original_summarizer(messages, existing):
            yield c

    agent = CompactionAgent(
        llm_provider=provider,
        summarizer=tracking_summarizer,
        prompt_token_threshold=8000,
        keep_recent=2,
        max_iterations=1,
    )
    memory = ConversationMemory()
    # Pre-seed with a fake prior CompactionMessage at index 0 + 20
    # recent messages. The second compact() detects role="compaction"
    # at msgs[0], lifts its content as existing_summary, and folds
    # msgs[1:end] into a new summary.
    await memory.add_message(
        {
            "role": "compaction",
            "content": "[earlier conversation: user asked about X]",
            "meta": {"dropped_count": 0, "keep_recent": 0},
        }
    )
    for i in range(20):
        await memory.add_message(_user(f"q{i}"))
        await memory.add_message(_assistant(f"a{i}"))
    memory.set_message_usage({"prompt_tokens": 9000, "completion_tokens": 0, "total_tokens": 9000})

    events: list[AgentEvent] = []
    async for evt in agent.run(
        user_input=[{"type": "text", "text": "go"}], memory=memory, tools=[]
    ):
        events.append(evt)
        _log(evt, t0)

    from minimal_harness.types import CompactionEnd, CompactionStart

    starts = [e for e in events if isinstance(e, CompactionStart)]
    ends = [e for e in events if isinstance(e, CompactionEnd)]
    assert len(starts) == 1
    assert len(ends) == 1
    assert starts[0].existing_summary is not None
    assert "[earlier conversation" in starts[0].existing_summary
    assert seen_summarizer_calls[0] is not None
    assert "[earlier conversation" in seen_summarizer_calls[0]
    print("  ✓ CompactionStart.existing_summary carries the prior summary")
    print("  ✓ summarizer invoked with the prior summary as second arg")
    print(f"  ✓ final buffer = {len(memory.get_all_messages())} msgs")


async def scenario_compaction_failure() -> None:
    print("\n=== Scenario 4: summarizer raises (compaction fails, agent errors) ===")
    t0 = time.time()

    class FailingSummarizerProvider:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tools=(), stop_event=None, **kwargs):
            self.calls += 1

            async def _gen():
                yield LLMChunkDelta(content="partial-")
                raise RuntimeError("simulated LLM outage")

            return Stream(_gen())

    main_provider = ScriptedLLMProvider(
        responses=[
            LLMResponse(
                content="ok",
                reasoning_content=None,
                tool_calls=[],
                finish_reason="stop",
                usage={
                    "prompt_tokens": 9000,
                    "completion_tokens": 1,
                    "total_tokens": 9001,
                },
            ),
        ]
    )
    failing_provider = FailingSummarizerProvider()

    async def failing_summarizer(messages, existing):
        stream = await failing_provider.chat(messages=[], tools=[])
        async for c in stream:
            if c.content:
                yield c.content

    agent = CompactionAgent(
        llm_provider=main_provider,
        summarizer=failing_summarizer,
        prompt_token_threshold=8000,
        keep_recent=2,
        max_iterations=1,
    )
    memory = ConversationMemory()
    for i in range(6):
        await memory.add_message(_user(f"q{i}"))
        await memory.add_message(_assistant(f"a{i}"))
    memory.set_message_usage({"prompt_tokens": 9000, "completion_tokens": 0, "total_tokens": 9000})
    # Snapshot taken right before agent.run — the agent itself will
    # add the user_input message at the top of run(), which is *expected*
    # and not part of the test invariant.
    msgs_before_run = [dict(m) for m in memory.get_all_messages()]

    events: list[AgentEvent] = []
    async for evt in agent.run(
        user_input=[{"type": "text", "text": "go"}], memory=memory, tools=[]
    ):
        events.append(evt)
        _log(evt, t0)

    from minimal_harness.types import AgentEnd, CompactionEnd

    ends = [e for e in events if isinstance(e, CompactionEnd)]
    assert len(ends) == 1
    assert ends[0].error is not None
    assert "RuntimeError" in ends[0].error

    agent_ends = [e for e in events if isinstance(e, AgentEnd)]
    assert len(agent_ends) == 1
    assert agent_ends[0].error is not None
    assert "Compaction failed" in agent_ends[0].error

    # Invariant: failed compaction must not have applied its fold. The
    # only allowed mutations past this point are the user_input message
    # the agent added at the start of run() and the assistant message
    # recorded AFTER the deferred raise (so the LLM's response is
    # preserved for the next turn and the frontend gets to see it).
    msgs_after = [dict(m) for m in memory.get_all_messages()]
    expected = msgs_before_run + [
        {"role": "user", "content": [{"type": "text", "text": "go"}]},
        {"role": "assistant", "content": "ok", "tool_calls": None},
    ]
    assert msgs_after == expected, (
        f"memory mutated unexpectedly on compact failure.\n"
        f"  expected: {len(expected)} msgs (before + user_input + assistant)\n"
        f"  got:      {len(msgs_after)} msgs"
    )
    # No compaction message should have been inserted on failure
    assert not any(m.get("role") == "compaction" for m in msgs_after), (
        "compaction must not insert a summary when it fails"
    )
    # The assistant MessageEvent must reach the frontend even when
    # compact failed, otherwise the LLM's reply is invisible to the user
    # and lost to the next turn.
    from minimal_harness.types import MessageEvent

    assistant_events = [
        e
        for e in events
        if isinstance(e, MessageEvent) and e.message.get("role") == "assistant"
    ]
    assert len(assistant_events) == 1, (
        f"expected exactly 1 assistant MessageEvent, got {len(assistant_events)}"
    )
    assert assistant_events[0].message.get("content") == "ok"
    # Order check: msg.assistant is the primary content and comes
    # first, then the compact events (housekeeping), then agent.end
    # (terminal error). Frontend renders the LLM's reply before the
    # compact error block.
    assistant_idx = next(
        i
        for i, e in enumerate(events)
        if isinstance(e, MessageEvent) and e.message.get("role") == "assistant"
    )
    compaction_end_idx = next(
        i for i, e in enumerate(events) if isinstance(e, CompactionEnd)
    )
    agent_end_idx = next(i for i, e in enumerate(events) if isinstance(e, AgentEnd))
    assert assistant_idx < compaction_end_idx < agent_end_idx, (
        f"event order wrong: assistant={assistant_idx} "
        f"compact_end={compaction_end_idx} agent_end={agent_end_idx}"
    )
    print("  ✓ CompactionEnd.error set, AgentEnd.error wraps it")
    print("  ✓ memory buffer: no summary, but assistant turn IS recorded")
    print("  ✓ MessageEvent(assistant) emitted BEFORE compact events")
    print("  ✓ event order: [msg.assistant, compact.start/chunk/end, agent.end]")


async def scenario_assistant_folded_by_same_turn_compaction() -> None:
    """keep_recent=0 means compaction folds EVERYTHING, including the
    just-added assistant message. The frontend still sees the raw
    reply via ``MessageEvent(assistant)``; only what the next LLM
    call sees is compacted (the buffer is just the CompactionMessage).

    This validates the design invariant: "what the user sees" (raw
    MessageEvent stream) is decoupled from "what the model sees on
    the next turn" (compacted buffer / get_forward_messages).
    """
    print("\n=== Scenario 5: keep_recent=0 → assistant folded by same-turn compact ===")
    t0 = time.time()

    captured_fold: list[Message] = []

    async def capturing_summarizer(
        messages: list[Message], existing: str | None
    ) -> AsyncIterator[str]:
        captured_fold.extend(messages)
        yield "everything-folded"

    main_provider = ScriptedLLMProvider(
        responses=[
            LLMResponse(
                content="this-reply-gets-folded",
                reasoning_content=None,
                tool_calls=[],
                finish_reason="stop",
                usage={
                    "prompt_tokens": 9000,
                    "completion_tokens": 5,
                    "total_tokens": 9005,
                },
            ),
        ]
    )

    agent = CompactionAgent(
        llm_provider=main_provider,
        summarizer=capturing_summarizer,
        prompt_token_threshold=8000,
        keep_recent=0,
        max_iterations=1,
    )
    memory = ConversationMemory()
    for i in range(4):
        await memory.add_message(_user(f"q{i}"))
        await memory.add_message(_assistant(f"a{i}"))
    memory.set_message_usage({"prompt_tokens": 9000, "completion_tokens": 0, "total_tokens": 9000})

    from minimal_harness.types import (
        AgentEnd,
        CompactionStart,
        MessageEvent,
    )

    events: list = []
    async for evt in agent.run(
        user_input=[{"type": "text", "text": "go"}], memory=memory, tools=[]
    ):
        events.append(evt)
        _log(evt, t0)

    # The summarizer received the user_input AND the just-added
    # assistant message (no tail was kept).
    fold_contents = [m.get("content") for m in captured_fold]
    assert any("go" in str(c) for c in fold_contents if c), (
        f"user_input 'go' not in fold: {fold_contents}"
    )
    assert any("this-reply-gets-folded" in str(c) for c in fold_contents if c), (
        f"just-added assistant not in fold: {fold_contents}"
    )

    # Event order: msg.assistant → compact events → msg.compaction → agent.end
    assistant_idx = next(
        i
        for i, e in enumerate(events)
        if isinstance(e, MessageEvent) and e.message.get("role") == "assistant"
    )
    compact_start_idx = next(
        i for i, e in enumerate(events) if isinstance(e, CompactionStart)
    )
    compact_msg_idx = next(
        i
        for i, e in enumerate(events)
        if isinstance(e, MessageEvent) and e.message.get("role") == "compaction"
    )
    agent_end_idx = next(i for i, e in enumerate(events) if isinstance(e, AgentEnd))
    assert assistant_idx < compact_start_idx < compact_msg_idx < agent_end_idx

    # Buffer state: only the CompactionMessage, nothing else.
    msgs = [dict(m) for m in memory.get_all_messages()]
    assert len(msgs) == 1
    assert msgs[0].get("role") == "compaction"
    assert msgs[0].get("content") == "everything-folded"

    # What the next LLM call sees (get_forward_messages re-projects
    # compaction → assistant): just one assistant turn with the
    # summary text. The raw "this-reply-gets-folded" is gone.
    forwarded = memory.get_forward_messages()
    assert len(forwarded) == 1
    assert forwarded[0].get("role") == "assistant"
    assert forwarded[0].get("content") == "everything-folded"
    assert "this-reply-gets-folded" not in str(forwarded)

    # The frontend DID see the raw reply via MessageEvent (so the
    # user is not blind to what the LLM said even though the buffer
    # already compacted it away).
    assistant_event = next(
        e
        for e in events
        if isinstance(e, MessageEvent) and e.message.get("role") == "assistant"
    )
    assert assistant_event.message.get("content") == "this-reply-gets-folded"

    # And agent.end is a clean success (compact succeeded).
    end = next(e for e in events if isinstance(e, AgentEnd))
    assert end.error is None

    print("  ✓ summarizer received both user_input and the just-added assistant")
    print("  ✓ buffer = [CompactionMessage] only (assistant folded in)")
    print("  ✓ get_forward_messages() returns just the summary, no raw reply")
    print("  ✓ MessageEvent(assistant) still shows raw reply to frontend")
    print("  ✓ event order: [msg.assistant, compact.*, msg.compaction, agent.end]")
    print("  ✓ 'what user sees' (MessageEvent) != 'what model sees' (buffer)")


# ── entry point ──────────────────────────────────────────────────────


async def main() -> int:
    try:
        await scenario_under_threshold()
        await scenario_over_threshold()
        await scenario_repeated_compaction()
        await scenario_compaction_failure()
        await scenario_assistant_folded_by_same_turn_compaction()
    except AssertionError as e:
        print(f"\n✗ FAILED: {e}")
        return 1
    print("\n=== All 5 scenarios passed ===")
    print(
        "Stage 1 verification complete. See the TUI for visual confirmation (Stage 2)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
