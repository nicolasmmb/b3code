"""Factories de agent. INSTRUCTIONS é estático de propósito (cache Azure)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, ModelRetry
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.models import Model
from pydantic_ai_harness import CodeMode, Shell
from pydantic_ai_harness.planning import Planning
from pydantic_ai_harness.shell import LLM_API_KEY_ENV_PATTERNS
from pydantic_monty import MountDir

from b3code.config.schema import AppConfig
from b3code.libs.models import build_model
from b3code.services.permission import PermissionDenied, PermissionGate
from b3code.services.plan import PlanMode
from b3code.services.planner import build_planner
from b3code.tools.workspace import workspace_toolset
from b3code.utils.diffview import FileChange

# Estático de propósito: mudar instructions a cada turno invalida o cache Azure.
INSTRUCTIONS = (
    "You are b3code, a concise coding assistant. "
    "Use run_code to batch file tools (paths under /work). "
    "Prefer replace_in_file for edits; write_file only to create files. "
    "Use delete_file and move_file instead of rewriting. "
    "Use run_command for git/tests/lint. Last expression is the run_code return."
)

SHELL_TOOLS = frozenset(
    {"run_command", "start_command", "check_command", "stop_command"}
)


async def ensure_shell_args(gate: PermissionGate | None, args: Any) -> Any:
    if gate is None:
        return args
    command = (
        args["command"] if isinstance(args, dict) else getattr(args, "command", "")
    )
    try:
        await gate.ensure(command)
    except PermissionDenied as exc:
        raise ModelRetry(str(exc)) from exc
    return args


def build_coder(
    *,
    config: AppConfig,
    cwd: Path,
    gate: PermissionGate | None = None,
    on_change: Callable[[FileChange], None] | None = None,
    injected_model: Model | None = None,
) -> Agent[None, str]:
    model = injected_model or build_model(config)
    if injected_model is not None:
        return Agent(model, instructions=INSTRUCTIONS)
    hooks = Hooks()

    @hooks.on.before_tool_execute(tools=["run_command", "start_command"])
    async def gate_shell(_ctx: Any, *, call: Any, tool_def: Any, args: Any) -> Any:
        return await ensure_shell_args(gate, args)

    return Agent(
        model,
        instructions=INSTRUCTIONS,
        toolsets=[
            workspace_toolset(cwd, on_change=on_change),
        ],
        capabilities=[
            Shell(
                cwd=cwd,
                persist_cwd=True,
                default_timeout=120,
                denied_env_patterns=LLM_API_KEY_ENV_PATTERNS,
            ),
            CodeMode(
                tools=lambda ctx, td: td.name not in SHELL_TOOLS,
                mount=MountDir(
                    virtual_path="/work",
                    host_path=str(cwd),
                    mode="read-write",
                ),
                max_retries=3,
            ),
            hooks,
            Planning(),
        ],
    )


def build_planner_agent(
    *,
    config: AppConfig,
    cwd: Path,
    plan: PlanMode,
    on_exit: Callable[[], None] | None = None,
    on_write: Callable[[str], None] | None = None,
    injected_model: Model | None = None,
) -> Agent[None, str]:
    model = injected_model or build_model(config)
    if injected_model is not None:
        return Agent(model, instructions="You are b3code's planner. Do not implement.")
    return build_planner(
        model,
        cwd,
        plan,
        on_exit=on_exit,
        on_write=on_write,
    )
