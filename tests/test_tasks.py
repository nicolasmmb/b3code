import asyncio

import pytest
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.models.test import TestModel

from b3code.config.schema import AppConfig
from b3code.services.events import format_elapsed, task_event
from b3code.services.subagents import build_subagent, note_child_event
from b3code.services.tasks import MAX_RUNNING, STEPS_CAP, TaskHub, TaskRecord
from b3code.tools.tasks import task_toolset


async def _ok(record: TaskRecord, prompt: str) -> str:
    record.activity = "read_file"
    await asyncio.sleep(0)
    return f"done:{prompt}"


async def _hang(record: TaskRecord, prompt: str) -> str:
    await asyncio.Event().wait()
    return prompt


async def test_spawn_background_and_snapshot():
    hub = TaskHub(runner=_ok)
    text = await hub.spawn("hi", "look around", "explore", background=True)
    assert text.startswith("started sa-")
    task_id = text.split()[1]
    await asyncio.sleep(0.05)
    snap = await hub.snapshot([task_id])
    assert "done" in snap
    assert hub.records[task_id].status == "done"


async def test_kill_cancels_token():
    hub = TaskHub(runner=_hang)
    text = await hub.spawn("x", "wait", "explore", background=True)
    task_id = text.split()[1]
    await asyncio.sleep(0)
    assert "cancelled" in await hub.kill(task_id)
    assert hub.records[task_id].status == "cancelled"
    assert hub.records[task_id].handle is None


async def test_cap_and_unknown_kind():
    hub = TaskHub(runner=_hang)
    for i in range(MAX_RUNNING):
        await hub.spawn("x", f"t{i}", "explore", background=True)
    with pytest.raises(ModelRetry, match="max"):
        await hub.spawn("x", "extra", "explore", background=True)
    with pytest.raises(ModelRetry, match="unknown"):
        await hub.spawn("x", "bad", "nope", background=True)
    await hub.kill_all()
    assert hub.running_count() == 0


async def test_snapshot_timeout_uses_wait():
    hub = TaskHub(runner=_hang)
    text = await hub.spawn("x", "wait", "explore", background=True)
    task_id = text.split()[1]
    snap = await hub.snapshot([task_id], timeout_ms=10)
    assert "running" in snap
    await hub.kill(task_id)


async def test_toolset_names():
    names = set(task_toolset(TaskHub(runner=_ok)).tools)
    assert names == {
        "spawn_subagent",
        "get_command_or_subagent_output",
        "kill_command_or_subagent",
    }


def test_build_subagent_tools(tmp_path):
    cfg = AppConfig(use_provider_gateway=False, selected_model="openai:gpt-4o")
    explore = build_subagent("explore", config=cfg, cwd=tmp_path, model=TestModel())
    plan = build_subagent("plan", config=cfg, cwd=tmp_path, model=TestModel())
    general = build_subagent(
        "general-purpose", config=cfg, cwd=tmp_path, model=TestModel()
    )
    assert "write_file" not in _names(explore)
    assert "write_file" not in _names(plan)
    assert "write_file" in _names(general)
    assert not any(
        type(cap).__name__ == "Shell" for cap in plan.root_capability.capabilities
    )


async def _notes(record: TaskRecord, prompt: str) -> str:
    record.note("Read README.md")
    record.note("Read README.md")
    record.note('Searched "TaskHub" in src')
    await asyncio.sleep(0)
    return "found 3 call sites"


async def test_note_emits_ticks_and_snapshot_lists_steps():
    seen: list[tuple[str, bool]] = []
    hub = TaskHub(
        runner=_notes,
        on_event=lambda rec, terminal: seen.append((rec.activity, terminal)),
    )
    text = await hub.spawn("hi", "look around", "explore", background=True)
    task_id = text.split()[1]
    await asyncio.sleep(0.05)
    assert seen[0] == ("", False)
    assert ("Read README.md", False) in seen
    assert ('Searched "TaskHub" in src', False) in seen
    assert seen[-1][1] is True
    snap = await hub.snapshot([task_id])
    assert f"{task_id} done (explore)" in snap
    assert "s" in snap
    assert "Read README.md" in snap
    assert 'Searched "TaskHub" in src' in snap
    assert "found 3 call sites" in snap


def test_note_dedupes_and_caps_steps():
    rec = TaskRecord(id="sa-x", kind="explore", description="x", background=True)
    ticks = []
    rec.on_tick = ticks.append
    assert rec.note("Read a") is True
    assert rec.note("Read a") is False
    assert rec.note("  ") is False
    assert len(ticks) == 1
    for i in range(STEPS_CAP + 5):
        rec.note(f"step {i}")
    assert len(rec.steps) == STEPS_CAP
    assert rec.steps[0] == "step 5"
    assert rec.steps[-1] == f"step {STEPS_CAP + 4}"


def test_task_event_stable_id_and_compact_title():
    rec = TaskRecord(
        id="sa-deadbeef", kind="explore", description="look around", background=True
    )
    rec.note("Read README.md")
    start = task_event(rec, terminal=False)
    assert start.call_id == "sa-deadbeef"
    assert start.text == "running"
    assert "· Read README.md" in start.output
    assert start.tool == "subagent"
    assert start.detail.startswith("explore · look around · Read README.md ·")
    assert start.detail.endswith("s")
    rec.status = "done"
    rec.output = "found 3 sites"
    end = task_event(rec, terminal=True)
    assert end.call_id == "sa-deadbeef"
    assert end.text == "done"
    assert "Read README.md" in end.output
    assert "found 3 sites" in end.output
    assert "failed" not in end.detail
    assert end.detail.startswith("explore · look around ·")


def test_task_event_failed_and_cancelled():
    rec = TaskRecord(id="sa-x", kind="explore", description="look", background=True)
    rec.status = "failed"
    rec.output = "boom"
    failed = task_event(rec, terminal=True)
    assert failed.text == "failed"
    assert "failed" in failed.detail
    assert "boom" in failed.output
    rec.status = "cancelled"
    rec.output = ""
    rec.steps.clear()
    cancelled = task_event(rec, terminal=True)
    assert cancelled.text == "cancelled"
    assert cancelled.call_id == "sa-x"
    assert cancelled.output


def test_note_child_event_uses_tool_title():
    rec = TaskRecord(id="sa-x", kind="explore", description="x", background=True)

    class Part:
        tool_name = "read_file"
        args = {"path": "README.md"}

    class Ev:
        part = Part()

    note_child_event(rec, Ev())
    note_child_event(rec, object())
    assert rec.activity == "Read README.md"
    assert rec.steps == ["Read README.md"]


def test_format_elapsed():
    assert format_elapsed(8) == "8s"
    assert format_elapsed(60) == "1m"
    assert format_elapsed(162) == "2m 42s"
    assert format_elapsed(3600) == "1h"


def test_note_child_event_skips_placeholder_title():
    rec = TaskRecord(id="sa-x", kind="explore", description="x", background=True)

    class Part:
        tool_name = "read_file"
        args = {}

    class Ev:
        part = Part()

    note_child_event(rec, Ev())
    assert rec.steps == []
    assert rec.activity == ""


def _names(agent) -> set[str]:
    names: set[str] = set()
    for toolset in getattr(agent, "toolsets", ()) or ():
        tools = getattr(toolset, "tools", None)
        if isinstance(tools, dict):
            names.update(tools)
    return names
