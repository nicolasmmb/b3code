"""Efeitos que um comando pede à UI. Sem Textual — só dados."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Quit:
    pass


@dataclass(frozen=True)
class Refresh:
    pass


@dataclass(frozen=True)
class NewSession:
    pass


@dataclass(frozen=True)
class RunPrompt:
    text: str


@dataclass(frozen=True)
class PlanOff:
    pass


@dataclass(frozen=True)
class ShowPlanDoc:
    body: str


@dataclass(frozen=True)
class DoctorMcp:
    names: tuple[str, ...]


@dataclass(frozen=True)
class ReloadSkills:
    pass


CommandEffect = (
    Quit
    | Refresh
    | NewSession
    | RunPrompt
    | PlanOff
    | ShowPlanDoc
    | DoctorMcp
    | ReloadSkills
)
