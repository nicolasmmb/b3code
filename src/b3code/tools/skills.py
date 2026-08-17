"""list_skills / load_skill — tools de topo para o modelo ativar skills em runtime.

O corpo da skill entra no *user turn* como bloco `<skill>` (igual a `@arquivo`),
preservando o prefixo estático do cache Azure. O system prompt não muda.
"""

from __future__ import annotations

from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.toolsets import FunctionToolset

from b3code.services.skills import SkillIndex


def skills_toolset(index: SkillIndex) -> FunctionToolset:
    def list_skills() -> str:
        """List available skills as `name — description (when: ...)` lines. Call first when a task may match a skill."""
        return index.catalog()

    def load_skill(name: str) -> str:
        """Load a skill body in a <skill> block. Unknown, disabled, or model-invocation-disabled skills raise ModelRetry."""
        skill = index.get(name)
        if (
            skill is None
            or skill.disabled
            or skill.disable_model_invocation
        ):
            raise ModelRetry(
                f"unknown or disabled skill {name!r} — call list_skills first"
            )
        return index.load(name)

    return FunctionToolset(tools=[list_skills, load_skill])
