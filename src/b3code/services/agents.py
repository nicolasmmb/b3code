"""Factories de agent. INSTRUCTIONS é estático de propósito (cache)"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, ModelRetry
from pydantic_ai.capabilities import WebSearch
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.models import Model
from pydantic_ai_harness import CodeMode, FileSystem, Shell
from pydantic_ai_harness.shell import LLM_API_KEY_ENV_PATTERNS
from pydantic_monty import MountDir

from b3code.config.schema import AppConfig
from b3code.libs.models import build_model
from b3code.services.mcp import McpHub, is_mcp_tool
from b3code.services.permission import PermissionDenied, PermissionGate
from b3code.services.plan import PlanMode
from b3code.services.planner import build_planner
from b3code.services.questions import QuestionGate
from b3code.services.tasks import TaskHub
from b3code.tools.ask import ask_toolset
from b3code.tools.tasks import task_toolset
from b3code.tools.workspace import workspace_toolset
from b3code.utils.diffview import FileChange

# Estático de propósito: mudar instructions a cada turno invalida o cache Azure.
CODER_INSTRUCTIONS = (
    "You are b3code. You write correct, minimal and production-ready code. You do not speculate. You act.",
    "All file operations exist only inside run_code. Paths are always under /work.",
    "File tools available inside run_code: read_file, list_dir, grep, write_file, replace_in_file, delete_file, move_file.",
    "Never call these tools as top-level tools. They are not in the schema.",
    "Edits: use replace_in_file by default. Use write_file only to create new files.",
    "run_command is allowed only for git, tests and lint. Never use it to write or modify project files (no cat, no heredoc, no echo redirection).",
    "MCP tools: use search_tools. Call them as server_tool.",
    "When a choice is cheaper than an assumption, call ask_user_question. Do not guess.",
    "Use spawn_subagent only for exploration or review. Never nest subagents.",
    "After spawning a subagent or running a command, poll with get_command_or_subagent_output.",
    "In run_code, the last expression is the return value.",
    "Always respond in the language the user is using.",
    "Follow ASD-STE100 Simplified Technical English: short sentences, one idea per sentence, active voice, imperative mood for instructions.",
)

PLANNER_INSTRUCTIONS = (
    "You are b3code's Planner. You own planning. You never implement. Implementation is not your job.",
    "When you receive an idea, you immediately turn it into a clear, complete, and executable plan. No vague steps. No open questions left unanswered.",
    "When you receive a plan to implement, you transform it into a ruthless, zero-ambiguity execution plan. Every step must be concrete and ordered.",
    "When you receive a plan to review, you attack it. Find every weakness, every missing detail, every inefficiency. Then rewrite it better.",
    "When you receive a plan to explore, you dig deep, surface the real constraints and risks, and produce a decisive exploration strategy.",
    "When you receive a plan to test, you define exactly what must be tested, how, and what constitutes failure. No soft criteria.",
    "When you receive a plan to lint, you enforce strict quality standards. Anything that violates clarity, consistency or correctness gets corrected.",
    "You do not hedge. You do not say 'maybe', 'perhaps' or 'it could be'. You decide. You commit. You own the outcome of the plan.",
)


SHELL_TOOLS = frozenset(
    {"run_command", "start_command", "check_command", "stop_command"}
)
HOST_TOOLS = SHELL_TOOLS | {
    "ask_user_question",
    "spawn_subagent",
    "get_command_or_subagent_output",
    "kill_command_or_subagent",
}


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


def _host_tool(_ctx: Any, tool_def: Any) -> bool:
    return tool_def.name not in HOST_TOOLS and not is_mcp_tool(tool_def)


def build_coder(
    *,
    config: AppConfig,
    cwd: Path,
    gate: PermissionGate | None = None,
    on_change: Callable[[FileChange], None] | None = None,
    injected_model: Model | None = None,
    mcp: McpHub | None = None,
    questions: QuestionGate | None = None,
    tasks: TaskHub | None = None,
) -> Agent[None, str]:
    model = injected_model or build_model(config)
    if injected_model is not None:
        return Agent(model, instructions=CODER_INSTRUCTIONS)
    hooks = Hooks()
    hub = mcp or McpHub(config)

    @hooks.on.before_tool_execute(tools=["run_command", "start_command"])
    async def gate_shell(_ctx: Any, *, call: Any, tool_def: Any, args: Any) -> Any:
        return await ensure_shell_args(gate, args)

    return Agent(
        model,
        instructions=CODER_INSTRUCTIONS,
        toolsets=[
            workspace_toolset(cwd, on_change=on_change),
            ask_toolset(questions or QuestionGate()),
            task_toolset(tasks or TaskHub()),
            *hub.toolsets(mutate=True),
        ],
        capabilities=[
            Shell(
                cwd=cwd,
                persist_cwd=True,
                default_timeout=120,
                denied_env_patterns=LLM_API_KEY_ENV_PATTERNS,
            ),
            CodeMode(
                tools=_host_tool,
                mount=MountDir(
                    virtual_path="/work",
                    host_path=str(cwd),
                    mode="read-write",
                ),
                max_retries=3,
            ),
            # FileSystem(),
            WebSearch(),
            hooks,
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
    mcp: McpHub | None = None,
) -> Agent[None, str]:
    model = injected_model or build_model(config)
    if injected_model is not None:
        return Agent(
            model,
            instructions="You are b3code's planner. Do not implement.",
            capabilities=[WebSearch()],
        )
    return build_planner(
        model,
        cwd,
        plan,
        on_exit=on_exit,
        on_write=on_write,
        mcp=mcp or McpHub(config),
    )
