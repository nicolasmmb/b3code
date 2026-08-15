from pydantic_ai import FunctionToolCallEvent, PartDeltaEvent, PartStartEvent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ThinkingPartDelta,
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
    assert tool_title("list_dir", {}) == "Ran list_dir"
    assert tool_title("list_dir", {"path": "src"}) == "List src"
    assert tool_title("grep", {"pattern": "compose"}) == 'Searched "compose"'
    assert tool_title("grep", {"pattern": "x", "path": "src"}) == 'Searched "x" in src'
    assert tool_title("write_file", {"path": "a.py"}) == "Write a.py"
    assert tool_title("replace_in_file", {"path": "a.py", "old": "x", "new": "y"}) == (
        "Replace a.py"
    )
    assert tool_title("delete_file", {"path": "tmp.txt"}) == "Delete tmp.txt"
    assert tool_title("move_file", {"src": "a.py", "dest": "b.py"}) == (
        "Move a.py → b.py"
    )
    assert tool_title("run_code", {"code": "print(1)"}) == "Ran run_code"
    assert tool_title("run_command", {}) == "Ran run_command"


def test_unknown_tools_use_args_not_whitelist():
    assert tool_title("fetch_url", {"url": "https://x.ai"}) == "Fetch https://x.ai"
    assert tool_title("summarize_pdf", {"path": "docs/spec.pdf"}) == (
        "Summarize docs/spec.pdf"
    )
    assert tool_title("web_search", {"query": "textual fold"}) == (
        'Searched "textual fold"'
    )
    assert tool_title("open_ticket", {"name": "BUG-12"}) == "Open BUG-12"
    assert tool_title("bash", {"command": "make test"}) == "$ make test"
    assert tool_title(
        "search_replace", {"path": "ui.py", "start_line": 10, "end_line": 40}
    ) == ("Search ui.py (10-40)")
    assert tool_title("think", {"text": "um parágrafo longo demais"}) == "Ran think"
    assert tool_title("clone_repo", {"repo": "xai-org/grok-build"}) == (
        "Clone xai-org/grok-build"
    )
    assert tool_title("search_tool", {"query": "linear issue"}) == (
        'Searched "linear issue"'
    )
    assert tool_title("use_tool", {"tool_name": "github__create_issue"}) == (
        "Use github__create_issue"
    )
    assert (
        tool_title(
            "spawn_subagent",
            {"description": "look around", "subagent_type": "explore"},
        )
        == "explore · look around"
    )
    assert (
        tool_title("get_command_or_subagent_output", {"task_ids": ["sa-deadbeef"]})
        == "Check subagent"
    )
    assert tool_title("kill_command_or_subagent", {"task_id": "sa-deadbeef"}) == (
        "Stop subagent"
    )


def test_preview_output_caps_lines():
    text = "\n".join(f"l{i}" for i in range(PREVIEW_LINES + 5))
    out = preview_output(text)
    assert out.endswith("…")
    assert out.count("\n") == PREVIEW_LINES


def test_preview_output_caps_chars():
    from b3code.utils.toolview import PREVIEW_CHARS

    out = preview_output("x" * (PREVIEW_CHARS + 80))
    assert out.endswith("…")
    assert len(out) < PREVIEW_CHARS + 10


def test_map_thinking_parts():
    start = map_agent_event(PartStartEvent(index=0, part=ThinkingPart(content="hmm")))
    assert start[0].kind == "thinking_delta"
    assert start[0].text == "hmm"
    delta = map_agent_event(
        PartDeltaEvent(index=0, delta=ThinkingPartDelta(content_delta=" more"))
    )
    assert delta[0].kind == "thinking_delta"
    assert delta[0].text == " more"
    text = map_agent_event(PartStartEvent(index=0, part=TextPart(content="hi")))
    assert text[0].kind == "text_delta"


def test_turns_include_thinking():
    turns = turns_from_messages(
        [
            ModelResponse(
                parts=[
                    ThinkingPart(content="let me look"),
                    TextPart(content="done"),
                ]
            )
        ]
    )
    assert turns[0].role == "thinking"
    assert turns[0].text == "let me look"
    assert turns[1].role == "assistant"
    assert turns[1].text == "done"


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


def test_turns_collapse_spawn_and_get_into_one_card():
    msgs = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="spawn_subagent",
                    args={
                        "prompt": "hi",
                        "description": "look around",
                        "subagent_type": "explore",
                    },
                    tool_call_id="s1",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="spawn_subagent",
                    content="started sa-deadbeef (explore): look around",
                    tool_call_id="s1",
                )
            ]
        ),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="get_command_or_subagent_output",
                    args={"task_ids": ["sa-deadbeef"]},
                    tool_call_id="g1",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="get_command_or_subagent_output",
                    content=(
                        "sa-deadbeef done (explore) 4s\n"
                        "  · Read README.md\n"
                        "  —\n"
                        "  found 3 sites\n"
                    ),
                    tool_call_id="g1",
                )
            ]
        ),
    ]
    turns = turns_from_messages(msgs)
    tools = [t for t in turns if t.role == "tool"]
    assert len(tools) == 1
    assert tools[0].tool == "subagent"
    assert tools[0].detail == "explore · look around"
    assert tools[0].call_id == "sa-deadbeef"
    assert "Read README.md" in tools[0].output
    assert "found 3 sites" in tools[0].output
    assert "started sa-" not in tools[0].output
