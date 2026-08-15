import asyncio

import pytest
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.models.test import TestModel

from b3code.config.schema import AppConfig
from b3code.services.subagents import build_subagent
from b3code.services.tasks import MAX_RUNNING, TaskHub, TaskRecord
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
    assert not any(type(cap).__name__ == "Shell" for cap in plan.root_capability.capabilities)


def _names(agent) -> set[str]:
    names: set[str] = set()
    for toolset in getattr(agent, "toolsets", ()) or ():
        tools = getattr(toolset, "tools", None)
        if isinstance(tools, dict):
            names.update(tools)
    return names
