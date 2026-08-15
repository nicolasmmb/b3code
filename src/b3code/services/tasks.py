"""Registro de subagentes. O hub não constrói o Agent — recebe um runner."""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic_ai import CancellationToken
from pydantic_ai.exceptions import ModelRetry

KINDS = frozenset({"general-purpose", "explore", "plan"})
MAX_RUNNING = 3
FG_TIMEOUT_S = 180.0
OUTPUT_CAP = 8_000
STEPS_CAP = 40
SNAPSHOT_STEPS = 8

TaskStatus = str
Runner = Callable[["TaskRecord", str], Awaitable[str]]
OnTask = Callable[["TaskRecord", bool], None]
OnTick = Callable[["TaskRecord"], None]


@dataclass
class TaskRecord:
    id: str
    kind: str
    description: str
    background: bool
    status: TaskStatus = "running"
    output: str = ""
    handle: asyncio.Task[None] | None = None
    token: CancellationToken = field(default_factory=CancellationToken)
    started: float = field(default_factory=time.monotonic)
    activity: str = ""
    steps: list[str] = field(default_factory=list)
    on_tick: OnTick | None = field(default=None, repr=False, compare=False)

    @property
    def elapsed(self) -> int:
        return max(0, int(time.monotonic() - self.started))

    def note(self, title: str) -> bool:
        text = title.strip()
        if not text or text == self.activity:
            return False
        self.activity = text
        self.steps.append(text)
        if len(self.steps) > STEPS_CAP:
            del self.steps[:-STEPS_CAP]
        if self.on_tick is not None:
            self.on_tick(self)
        return True


class TaskHub:
    def __init__(
        self, runner: Runner | None = None, on_event: OnTask | None = None
    ) -> None:
        self.runner = runner
        self.on_event = on_event
        self.records: dict[str, TaskRecord] = {}

    def running_count(self) -> int:
        return sum(1 for rec in self.records.values() if rec.status == "running")

    async def spawn(
        self,
        prompt: str,
        description: str,
        subagent_type: str = "general-purpose",
        background: bool = True,
    ) -> str:
        record = self._open(description, subagent_type, background)
        task = asyncio.create_task(self._run(record, prompt), name=record.id)
        record.handle = task
        self._emit(record, terminal=False)
        if background:
            return f"started {record.id} ({record.kind}): {description}"
        return await self._await_foreground(record, task)

    async def snapshot(self, task_ids: list[str], timeout_ms: int | None = None) -> str:
        handles = [
            self.records[i].handle for i in task_ids if _live(self.records.get(i))
        ]
        if timeout_ms and handles:
            await asyncio.wait(handles, timeout=max(timeout_ms, 0) / 1000)
        return "\n".join(self._line(i) for i in task_ids)

    async def kill(self, task_id: str) -> str:
        record = self.records.get(task_id)
        if record is None:
            raise ModelRetry(f"unknown task {task_id}")
        await _cancel_record(record)
        return f"cancelled {task_id}"

    def cancel_all(self) -> None:
        for record in self.records.values():
            if record.status != "running":
                continue
            record.token.cancel()
            if record.handle is not None:
                record.handle.cancel()

    async def kill_all(self) -> None:
        ids = [rec.id for rec in self.records.values() if rec.status == "running"]
        for task_id in ids:
            await self.kill(task_id)

    def _open(self, description: str, kind: str, background: bool) -> TaskRecord:
        if kind not in KINDS:
            raise ModelRetry(f"unknown subagent_type: {kind}")
        if self.running_count() >= MAX_RUNNING:
            raise ModelRetry(f"max {MAX_RUNNING} running subagents")
        if self.runner is None:
            raise ModelRetry("subagents are not configured")
        record = TaskRecord(
            id=f"sa-{uuid.uuid4().hex[:8]}",
            kind=kind,
            description=description,
            background=background,
            on_tick=self._tick,
        )
        self.records[record.id] = record
        return record

    async def _run(self, record: TaskRecord, prompt: str) -> None:
        assert self.runner is not None
        try:
            output = await self.runner(record, prompt)
            if record.status == "running":
                record.status = "done"
                record.output = output[:OUTPUT_CAP]
        except asyncio.CancelledError:
            record.status = "cancelled"
        except Exception as exc:
            record.status = "failed"
            record.output = str(exc)[:OUTPUT_CAP]
        finally:
            record.handle = None
            self._emit(record, terminal=True)

    async def _await_foreground(
        self, record: TaskRecord, task: asyncio.Task[None]
    ) -> str:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=FG_TIMEOUT_S)
        except TimeoutError:
            await self.kill(record.id)
            return f"{record.id} timed out"
        return record.output or record.status

    def _tick(self, record: TaskRecord) -> None:
        self._emit(record, terminal=False)

    def _emit(self, record: TaskRecord, *, terminal: bool) -> None:
        if self.on_event is not None:
            self.on_event(record, terminal)

    def _line(self, task_id: str) -> str:
        record = self.records.get(task_id)
        if record is None:
            return f"{task_id}: unknown"
        head = f"{record.id} {record.status} ({record.kind}) {record.elapsed}s"
        if record.status == "running":
            extra = f" — {record.activity}" if record.activity else ""
            return head + extra
        parts = [head]
        for step in record.steps[-SNAPSHOT_STEPS:]:
            parts.append(f"  · {step}")
        body = record.output.replace("\n", " ").strip()
        if body:
            parts.append("  —")
            parts.append(f"  {body[:200]}")
        return "\n".join(parts)


def _live(record: TaskRecord | None) -> bool:
    return bool(record is not None and record.handle is not None)


async def _cancel_record(record: TaskRecord) -> None:
    record.token.cancel()
    handle = record.handle
    if handle is None:
        record.status = "cancelled"
        return
    handle.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await handle
    record.status = "cancelled"
