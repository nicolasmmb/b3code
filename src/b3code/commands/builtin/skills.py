"""Comandos `/skill run` (única porta de invocação) e `/skills` (gestão)."""

from __future__ import annotations

from b3code.commands.effects import ReloadSkills, RunPrompt
from b3code.commands.registry import Command
from b3code.commands.types import CommandResult, Suggestion
from b3code.services.skills import SkillIndex


def build_skill_run(index: SkillIndex) -> Command:
    """`/skill run <nome> [args...]` — roda uma skill, sempre com autocomplete."""

    def run(*args: str) -> CommandResult:
        if not args:
            return CommandResult("usage: /skill run <name> [args...]")
        name, *rest = args
        index.scan()
        skill = index.get(name)
        if skill is None or skill.disabled or not skill.user_invocable:
            return CommandResult(f"unknown or disabled skill {name!r}")
        task = " ".join(rest).strip() or "Follow the skill instructions now."
        text = f"{index.load(skill.name)}\n\nTask: {task}"
        return CommandResult(f"skill {skill.name} loaded", effect=RunPrompt(text))

    def complete(prefix: str = "", *_: str) -> list[Suggestion]:
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

    return Command(
        "skill",
        "run a skill by name",
        None,
        children={
            "run": Command(
                "run",
                "run a skill by name with optional args",
                run,
                complete,
            ),
        },
    )


def build_skills_command(index: SkillIndex) -> Command:
    """`/skills`, `/skills reload`, `/skills paths`."""

    def handler(*args: str) -> CommandResult:
        if not index.settings.enabled:
            return CommandResult("skills: disabled")
        if args:
            return CommandResult(
                "usage: /skills | /skills reload | /skills paths"
            )
        return CommandResult(_skill_listing(index))

    def reload(*_: str) -> CommandResult:
        index.scan()
        return CommandResult("skills reloaded", effect=ReloadSkills())

    def paths(*_: str) -> CommandResult:
        rows = [f"{root}  {scope}" for root, scope in index.roots()]
        return CommandResult("\n".join(rows) or "(no roots)")

    return Command(
        "skills",
        "list, reload, or show skill roots",
        handler,
        children={
            "reload": Command("reload", "rescan skills from disk", reload),
            "paths": Command("paths", "show skill roots", paths),
        },
    )


def _skill_listing(index: SkillIndex) -> str:
    lines: list[str] = []
    for skill in index.skills(include_disabled=True):
        line = f"{skill.name}  {skill.scope}"
        if skill.disabled:
            line += "  [disabled]"
        lines.append(line)
    return "\n".join(lines) or "(no skills)"
