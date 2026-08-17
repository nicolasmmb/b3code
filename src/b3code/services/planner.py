"""Agente especialista de plan mode: lê o necessário, só escreve plan.md."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.models import Model
from pydantic_ai.toolsets import FunctionToolset

from b3code.config.schema import AppConfig
from b3code.services.mcp import McpHub
from b3code.services.plan import PlanMode
from b3code.tools.workspace import workspace_toolset
from b3code.utils.planmeta import plan_meta

__all__ = [
    "PLAN_INSTRUCTIONS",
    "build_planner",
    "plan_meta",
    "planner_tool_names",
    "planner_toolsets",
    "slim_plan_note",
]

PLAN_INSTRUCTIONS = """
You are b3code’s Planner. You are a specialist, not an implementer.

CORE RULES (never violate)
- Explore the repository until you fully understand the relevant code.
- Write one complete implementation plan to .b3code/plan.md.
- Do NOT implement any code.
- Do NOT run shell commands that mutate the repository.
- Do NOT edit any project file except through the write_plan_file tool.
- Do NOT create, update, or delete remote state via MCP (tickets, PRs, etc.).

EXPLORATION PROTOCOL (follow in order)
1. list_dir on the project root and on likely packages (src/, tests/, packages/, apps/, etc.).
2. grep for the key symbols, types, and functions mentioned by the user or implied by the task.
3. read_file with tight start_line/end_line around every hit you will reference.
4. Read every file you will list under ## Files or ## Steps.
5. Quote only short signatures (1–8 lines). Never dump whole files into the plan.
6. If an MCP server is enabled, use search_tools only to gather facts into Context / Current. Never mutate.

If anything is ambiguous:
- State the assumption clearly.
- State the cheaper alternative you rejected and why.

PLAN QUALITY REQUIREMENTS
- The plan must be long enough that an implementer who has never seen this conversation can execute it without guessing.
- Typical good plans: 80–400 lines.
- Thin outlines, bullet-point skeletons, or missing sections are rejected.
- Write the plan in the same language the user is using.
- Follow ASD-STE100 Simplified Technical in actual language:

REQUIRED MARKDOWN STRUCTURE (exactly these headings, in this order)

# <concise title that names the change>

## Context
Why this change exists.
- User goal
- Current pain
- Constraints that matter (async TUI, Azure prompt cache, plan-mode write gate, etc.)

## Current
What exists today.
- Modules, key types and functions with `path:lineno`
- One-line role for each
- Explicitly name the exact functions the implementer will touch

## Approach
The recommended design.
- Why this path was chosen
- 1–2 rejected alternatives and the reason each was rejected
- Data flow / control flow in prose or a small mermaid block

## Steps
Numbered implementation steps.
Each step must contain:
- files to edit
- what to add or change (function names, new types, error/retry behavior)
- a concrete “done-when” check
Order the steps so the repository stays runnable after every step.

## Files
Bullet list of every path that will be created or modified, with the change described in one clause.

## Reuse
Existing helpers the implementer must call instead of rewriting (path + name).
If none exist, say so and explain why.

## Risks
Edge cases, migrations, cache invalidation, tests that will break, areas that must not be touched.

## Verify
Concrete commands and cases:
- exact pytest targets
- manual TUI paths
- empty / error / boundary states
No vague “test it”.

FINAL ACTIONS
When the plan contains every required heading and has enough detail:
1. Call write_plan_file with the full markdown content.
2. Call exit_plan_mode.

If write_plan_file is rejected or asks for more detail, expand the missing parts. Never shrink the plan.

"""

PLAN_READ_CHARS = 48_000
PLAN_GREP_HITS = 60
_MIN_CHARS = 1_200
_HEADINGS = (
    "## Context",
    "## Current",
    "## Approach",
    "## Steps",
    "## Files",
    "## Reuse",
    "## Risks",
    "## Verify",
)


def planner_toolsets(
    cwd: Path,
    plan: PlanMode,
    on_exit: Callable[[], None] | None = None,
    on_write: Callable[[str], None] | None = None,
    mcp: McpHub | None = None,
    *,
    skip_dirs: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (),
    skip_exts: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (),
) -> list:
    files = workspace_toolset(
        cwd,
        include_write=False,
        max_file_chars=PLAN_READ_CHARS,
        max_hits=PLAN_GREP_HITS,
        skip_dirs=skip_dirs,
        skip_exts=skip_exts,
    )

    def write_plan_file(content: str) -> str:
        """Write the full detailed markdown plan to .b3code/plan.md."""
        problem = _plan_gaps(content)
        if problem:
            raise ModelRetry(problem)
        plan.write(content)
        if on_write is not None:
            on_write(content)
        return f"wrote {plan.plan_path.name} ({len(content.splitlines())} lines)"

    def exit_plan_mode() -> str:
        """Present plan.md for human approval. Do not implement."""
        problem = _plan_gaps(plan.read())
        if problem:
            raise ModelRetry(problem + " — expand the plan with write_plan_file first")
        if on_exit is not None:
            on_exit()
        return "plan ready for approval"

    extra = FunctionToolset(tools=[write_plan_file, exit_plan_mode])
    hub = mcp or McpHub()
    return [files, extra, *hub.toolsets(mutate=False)]


def planner_tool_names(
    cwd: Path,
    plan: PlanMode,
    *,
    skip_dirs: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (),
    skip_exts: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (),
) -> set[str]:
    names: set[str] = set()
    for toolset in planner_toolsets(
        cwd, plan, skip_dirs=skip_dirs, skip_exts=skip_exts
    ):
        tools = getattr(toolset, "tools", None)
        if tools is not None:
            names.update(tools)
    return names


def build_planner(
    model: Model | str,
    cwd: Path,
    plan: PlanMode,
    on_exit: Callable[[], None] | None = None,
    on_write: Callable[[str], None] | None = None,
    mcp: McpHub | None = None,
    *,
    skip_dirs: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (),
    skip_exts: list[str] | tuple[str, ...] | set[str] | frozenset[str] = (),
    config: AppConfig | None = None,
) -> Agent[None, str]:
    from b3code.services.agents import thinking_cap

    caps = []
    if config is not None and (cap := thinking_cap(config)):
        caps.append(cap)
    return Agent(
        model,
        instructions=PLAN_INSTRUCTIONS,
        toolsets=planner_toolsets(
            cwd,
            plan,
            on_exit,
            on_write,
            mcp=mcp,
            skip_dirs=skip_dirs,
            skip_exts=skip_exts,
        ),
        capabilities=caps or None,
        retries=2,
    )


def _plan_gaps(content: str) -> str | None:
    body = content.strip()
    if len(body) < _MIN_CHARS:
        return (
            f"plan too thin ({len(body)} chars, need ≥ {_MIN_CHARS}). "
            "Add concrete files, function names, steps, and verify cases."
        )
    missing = [h for h in _HEADINGS if h.lower() not in body.lower()]
    if missing:
        return "missing sections: " + ", ".join(missing)
    return None


def slim_plan_note(plan: PlanMode) -> str:
    if plan.read():
        return "plan written to .b3code/plan.md"
    return "plan mode (no plan.md yet)"
