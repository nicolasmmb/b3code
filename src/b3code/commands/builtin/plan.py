from b3code.commands.effects import PlanOff, RunPrompt, ShowPlanDoc
from b3code.commands.registry import Command
from b3code.commands.types import CommandResult, Suggestion
from b3code.services.chat import ChatService


def build_plan(chat: ChatService) -> Command:
    def handler(*args: str) -> CommandResult:
        if chat.busy:
            return CommandResult("busy — press esc to cancel first")
        token = args[0].lower() if args else ""
        if token in {"off", "false"}:
            chat.exit_plan()
            return CommandResult("plan mode off", effect=PlanOff())
        chat.enter_plan()
        rest = " ".join(args[1:] if token == "on" else args).strip()
        return CommandResult(
            "plan mode on",
            effect=RunPrompt(rest) if rest else None,
        )

    def complete(prefix: str = "", *_: str) -> list[Suggestion]:
        return [
            Suggestion(value=value, label=value, hint="plan", kind="arg", consume=True)
            for value in ("on", "off")
            if value.startswith(prefix)
        ]

    return Command("plan", "enter or leave plan mode", handler, complete)


def build_view_plan(chat: ChatService) -> Command:
    def handler(*_: str) -> CommandResult:
        body = chat.plan.read()
        if not body:
            return CommandResult("(no plan.md yet)")
        return CommandResult(body, effect=ShowPlanDoc(body))

    return Command("view-plan", "show the current plan.md", handler)
