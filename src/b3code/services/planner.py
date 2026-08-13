"""Agente especialista de plan mode: lê pouco, só escreve plan.md."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.toolsets import FunctionToolset

from b3code.services.plan import PlanMode
from b3code.tools.workspace import workspace_toolset

PLAN_INSTRUCTIONS = (
    "You are b3code's planner. Produce a short implementation plan. "
    "Do not implement, run commands, or edit project files. "
    "Cite paths only — never paste large file bodies into the plan. "
    "Keep .b3code/plan.md under 2000 lines. "
    "Sections: Context, Approach, Files, Reuse, Verify. "
    "When ready, write_plan_file then exit_plan_mode."
)

PLAN_READ_CHARS = 8_000
PLAN_GREP_HITS = 20


def planner_toolsets(
    cwd: Path,
    plan: PlanMode,
    on_exit: Callable[[], None] | None = None,
) -> list[FunctionToolset]:
    files = workspace_toolset(
        cwd,
        include_write=False,
        max_file_chars=PLAN_READ_CHARS,
        max_hits=PLAN_GREP_HITS,
    )

    def write_plan_file(content: str) -> str:
        """Replace .b3code/plan.md with a concise markdown plan."""
        plan.write(content)
        return f"wrote {plan.plan_path.name} ({len(content.splitlines())} lines)"

    def exit_plan_mode() -> str:
        """Present plan.md for human approval. Do not implement."""
        if on_exit is not None:
            on_exit()
        return "plan ready for approval" if plan.read() else "no plan.md yet"

    extra = FunctionToolset(tools=[write_plan_file, exit_plan_mode])
    return [files, extra]


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
) -> Agent[None, str]:
    return Agent(
        model,
        instructions=PLAN_INSTRUCTIONS,
        toolsets=planner_toolsets(cwd, plan, on_exit),
    )


def slim_plan_note(plan: PlanMode) -> str:
    if plan.read():
        return "plan written to .b3code/plan.md"
    return "plan mode (no plan.md yet)"
