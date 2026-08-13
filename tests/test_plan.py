from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelRetry

from b3code.services.plan import PlanMode
from b3code.services.planner import planner_tool_names
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
        for name, tool in workspace_toolset(tmp_path, can_write=mode.can_write).tools.items()
    }
    with pytest.raises(ModelRetry, match="plan mode"):
        fns["write_file"]("a.py", "nope")
    out = fns["write_file"](".b3code/plan.md", "# plan\n")
    assert "plan.md" in out
    assert mode.read().startswith("# plan")


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
