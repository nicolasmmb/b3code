"""Dispatcher puro de CommandResult → callbacks da tela."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from b3code.commands.effects import (
    NewSession,
    PlanOff,
    Quit,
    Refresh,
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


def dispatch_command(result: CommandResult, hooks: CommandHooks) -> None:
    effect = result.effect
    if isinstance(effect, Quit):
        hooks.on_quit()
        return
    if isinstance(effect, NewSession):
        hooks.on_reset()
    if isinstance(effect, Refresh):
        hooks.on_rebuild()
    if isinstance(effect, RunPrompt):
        hooks.on_send(effect.text)
        return
    if isinstance(effect, PlanOff):
        hooks.on_plan_off()
    if isinstance(effect, ShowPlanDoc):
        hooks.on_show_plan(effect.body)
        return
    if result.message:
        hooks.on_note(result.message)
