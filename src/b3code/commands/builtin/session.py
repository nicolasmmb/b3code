from b3code.commands.effects import NewSession, Quit, Refresh
from b3code.commands.registry import Command
from b3code.commands.types import CommandResult, Suggestion
from b3code.services.session import Session, SessionStore


def _session_count(session: Session) -> int:
    return session.message_count or len(session.messages)


def build_new(sessions: SessionStore) -> Command:
    def handler(*_: str) -> CommandResult:
        sessions.new()
        return CommandResult("new session", effect=NewSession())

    return Command("new", "start a new session", handler)


def build_quit() -> Command:
    def handler(*_: str) -> CommandResult:
        return CommandResult("bye", effect=Quit())

    return Command("quit", "quit the app", handler)


def build_exit() -> Command:
    return Command("exit", "quit the app", build_quit().handler)


def build_resume(sessions: SessionStore) -> Command:
    def handler(*args: str) -> CommandResult:
        if not args:
            rows = []
            for session in sessions.list_sessions():
                mark = "*" if session.id == sessions.current_id else " "
                rows.append(
                    f"{mark} {session.id}  {session.created_at}  {_session_count(session)} msgs"
                )
            return CommandResult("sessions:\n" + "\n".join(rows) or "(none)")
        sessions.activate(args[0])
        return CommandResult(f"resumed {args[0]}", effect=Refresh())

    def complete(prefix: str = "", *_: str) -> list[Suggestion]:
        needle = prefix.lower()
        out: list[Suggestion] = []
        for session in sessions.list_sessions():
            if needle and needle not in session.id.lower():
                continue
            mark = "* " if session.id == sessions.current_id else ""
            date = session.created_at[:10] if session.created_at else ""
            out.append(
                Suggestion(
                    value=session.id,
                    label=session.id,
                    hint=f"{mark}{date}  {_session_count(session)} msgs".strip(),
                    kind="arg",
                    consume=True,
                )
            )
        return out

    return Command("resume", "list or resume a session", handler, complete)
