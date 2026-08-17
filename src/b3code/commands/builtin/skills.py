"""Comandos `/nome` (uma skill) e `/skills` (gestão de skills)."""

from __future__ import annotations

from b3code.commands.effects import ReloadSkills, RunPrompt
from b3code.commands.registry import Command
from b3code.commands.types import CommandResult
from b3code.services.chat import ChatService
from b3code.services.skills import Skill, SkillIndex


def build_skill_command(
    skill: Skill, index: SkillIndex, name: str | None = None
) -> Command:
    """`/nome [args...]` → RunPrompt com o corpo da skill + a tarefa."""

    command_name = name or skill.name

    def handler(*args: str) -> CommandResult:
        index.scan()
        fresh = index.get(skill.name)
        if fresh is None or fresh.disabled:
            return CommandResult(f"skill {skill.name} not found")
        task = " ".join(args).strip() or "Follow the skill instructions now."
        text = f"{index.load(skill.name)}\n\nTask: {task}"
        return CommandResult(f"skill {skill.name} loaded", effect=RunPrompt(text))

    help_text = f"skill: {skill.description}"
    if skill.argument_hint:
        help_text += f" — args: {skill.argument_hint}"
    return Command(command_name, help_text, handler)


def build_skills_command(
    index: SkillIndex,
    chat: ChatService,
    native: frozenset[str] = frozenset(),
) -> Command:
    """`/skills`, `/skills reload`, `/skills paths`."""

    def handler(*args: str) -> CommandResult:
        if not index.settings.enabled:
            return CommandResult("skills: disabled")
        if args:
            return CommandResult(
                "usage: /skills | /skills reload | /skills paths"
            )
        return CommandResult(_skill_listing(index, native))

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


def _skill_listing(index: SkillIndex, native: frozenset[str]) -> str:
    lines: list[str] = []
    for skill in index.skills(include_disabled=True):
        line = f"{skill.name}  {skill.scope}"
        if skill.disabled:
            line += "  [disabled]"
        if skill.name in native:
            line += (
                f"  [collides with /{skill.name} → "
                f"/{skill.scope}:{skill.name}]"
            )
        lines.append(line)
    return "\n".join(lines) or "(no skills)"
