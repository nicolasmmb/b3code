"""Factories de filho. Sem CodeMode, sem MCP, sem as tools de orquestração."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, ModelRetry
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.models import Model
from pydantic_ai_harness import Shell
from pydantic_ai_harness.shell import LLM_API_KEY_ENV_PATTERNS

from b3code.config.schema import AppConfig
from b3code.libs.models import build_model
from b3code.services.agents import ensure_shell_args
from b3code.services.permission import PermissionGate
from b3code.services.tasks import TaskRecord
from b3code.tools.workspace import workspace_toolset
from b3code.utils.diffview import FileChange
from b3code.utils.toolview import tool_title

KINDS = ("general-purpose", "explore", "plan")

_INSTRUCTIONS = {
    "explore": (
        "You are b3code's explore subagent. Read and search the repo. "
        "Do not edit files. Return a concise summary."
    ),
    "plan": (
        "You are b3code's plan subagent. Explore the repo and return a "
        "markdown plan. Do not edit files. Do not write plan.md."
    ),
    "general-purpose": (
        "You are b3code's implementer subagent. Use file tools and shell. "
        "Prefer replace_in_file for edits. Return a concise summary."
    ),
}


def build_subagent(
    kind: str,
    *,
    config: AppConfig,
    cwd: Path,
    gate: PermissionGate | None = None,
    on_change: Callable[[FileChange], None] | None = None,
    model: Model | None = None,
) -> Agent[None, str]:
    if kind not in _INSTRUCTIONS:
        raise ModelRetry(f"unknown subagent_type: {kind}")
    resolved = model or build_model(config)
    write = kind == "general-purpose"
    files = workspace_toolset(
        cwd, on_change=on_change if write else None, include_write=write
    )
    return Agent(
        resolved,
        instructions=_INSTRUCTIONS[kind],
        toolsets=[files],
        capabilities=_caps(kind, cwd, gate),
    )


def child_runner(
    *,
    config: AppConfig,
    cwd: Path,
    gate: PermissionGate | None,
    on_change: Callable[[FileChange], None] | None,
    model: Model | None,
) -> Callable[[TaskRecord, str], Any]:
    async def run(record: TaskRecord, prompt: str) -> str:
        agent = build_subagent(
            record.kind,
            config=config,
            cwd=cwd,
            gate=gate,
            on_change=on_change,
            model=model,
        )

        async def handler(_ctx: Any, events: Any) -> None:
            async for event in events:
                note_child_event(record, event)

        result = await agent.run(
            prompt,
            event_stream_handler=handler,
            cancellation_token=record.token,
        )
        return result.output or ""

    return run


def note_child_event(record: TaskRecord, event: Any) -> None:
    part = getattr(event, "part", None)
    name = getattr(part, "tool_name", "") or ""
    if not name:
        return
    record.note(tool_title(name, getattr(part, "args", None)))


def _caps(kind: str, cwd: Path, gate: PermissionGate | None) -> list[Any]:
    if kind == "plan":
        return []
    hooks = Hooks()

    @hooks.on.before_tool_execute(tools=["run_command", "start_command"])
    async def gate_shell(_ctx: Any, *, call: Any, tool_def: Any, args: Any) -> Any:
        return await ensure_shell_args(gate, args)

    return [
        Shell(
            cwd=cwd,
            persist_cwd=True,
            default_timeout=120,
            denied_env_patterns=LLM_API_KEY_ENV_PATTERNS,
        ),
        hooks,
    ]
