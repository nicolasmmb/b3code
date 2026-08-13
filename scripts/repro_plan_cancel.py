"""Reproduz cancel no plan mode contra a LLM real.

    uv run python scripts/repro_plan_cancel.py
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from b3code.container import AppContainer
from b3code.services.chat import ChatEvent


async def main() -> None:
    cwd = Path(__file__).resolve().parents[1]
    container = AppContainer.build(cwd)
    chat = container.chat
    chat.enter_plan()
    events: list[ChatEvent] = []

    def on_event(event: ChatEvent) -> None:
        events.append(event)
        print(f"  event {event.kind!r} tool={event.tool!r} text={event.text[:80]!r}")

    print("model:", container.config.selected_model)
    print("plan.active:", chat.plan.active)
    task = asyncio.create_task(chat.enqueue("outline a 3-step plan to add a /status command", on_event))
    t0 = time.perf_counter()
    await asyncio.sleep(2.5)
    print(f"after 2.5s busy={chat.busy} events={len(events)} — calling cancel_current()")
    chat.cancel_current()
    try:
        await asyncio.wait_for(task, timeout=8)
        elapsed = time.perf_counter() - t0
        print(f"enqueue returned in {elapsed:.2f}s after cancel")
    except TimeoutError:
        print("TIMEOUT: enqueue still running 8s after cancel — cancel did not stop the run")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    kinds = [e.kind for e in events]
    print("kinds:", kinds)
    print("busy after:", chat.busy)
    print("plan.active after:", chat.plan.active)


if __name__ == "__main__":
    asyncio.run(main())
