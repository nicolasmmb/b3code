from b3code.commands.effects import (
    DoctorMcp,
    NewSession,
    PlanOff,
    Quit,
    Refresh,
    RunPrompt,
    ShowPlanDoc,
)
from b3code.commands.types import CommandResult
from b3code.ui.effects import CommandHooks, dispatch_command


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def hooks(self) -> CommandHooks:
        return CommandHooks(
            on_quit=lambda: self.calls.append(("quit", None)),
            on_reset=lambda: self.calls.append(("reset", None)),
            on_rebuild=lambda: self.calls.append(("rebuild", None)),
            on_send=lambda text: self.calls.append(("send", text)),
            on_plan_off=lambda: self.calls.append(("plan_off", None)),
            on_show_plan=lambda body: self.calls.append(("show_plan", body)),
            on_note=lambda text: self.calls.append(("note", text)),
            on_doctor=lambda names: self.calls.append(("doctor", ",".join(names))),
            on_skills_reload=lambda: self.calls.append(("skills_reload", None)),
        )


def test_dispatch_quit():
    rec = _Recorder()
    dispatch_command(CommandResult("bye", effect=Quit()), rec.hooks())
    assert rec.calls == [("quit", None)]


def test_dispatch_new_session_then_note():
    rec = _Recorder()
    dispatch_command(CommandResult("new session", effect=NewSession()), rec.hooks())
    assert rec.calls == [("reset", None), ("note", "new session")]


def test_dispatch_refresh_then_note():
    rec = _Recorder()
    dispatch_command(CommandResult("model → x", effect=Refresh()), rec.hooks())
    assert rec.calls == [("rebuild", None), ("note", "model → x")]


def test_dispatch_run_prompt_skips_note():
    rec = _Recorder()
    dispatch_command(
        CommandResult("plan mode on", effect=RunPrompt("do it")), rec.hooks()
    )
    assert rec.calls == [("send", "do it")]


def test_dispatch_plan_off_then_note():
    rec = _Recorder()
    dispatch_command(CommandResult("plan mode off", effect=PlanOff()), rec.hooks())
    assert rec.calls == [("plan_off", None), ("note", "plan mode off")]


def test_dispatch_show_plan_skips_note():
    rec = _Recorder()
    dispatch_command(
        CommandResult("# title", effect=ShowPlanDoc("# title")), rec.hooks()
    )
    assert rec.calls == [("show_plan", "# title")]


def test_dispatch_doctor_skips_note():
    rec = _Recorder()
    dispatch_command(CommandResult("", effect=DoctorMcp(("github",))), rec.hooks())
    assert rec.calls == [("doctor", "github")]


def test_dispatch_message_only():
    rec = _Recorder()
    dispatch_command(CommandResult("help text"), rec.hooks())
    assert rec.calls == [("note", "help text")]
