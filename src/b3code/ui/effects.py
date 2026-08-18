"""Dispatcher puro de CommandResult → callbacks da tela."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from b3code.commands.effects import (
    CommandEffect,
    DoctorMcp,
    NewSession,
    PlanOff,
    Quit,
    Refresh,
    ReloadSkills,
    RunPrompt,
    ShowPlanDoc,
)
from b3code.commands.types import CommandResult


@dataclass(frozen=True)
class CommandHooks:
    on_quit: Callable[[], None]
    on_reset: Callable[[], None]
    on_rebuild: Callable[[], None]
    on_send: Callable[[str], None]
    on_plan_off: Callable[[], None]
    on_show_plan: Callable[[str], None]
    on_note: Callable[[str], None]
    on_doctor: Callable[[tuple[str, ...]], None]
    on_skills_reload: Callable[[], None]


def dispatch_command(result: CommandResult, hooks: CommandHooks) -> None:
    effect = result.effect
    if effect is not None and _APPLY[type(effect)](hooks, effect):
        return
    if result.message:
        hooks.on_note(result.message)


def _quit(hooks: CommandHooks, _effect: Quit) -> bool:
    hooks.on_quit()
    return True


def _new(hooks: CommandHooks, _effect: NewSession) -> bool:
    hooks.on_reset()
    return False


def _refresh(hooks: CommandHooks, _effect: Refresh) -> bool:
    hooks.on_rebuild()
    return False


def _prompt(hooks: CommandHooks, effect: RunPrompt) -> bool:
    hooks.on_send(effect.text)
    return True


def _plan_off(hooks: CommandHooks, _effect: PlanOff) -> bool:
    hooks.on_plan_off()
    return False


def _show_plan(hooks: CommandHooks, effect: ShowPlanDoc) -> bool:
    hooks.on_show_plan(effect.body)
    return True


def _doctor(hooks: CommandHooks, effect: DoctorMcp) -> bool:
    hooks.on_doctor(effect.names)
    return True


def _reload_skills(hooks: CommandHooks, _effect: ReloadSkills) -> bool:
    hooks.on_skills_reload()
    return False


# Cada handler recebe o efeito do próprio tipo da chave (by construction).
_APPLY: dict[type[CommandEffect], Callable[..., bool]] = {
    Quit: _quit,
    NewSession: _new,
    Refresh: _refresh,
    RunPrompt: _prompt,
    PlanOff: _plan_off,
    ShowPlanDoc: _show_plan,
    DoctorMcp: _doctor,
    ReloadSkills: _reload_skills,
}
