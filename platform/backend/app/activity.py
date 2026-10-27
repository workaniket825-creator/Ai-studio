"""Live Reasoning & Activity Stream (spec §25).

- ActivityBus: per-run asyncio pub/sub with a bounded ring buffer for replay/reconnect.
- Narrator: the deterministic templated narrator (tier 1) that turns raw runtime
  events into friendly, present-tense phrases. The optional LLM-flavored narrator
  (tier 2) plugs in behind `narrate()` and is intentionally out of scope for Phase 0.

In production this is fed by an ADK `ActivityStreamPlugin` on the Runner and fans
out to both MLflow (durable trace) and this bus (ephemeral UX). Here the mock
runtime feeds it directly.
"""
from __future__ import annotations

import asyncio
import random
from collections import defaultdict, deque
from typing import Optional

from .schemas import ActivityEvent, ActivityKind


class ActivityBus:
    def __init__(self, ring_size: int = 500):
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._ring: dict[str, deque] = defaultdict(lambda: deque(maxlen=ring_size))
        self._seq: dict[str, int] = defaultdict(int)

    def next_seq(self, run_id: str) -> int:
        self._seq[run_id] += 1
        return self._seq[run_id]

    async def publish(self, event: ActivityEvent) -> None:
        self._ring[event.run_id].append(event)
        for q in list(self._subs[event.run_id]):
            await q.put(event)

    def subscribe(self, run_id: str, after_seq: int = 0) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        # replay buffered events for reconnect/late joiners
        for ev in self._ring[run_id]:
            if ev.seq > after_seq:
                q.put_nowait(ev)
        self._subs[run_id].add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        self._subs[run_id].discard(q)

    def replay(self, run_id: str) -> list[ActivityEvent]:
        return list(self._ring[run_id])


bus = ActivityBus()


# ------------------------- mid-run steering (§7) -------------------------
class SteerRegistry:
    """Holds guidance injected into a live run; the runtime drains it between steps."""
    def __init__(self):
        self._pending: dict[str, list[str]] = {}

    def add(self, run_id: str, text: str) -> None:
        self._pending.setdefault(run_id, []).append(text)

    def drain(self, run_id: str) -> list[str]:
        return self._pending.pop(run_id, [])


steer = SteerRegistry()


class CancelRegistry:
    """Cooperative interrupt: mark a run to stop; the runtime checks between steps."""
    def __init__(self):
        self._flags: set[str] = set()

    def request(self, run_id: str) -> None:
        self._flags.add(run_id)

    def is_cancelled(self, run_id: str) -> bool:
        return run_id in self._flags

    def clear(self, run_id: str) -> None:
        self._flags.discard(run_id)


cancel = CancelRegistry()


# ------------------------- narration templates -------------------------
_PHRASES = {
    "web_search": ["Searching the web for '{q}'\u2026", "Looking up '{q}' online\u2026"],
    "parse_file": ["Reading {f} and extracting the rows\u2026", "Parsing {f}\u2026"],
    "erp.getInvoices": ["Querying the ERP for invoices\u2026", "Pulling invoice records\u2026"],
    "code_execution": ["Crunching the numbers\u2026", "Running the analysis\u2026"],
    "email.send": ["Preparing the email draft\u2026"],
    "rag.retrieve": ["Retrieving the most relevant passages\u2026"],
}
_ENTER = ["Handing off to the {a} agent\u2026", "Bringing in the {a} agent\u2026", "The {a} agent is taking this\u2026"]
_REASON = [
    "The figures from the two sources don't line up \u2014 reconciling before I continue.",
    "This looks consistent so far; moving to the next step.",
    "Weighing a couple of options here before deciding.",
    "Double-checking an assumption before I commit to it.",
]
_VERIFY = ["Double-checking the output against the source\u2026", "Verifying the result before returning\u2026"]


def narrate(kind: ActivityKind, ctx: dict) -> str:
    """Tier-1 deterministic narrator. Returns a friendly present-tense phrase."""
    if kind == ActivityKind.tool_call:
        tool = ctx.get("tool", "")
        pool = _PHRASES.get(tool) or [f"Calling {tool}\u2026"]
        return random.choice(pool).format(q=ctx.get("query", ""), f=ctx.get("file", "the file"))
    if kind == ActivityKind.agent_enter:
        return random.choice(_ENTER).format(a=ctx.get("agent", "next"))
    if kind == ActivityKind.reasoning:
        return ctx.get("text") or random.choice(_REASON)
    if kind == ActivityKind.verification:
        return random.choice(_VERIFY)
    return ctx.get("label", "")
