"""spawn / snapshot / kill — tools de topo, fora do run_code."""

from __future__ import annotations

from pydantic_ai.toolsets import FunctionToolset

from b3code.services.tasks import TaskHub


def task_toolset(hub: TaskHub) -> FunctionToolset:
    async def spawn_subagent(
        prompt: str,
        description: str,
        subagent_type: str = "general-purpose",
        background: bool = True,
    ) -> str:
        """Spawn a child agent with its own context. Poll with get_command_or_subagent_output."""
        return await hub.spawn(prompt, description, subagent_type, background)

    async def get_command_or_subagent_output(
        task_ids: list[str], timeout_ms: int | None = None
    ) -> str:
        """Read or wait for background subagent output. Omit timeout_ms for a snapshot."""
        return await hub.snapshot(task_ids, timeout_ms)

    async def kill_command_or_subagent(task_id: str) -> str:
        """Cancel a running subagent."""
        return await hub.kill(task_id)

    return FunctionToolset(
        tools=[
            spawn_subagent,
            get_command_or_subagent_output,
            kill_command_or_subagent,
        ]
    )
