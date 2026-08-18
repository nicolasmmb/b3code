"""Plan mode: só o `plan.md` central do projeto é gravável.

Sem Textual, sem pydantic_ai. O arquivo fica fora do workspace
(`b3code_home()/projects/<key>/plan.md`), então as tools de escrita do
workspace nunca o alcançam — o único canal é `write_plan_file`.
"""

from __future__ import annotations

from pathlib import Path

from b3code.config.dirs import project_dir
from b3code.utils.paths import atomic_write_text


class PlanMode:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self.active = False
        self.plan_path = project_dir(self.cwd) / "plan.md"

    def enter(self) -> None:
        self.active = True

    def exit(self) -> None:
        self.active = False

    def can_write(self, path: Path) -> bool:
        if not self.active:
            return True
        try:
            return path.resolve() == self.plan_path.resolve()
        except OSError:
            return False

    def read(self) -> str:
        if not self.plan_path.exists():
            return ""
        return self.plan_path.read_text(encoding="utf-8")

    def write(self, content: str) -> None:
        atomic_write_text(
            self.plan_path, content if content.endswith("\n") else content + "\n"
        )
