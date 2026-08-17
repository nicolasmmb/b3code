"""Comando `/skills` — única porta de skills: run, list, reload, paths."""

from __future__ import annotations

from b3code.commands.effects import ReloadSkills, RunPrompt
from b3code.commands.registry import Command
from b3code.commands.types import CommandResult, Suggestion
from b3code.services.skills import SkillIndex

_USAGE = (
    "usage: /skills | /skills run <name> [args...] | "
    "/skills reload | /skills paths"
)


def build_skills_command(index: SkillIndex) -> Command:
    """`/skills run <nome> [args...]` (com autocomplete) + gestão."""
    return Command(
        "skills",
        "list, run, reload, or show skill roots",
        lambda *args: _listing(index, args),
        children={
            "run": Command(
                "run",
                "run a skill by name with optional args",
                lambda *args: _run(index, args),
                lambda prefix="", *_: _complete(index, prefix),
            ),
            "reload": Command(
                "reload", "rescan skills from disk", lambda *_: _reload(index)
            ),
            "paths": Command(
                "paths", "show skill roots", lambda *_: _paths(index)
            ),
        },
    )


def _run(index: SkillIndex, args: tuple[str, ...]) -> CommandResult:
    if not args:
        return CommandResult("usage: /skills run <name> [args...]")
    name, *rest = args
    index.scan()
    skill = index.get(name)
    if skill is None or skill.disabled or not skill.user_invocable:
        return CommandResult(f"unknown or disabled skill {name!r}")
    task = " ".join(rest).strip() or "Follow the skill instructions now."
    text = f"{index.load(skill.name)}\n\nTask: {task}"
    return CommandResult(f"skill {skill.name} loaded", effect=RunPrompt(text))


def _complete(index: SkillIndex, prefix: str) -> list[Suggestion]:
    index.scan()
    needle = prefix.lower()
    out: list[Suggestion] = []
    for skill in index.skills():
        if not skill.user_invocable:
            continue
        if needle and needle not in skill.name.lower():
            continue
        out.append(
            Suggestion(
                value=skill.name,
                label=skill.name,
                hint=skill.description or "skill",
                kind="arg",
                consume=False,
            )
        )
    return out


def _listing(index: SkillIndex, args: tuple[str, ...]) -> CommandResult:
    if not index.settings.enabled:
        return CommandResult("skills: disabled")
    if args:
        return CommandResult(_USAGE)
    return CommandResult(_skill_listing(index))


def _reload(index: SkillIndex) -> CommandResult:
    index.scan()
    return CommandResult("skills reloaded", effect=ReloadSkills())


def _paths(index: SkillIndex) -> CommandResult:
    rows = [f"{root}  {scope}" for root, scope in index.roots()]
    return CommandResult("\n".join(rows) or "(no roots)")


def _skill_listing(index: SkillIndex) -> str:
    lines: list[str] = []
    for skill in index.skills(include_disabled=True):
        line = f"{skill.name}  {skill.scope}"
        if skill.disabled:
            line += "  [disabled]"
        lines.append(line)
    return "\n".join(lines) or "(no skills)"
