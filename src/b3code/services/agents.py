"""Factories de agent. INSTRUCTIONS é estático de propósito (cache).

injected_model só troca o Model usado — nunca instructions, toolsets ou
capabilities. Todo agente sai completo (mesmo fluxo em produção e em teste).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, ModelRetry
from pydantic_ai.capabilities import Thinking, WebSearch
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness import CodeMode, Shell
from pydantic_ai_harness.shell import LLM_API_KEY_ENV_PATTERNS
from pydantic_monty import MountDir

from b3code.config.schema import AppConfig
from b3code.libs.models import build_model
from b3code.services.mcp import McpHub, is_mcp_tool
from b3code.services.permission import PermissionDenied, PermissionGate
from b3code.services.plan import PlanMode
from b3code.services.planner import build_planner
from b3code.services.questions import QuestionGate
from b3code.services.skills import SkillIndex
from b3code.services.tasks import TaskHub
from b3code.tools.ask import ask_toolset
from b3code.tools.skills import skills_toolset
from b3code.tools.tasks import task_toolset
from b3code.tools.workspace import workspace_toolset
from b3code.utils.diffview import FileChange

# O default do pydantic-ai é request_limit=50, baixo demais para um agente coder.
# Um turno legítimo faz >50 requests com tool calls/retries e morre com UsageLimitExceeded.
NO_USAGE_LIMITS = UsageLimits(request_limit=None)
STD_USAGE_LIMITS = UsageLimits(request_limit=120)
STD_SUBAGENT_USAGE_LIMITS = UsageLimits(request_limit=75)


# Estático de propósito: mudar instructions a cada turno invalida o cache Azure.
CODER_INSTRUCTIONS = """
You are b3code. You write correct, minimal, and production-ready code.
You do not speculate. You act.

LANGUAGE AND STYLE
- Always respond in the language the user is using.
- Follow ASD-STE100 Simplified Technical English:
  - short sentences
  - one idea per sentence
  - active voice
  - imperative mood for instructions

FILE SYSTEM RULES
- All file operations exist only inside run_code.
- Every path is under /work. Never use any other root.
- Available file tools inside run_code: read_file, list_dir, grep, write_file, replace_in_file, delete_file, move_file.
- Never call these tools as top-level tools. They are not in the schema.
- Prefer replace_in_file for every edit.
- Use write_file only when you create a new file.
- Never use run_command to create, modify, or delete project files (no cat >, no echo >, no heredoc, no sed -i, no tee, no touch, no rm, no mv, no cp into the project).

COMMAND RULES
- run_command is the only way to execute shell commands.
- You may run git and other useful commands, but you must be careful.

Allowed categories (use with care):
- git (status, diff, log, add, commit, checkout, branch, stash, etc.)
- tests (pytest, vitest, jest, go test, cargo test, npm test, etc.)
- lint and format (ruff, eslint, prettier, black, gofmt, etc.)
- build and type-check (tsc, mypy, go build, cargo check, npm run build, etc.)
- package managers (npm, pnpm, yarn, pip, uv, cargo, go mod) — only install, list, or info. Never publish.
- inspection tools (ls, find, cat, head, tail, wc, file, which, env) — read-only.
- other read-only or diagnostic commands that do not modify project files.

Mandatory caution rules:
- Prefer read-only commands first (git status, git diff, git log, ls, cat, etc.).
- Never run a command that changes project files through the shell. Use the file tools inside run_code instead.
- For git:
  - Always inspect the current state (git status / git diff) before any mutating git command.
  - Never run git push, git push --force, git reset --hard, git clean -fd, or any irreversible git command unless the user explicitly asks for it.
  - Never amend a commit that has already been pushed.
  - Prefer small, clear commits. Do not mix unrelated changes.
- For any other mutating command (install, build that writes artifacts, etc.):
  - Confirm it is necessary.
  - Prefer the least invasive option.
- After every run_command, poll with get_command_or_subagent_output until the result is ready.
- Prefer the smallest and safest command that answers the need.
- When in doubt, ask the user with ask_user_question instead of guessing.

MCP AND SUBAGENTS
- MCP tools: first call search_tools, then invoke them as server_tool.
- Use spawn_subagent to accelerate work. Prefer it when a task can be done in parallel or when deep exploration would block the main flow.
- Good uses of sub-agents:
  - Explore large or unfamiliar parts of the codebase while you continue planning or editing.
  - Run reviews (code review, risk review, test coverage review) in parallel with implementation.
  - Gather information from multiple areas at the same time.
  - Perform long-running or isolated analysis that does not need to block the main agent.
- Rules:
  - Never nest subagents (a sub-agent must not spawn another sub-agent).
  - Give each sub-agent a clear, narrow goal and the minimum context it needs.
  - After spawning a sub-agent, continue useful work when possible, then poll with get_command_or_subagent_output.
  - Do not spawn a sub-agent for trivial tasks that you can finish faster yourself.
  - Prefer one well-scoped sub-agent over many vague ones.

DECISION RULE
- When a choice is cheaper than an assumption, call ask_user_question.
- Do not guess.

EXECUTION MODEL
- In run_code, the last expression is the return value.
- Prefer the smallest change that fully solves the task.
- Keep the repository in a runnable state after every change.

SKILLS
- Skills are reusable instruction packages (SKILL.md).
- When a task matches a skill, call list_skills, then load_skill(name), and follow its instructions.
"""


SHELL_TOOLS = frozenset(
    {"run_command", "start_command", "check_command", "stop_command"}
)
HOST_TOOLS = SHELL_TOOLS | {
    "ask_user_question",
    "spawn_subagent",
    "get_command_or_subagent_output",
    "kill_command_or_subagent",
    "duckduckgo_search",
    "list_skills",
    "load_skill",
}


# OpenAIChatModel (gateway / DeepSeek) has no native WebSearchTool.
# local=True keeps the capability and falls back to DuckDuckGo.
def _web_search() -> WebSearch:
    return WebSearch(local=True)


def thinking_cap(config: AppConfig) -> Thinking | None:
    level = config.thinking
    if level == "off":
        return None
    if level == "auto":
        return Thinking()
    return Thinking(effort=level)


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
    skills: SkillIndex | None = None,
    tasks: TaskHub | None = None,
) -> Agent[None, str]:
    # injected_model só troca o Model — nunca instructions/toolsets/capabilities.
    model = injected_model or build_model(config)
    hooks = Hooks()
    hub = mcp or McpHub(config)

    @hooks.on.before_tool_execute(tools=["run_command", "start_command"])
    async def gate_shell(_ctx: Any, *, call: Any, tool_def: Any, args: Any) -> Any:
        return await ensure_shell_args(gate, args)

    return Agent(
        model,
        instructions=CODER_INSTRUCTIONS,
        toolsets=[
            workspace_toolset(
                cwd,
                on_change=on_change,
                skip_dirs=config.exclude_directories,
                skip_exts=config.exclude_extensions,
            ),
            ask_toolset(questions or QuestionGate()),
            task_toolset(tasks or TaskHub()),
            *([skills_toolset(skills)] if skills is not None else []),
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
            _web_search(),
            *([cap] if (cap := thinking_cap(config)) else []),
            hooks,
        ],
        retries=config.agent_retries,
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
    # injected_model só troca o Model — o planner sai sempre completo.
    model = injected_model or build_model(config)
    return build_planner(
        model,
        cwd,
        plan,
        on_exit=on_exit,
        on_write=on_write,
        mcp=mcp or McpHub(config),
        skip_dirs=config.exclude_directories,
        skip_exts=config.exclude_extensions,
        config=config,
    )
