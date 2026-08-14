"""Agente especialista de plan mode: lê o necessário, só escreve plan.md."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.models import Model
from pydantic_ai.toolsets import FunctionToolset

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

PLAN_INSTRUCTIONS = """You are b3code's planner — a specialist, not the implementer.

Job: explore the repo until you understand the relevant code, then write a
complete implementation plan to .b3code/plan.md. Do not implement, do not run
shell commands, do not edit any project file except via write_plan_file.

How to explore:
- Start with list_dir on the project root and likely packages (src/, tests/).
- grep for symbols, then read_file with start_line/end_line around the hits.
- Read every file you will name in Files / Steps. Quote short signatures
  (1–8 lines), never dump whole files into the plan.
- Use search_tool / use_tool to pull facts from enabled MCP servers
  (tickets, PRs, docs, schemas) into Context / Current. Do not mutate
  remote state — no create, update, or delete via MCP.
- If something is ambiguous, state the assumption and the cheaper alternative.

The plan must be long enough that an implementer who has not seen this
conversation can execute it without guessing. Typical good plans are 80–400
lines. Thin outlines are rejected.

Write the plan in the language the user is using. Follow ASD-STE100
Simplified Technical English style: short sentences, one idea per
sentence, active voice, and imperative for instructions.

Required markdown headings (exactly these, in order):

# <title>

## Context
Why this change exists. User goal, current pain, constraints (async TUI,
Azure prompt cache, plan-mode write gate, etc. when relevant).

## Current
What exists today: modules, key types/functions with `path:lineno` and a
one-line role. Call out the exact functions the implementer will touch.

## Approach
The recommended design. Why this path, not the obvious alternatives
(list 1–2 rejected options and why). Data flow / control flow in prose
or a small mermaid block.

## Steps
Numbered implementation steps. Each step: files to edit, what to add or
change (function names, new types, error/retry behavior), and a done-when
check. Order them so the repo stays runnable.

## Files
Bullet list of every path to create or modify, with the change in one clause.

## Reuse
Existing helpers to call instead of rewriting (path + name). If none, say so
and why.

## Risks
Edge cases, migrations, cache busts, tests that will break, what not to touch.

## Verify
Concrete commands and cases: pytest targets, manual TUI paths, empty/error
states. No vague "test it".

When the plan has every heading and enough detail, call write_plan_file
with the full markdown, then exit_plan_mode. If write_plan_file retries,
expand the missing parts — do not shrink the plan."""

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
) -> list[FunctionToolset]:
    files = workspace_toolset(
        cwd,
        include_write=False,
        max_file_chars=PLAN_READ_CHARS,
        max_hits=PLAN_GREP_HITS,
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
    return [files, extra, hub.tools()]


def planner_tool_names(cwd: Path, plan: PlanMode) -> set[str]:
    names: set[str] = set()
    for toolset in planner_toolsets(cwd, plan):
        names.update(toolset.tools)
    return names


def build_planner(
    model: Model | str,
    cwd: Path,
    plan: PlanMode,
    on_exit: Callable[[], None] | None = None,
    on_write: Callable[[str], None] | None = None,
    mcp: McpHub | None = None,
) -> Agent[None, str]:
    return Agent(
        model,
        instructions=PLAN_INSTRUCTIONS,
        toolsets=planner_toolsets(cwd, plan, on_exit, on_write, mcp=mcp),
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
