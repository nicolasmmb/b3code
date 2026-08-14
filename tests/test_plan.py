from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelRetry

from b3code.services.plan import PlanMode
from b3code.services.planner import (
    PLAN_INSTRUCTIONS,
    plan_meta,
    planner_tool_names,
    planner_toolsets,
)
from b3code.tools.workspace import workspace_toolset


def test_can_write_inactive_allows_everything(tmp_path: Path):
    mode = PlanMode(tmp_path)
    assert mode.active is False
    assert mode.can_write(tmp_path / "a.py") is True
    assert mode.can_write(mode.plan_path) is True


def test_can_write_active_only_plan_md(tmp_path: Path):
    mode = PlanMode(tmp_path)
    mode.enter()
    assert mode.can_write(tmp_path / "src" / "a.py") is False
    assert mode.can_write(mode.plan_path) is True
    mode.exit()
    assert mode.can_write(tmp_path / "src" / "a.py") is True


def test_write_file_blocked_in_plan_mode(tmp_path: Path):
    mode = PlanMode(tmp_path)
    mode.enter()
    fns = {
        name: tool.function
        for name, tool in workspace_toolset(
            tmp_path, can_write=mode.can_write
        ).tools.items()
    }
    with pytest.raises(ModelRetry, match="plan mode"):
        fns["write_file"]("a.py", "nope")
    out = fns["write_file"](".b3code/plan.md", "# plan\n")
    assert "plan.md" in out
    assert mode.read().startswith("# plan")


def test_plan_meta_extracts_title_and_sections():
    title, heads, n = plan_meta("# Add auth\n\n## Context\nwhy\n\n## Steps\n1.\n")
    assert title == "Add auth"
    assert heads == ["Context", "Steps"]
    assert n == 7


def test_plan_read_empty(tmp_path: Path):
    assert PlanMode(tmp_path).read() == ""


def test_planner_has_no_write_or_shell(tmp_path: Path):
    names = planner_tool_names(tmp_path, PlanMode(tmp_path))
    assert "write_file" not in names
    assert "replace_in_file" not in names
    assert "delete_file" not in names
    assert "move_file" not in names
    assert "run_command" not in names
    assert "write_plan_file" in names
    assert "exit_plan_mode" in names
    assert "read_file" in names
    assert "grep" in names
    assert "search_tool" in names
    assert "use_tool" in names
    assert "search_tool" in PLAN_INSTRUCTIONS
    assert "Do not mutate" in PLAN_INSTRUCTIONS


def _write_plan(tmp_path: Path):
    mode = PlanMode(tmp_path)
    tools = {}
    for toolset in planner_toolsets(tmp_path, mode):
        tools.update({name: t.function for name, t in toolset.tools.items()})
    return tools["write_plan_file"], tools["exit_plan_mode"], mode


def test_write_plan_rejects_stub(tmp_path: Path):
    write, exit_fn, _mode = _write_plan(tmp_path)
    with pytest.raises(ModelRetry, match="too thin"):
        write("# hi\n\nshort")
    with pytest.raises(ModelRetry, match="write_plan_file"):
        exit_fn()


def test_write_plan_requires_sections(tmp_path: Path):
    write, exit_fn, mode = _write_plan(tmp_path)
    body = "# Title\n\n" + ("word " * 400)
    with pytest.raises(ModelRetry, match="missing sections"):
        write(body)
    full = "\n\n".join(
        [
            "# Add replace_in_file",
            "## Context\n"
            + (
                "Need precise edits without sending whole files to the model. "
                "write_file wastes context on every small change. "
            )
            * 12,
            "## Current\n`src/b3code/tools/workspace.py` write_file overwrites the file. "
            "CodeMode wraps the toolset. Planner uses include_write=False.",
            "## Approach\nLiteral replace with unique old. Reject regex and apply_patch. "
            "Retry when old is missing or ambiguous unless replace_all.",
            "## Steps\n1. Add replace_in_file, delete_file, move_file in workspace_toolset. "
            "2. Prefer replace in coder instructions. 3. Keep planner read-only. "
            "Done when test_tools covers unique/ambiguous/delete/move.",
            "## Files\n- src/b3code/tools/workspace.py — add replace/delete/move and read ranges\n"
            "- src/b3code/services/chat.py — instruct prefer replace\n"
            "- tests/test_tools.py — cases for each tool",
            "## Reuse\nsafe_workspace_path, diff_texts, can_write, on_change.",
            "## Risks\nAmbiguous old strings; refuse unless replace_all. "
            "Do not delete directories. Plan mode must not see mutate tools.",
            "## Verify\nuv run pytest tests/test_tools.py tests/test_plan.py",
        ]
    )
    assert "wrote" in write(full)
    assert "## Steps" in mode.read()
    assert exit_fn() == "plan ready for approval"
