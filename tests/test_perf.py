"""Teto de latência nos caminhos que o TUI chama a cada tecla / Enter.

Não precisa de baseline JSON: falha se um hot path ficar lento demais.
Rode com `uv run pytest tests/test_perf.py -s` para ver a tabela.
"""

from __future__ import annotations

import time
from pathlib import Path

from pydantic_ai.models.test import TestModel

from b3code.commands.apply import apply_suggestion, decide_submit
from b3code.commands.registry import CommandRegistry
from b3code.commands.types import Suggestion
from b3code.config.schema import AppConfig
from b3code.config.store import ConfigStore
from b3code.services.catalog import list_models
from b3code.services.chat import ChatService
from b3code.services.files import FileIndex
from b3code.services.session import SessionStore

# tetos folgados: pegam regressão real, não ruído de CI
BUDGET_MS = {
    "apply_suggestion": 0.05,
    "decide_submit": 0.05,
    "complete_root": 0.15,
    "complete_model": 2.0,
    "complete_resume": 0.25,
    "index_search": 5.0,
}


def _ms_per_op(fn, n: int, *, warmup: int = 20) -> float:
    for _ in range(warmup):
        fn()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) * 1000 / n


def _registry(tmp_path: Path, *, sessions: int = 1) -> CommandRegistry:
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(use_provider_gateway=False, api_models=["gpt-4o"])
    store.save(cfg)
    sess = SessionStore(tmp_path / "sessions.json")
    for _ in range(sessions - 1):
        sess.new()
    chat = ChatService(cfg, sess, tmp_path, model=TestModel())
    return CommandRegistry.build(store, cfg, sess, chat)


def test_hot_paths_stay_under_budget(tmp_path: Path):
    reg = _registry(tmp_path, sessions=80)
    list_models(reg.config)  # aquece known_model_names

    item = Suggestion(
        value="anthropic:claude-fable-5",
        label="anthropic:claude-fable-5",
        hint="catalog",
        kind="arg",
        consume=True,
    )
    line = "/model claude-fable"

    for i in range(30):
        (tmp_path / f"mod_{i:03d}.py").write_text("x", encoding="utf-8")
    idx = FileIndex(tmp_path)
    idx.scan()

    measured = {
        "apply_suggestion": _ms_per_op(
            lambda: apply_suggestion(line, len(line), item), 4_000
        ),
        "decide_submit": _ms_per_op(
            lambda: decide_submit(line, len(line), item), 4_000
        ),
        "complete_root": _ms_per_op(lambda: reg.complete("/"), 2_000),
        "complete_model": _ms_per_op(lambda: reg.complete("/model claude"), 200),
        "complete_resume": _ms_per_op(lambda: reg.complete("/resume"), 1_000),
        "index_search": _ms_per_op(lambda: idx.search("mod"), 200),
    }

    print("\nhot path                  ms/op    budget")
    failed: list[str] = []
    for name, got in measured.items():
        budget = BUDGET_MS[name]
        print(f"  {name:<22} {got:7.3f}    {budget:6.2f}")
        if got > budget:
            failed.append(f"{name} {got:.3f}ms > {budget:.2f}ms")
    # pytest mostra o print no -s; no fail a mensagem leva os números
    assert not failed, "slowdown: " + "; ".join(failed)
