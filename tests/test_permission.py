from pathlib import Path

import pytest

from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore
from b3code.services.permission import PermissionDenied, PermissionGate


def make_gate(tmp_path: Path, allowed: list[str] | None = None) -> PermissionGate:
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(shell_allowed_paths=allowed or [])
    store.save(cfg)
    return PermissionGate(store, cfg, tmp_path)


async def test_local_command_does_not_ask(tmp_path: Path):
    gate = make_gate(tmp_path)
    gate.on_ask = lambda req: pytest.fail("should not ask")
    await gate.ensure("pytest -q")
    await gate.ensure("cd /work && git status")


async def test_allowlist_skips_ask(tmp_path: Path):
    allowed = str(Path("/tmp").expanduser().resolve())
    gate = make_gate(tmp_path, allowed=[allowed])
    gate.on_ask = lambda req: pytest.fail("should not ask")
    await gate.ensure("ls /tmp")


async def test_always_persists(tmp_path: Path):
    gate = make_gate(tmp_path)

    def auto(req) -> None:
        gate.answer("always")

    gate.on_ask = auto
    await gate.ensure("ls /tmp")
    saved = Path("/tmp").expanduser().resolve()
    assert str(saved) in gate.store.load().shell_allowed_paths


async def test_once_does_not_persist(tmp_path: Path):
    gate = make_gate(tmp_path)
    gate.on_ask = lambda req: gate.answer("once")
    await gate.ensure("ls /tmp")
    assert gate.store.load().shell_allowed_paths == []


async def test_deny_raises(tmp_path: Path):
    gate = make_gate(tmp_path)
    gate.on_ask = lambda req: gate.answer("deny")
    with pytest.raises(PermissionDenied):
        await gate.ensure("ls /tmp")
