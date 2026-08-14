from pydantic_ai import FunctionToolCallEvent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from b3code.services.events import map_agent_event
from b3code.services.session import turns_from_messages
from b3code.utils.toolview import PREVIEW_LINES, parse_args, preview_output, tool_title


def test_parse_args_dict_and_json():
    assert parse_args({"command": "ls"}) == {"command": "ls"}
    assert parse_args('{"path": "a.py"}') == {"path": "a.py"}
    assert parse_args("not-json") == {}
    assert parse_args(None) == {}


def test_tool_titles():
    assert tool_title("run_command", {"command": "git status"}) == "$ git status"
    assert tool_title("start_command", '{"command": "pytest"}') == "$ pytest"
    assert tool_title("read_file", {"path": "README.md"}) == "Read README.md"
    assert tool_title(
        "read_file", {"path": "a.py", "start_line": 2, "end_line": 9}
    ) == ("Read a.py (2-9)")
    assert tool_title("list_dir", {}) == "Listed ."
    assert tool_title("list_dir", {"path": "src"}) == "Listed src"
    assert tool_title("grep", {"pattern": "compose"}) == 'Searched "compose"'
    assert tool_title("grep", {"pattern": "x", "path": "src"}) == 'Searched "x" in src'
    assert tool_title("write_file", {"path": "a.py"}) == "Editing a.py"
    assert tool_title("run_code", {"code": "print(1)"}) == "Ran run_code"
    assert tool_title("run_command", {}) == "Ran run_command"


def test_preview_output_caps_lines():
    text = "\n".join(f"l{i}" for i in range(PREVIEW_LINES + 5))
    out = preview_output(text)
    assert out.endswith("…")
    assert out.count("\n") == PREVIEW_LINES


def test_map_start_uses_human_title():
    part = ToolCallPart(
        tool_name="run_command",
        args={"command": "git status"},
        tool_call_id="c1",
    )
    events = map_agent_event(FunctionToolCallEvent(part=part))
    assert events[0].kind == "tool_start"
    assert events[0].detail == "$ git status"
    assert events[0].call_id == "c1"
    assert events[0].output == ""


def test_turns_pair_call_with_return():
    msgs = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="read_file",
                    args={"path": "a.py"},
                    tool_call_id="r1",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read_file",
                    content="print(1)\n",
                    tool_call_id="r1",
                )
            ]
        ),
    ]
    turns = turns_from_messages(msgs)
    tools = [t for t in turns if t.role == "tool"]
    assert len(tools) == 1
    assert tools[0].detail == "Read a.py"
    assert "print(1)" in tools[0].output
    assert tools[0].call_id == "r1"


def test_turns_keep_user_prompts():
    msgs = [ModelRequest(parts=[UserPromptPart(content="oi")])]
    turns = turns_from_messages(msgs)
    assert turns[0].role == "user"
    assert turns[0].text == "oi"
