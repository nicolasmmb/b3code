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
from b3code.ui.widgets.messages import render_diff, render_lines
from b3code.utils.diffview import EXPAND_CAP, diff_texts, visible

# tetos folgados: pegam regressão real, não ruído de CI
BUDGET_MS = {
    "apply_suggestion": 0.05,
    "decide_submit": 0.05,
    "complete_root": 0.15,
    "complete_model": 2.0,
    "complete_resume": 0.25,
    "index_search": 5.0,
    "diff_2k": 40.0,
    "render_collapsed": 4.0,
    "render_expanded": 20.0,
    "toggle_expand": 20.0,
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
        **_diff_metrics(),
    }

    print("\nhot path                  ms/op    budget")
    failed: list[str] = []
    for name, got in measured.items():
        budget = BUDGET_MS[name]
        print(f"  {name:<22} {got:7.3f}    {budget:6.2f}")
        if got > budget:
            failed.append(f"{name} {got:.3f}ms > {budget:.2f}ms")
    assert not failed, "slowdown: " + "; ".join(failed)


def _diff_metrics() -> dict[str, float]:
    old = [f"line {i} keep" for i in range(2000)]
    new = list(old)
    for i in range(100, 180):
        new[i] = f"line {i} changed"
    old_s = "\n".join(old)
    new_s = "\n".join(new)
    change = diff_texts("big.py", old_s, new_s)

    def toggle_paint() -> None:
        collapsed = visible(change, expanded=False)
        render_lines(collapsed, 80)
        expanded = visible(change, expanded=True)
        render_lines(expanded, 80)

    huge = diff_texts(
        "huge.py",
        "",
        "\n".join(f"row {i}" for i in range(EXPAND_CAP + 10)),
    )
    return {
        "diff_2k": _ms_per_op(lambda: diff_texts("big.py", old_s, new_s), 8, warmup=2),
        "render_collapsed": _ms_per_op(
            lambda: render_diff(change, 80, expanded=False), 40
        ),
        "render_expanded": _ms_per_op(
            lambda: render_lines(visible(huge, expanded=True), 80), 20
        ),
        "toggle_expand": _ms_per_op(toggle_paint, 20),
    }
