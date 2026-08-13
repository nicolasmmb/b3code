"""Teto de latência com amostragem estável (mediana / p95, GC pausado).

Um único burst + média pega ruído de GC e de relógio. Aqui: aquece,
calibra o lote pra cada round durar ~30ms, tira vários rounds e
julga pela **mediana**. `p95` só aparece na tabela.

    uv run pytest tests/test_perf.py -s
"""

from __future__ import annotations

import gc
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
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

# teto na mediana. folgado o bastante pra CI, apertado pra regressão real.
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

ROUNDS = 9
WARMUP = 3
TARGET_ROUND_S = 0.03


@dataclass(frozen=True)
class Sample:
    minimum: float
    median: float
    p95: float
    batch: int
    rounds: int


def _sample(fn: Callable[[], object]) -> Sample:
    """ms/op: warmup + N rounds com lote calibrado; GC desligado na medição."""
    fn()
    t0 = time.perf_counter()
    fn()
    one = max(time.perf_counter() - t0, 1e-9)
    batch = max(1, min(20_000, int(TARGET_ROUND_S / one)))

    for _ in range(WARMUP):
        for _ in range(batch):
            fn()

    gc.collect()
    was_enabled = gc.isenabled()
    gc.disable()
    raw: list[float] = []
    try:
        for _ in range(ROUNDS):
            start = time.perf_counter()
            for _ in range(batch):
                fn()
            raw.append((time.perf_counter() - start) * 1000 / batch)
    finally:
        if was_enabled:
            gc.enable()

    raw.sort()
    if len(raw) >= 2:
        p95 = statistics.quantiles(raw, n=20)[18]
    else:
        p95 = raw[-1]
    return Sample(raw[0], statistics.median(raw), p95, batch, ROUNDS)


def _registry(tmp_path: Path, *, sessions: int = 1) -> CommandRegistry:
    store = ConfigStore(tmp_path / "config.json")
    cfg = AppConfig(use_provider_gateway=False, api_models=["gpt-4o"])
    store.save(cfg)
    sess = SessionStore(tmp_path / "sessions.json")
    for _ in range(sessions - 1):
        sess.new()
    chat = ChatService(cfg, sess, tmp_path, model=TestModel())
    return CommandRegistry.build(store, cfg, sess, chat)


def _diff_work() -> dict[str, Callable[[], object]]:
    old = [f"line {i} keep" for i in range(2000)]
    new = list(old)
    for i in range(100, 180):
        new[i] = f"line {i} changed"
    old_s = "\n".join(old)
    new_s = "\n".join(new)
    change = diff_texts("big.py", old_s, new_s)
    huge = diff_texts(
        "huge.py",
        "",
        "\n".join(f"row {i}" for i in range(EXPAND_CAP + 10)),
    )

    def toggle() -> None:
        render_lines(visible(change, expanded=False), 80)
        render_lines(visible(change, expanded=True), 80)

    return {
        "diff_2k": lambda: diff_texts("big.py", old_s, new_s),
        "render_collapsed": lambda: render_diff(change, 80, expanded=False),
        "render_expanded": lambda: render_lines(visible(huge, expanded=True), 80),
        "toggle_expand": toggle,
    }


def test_hot_paths_stay_under_budget(tmp_path: Path):
    reg = _registry(tmp_path, sessions=80)
    list_models(reg.config)

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

    jobs: dict[str, Callable[[], object]] = {
        "apply_suggestion": lambda: apply_suggestion(line, len(line), item),
        "decide_submit": lambda: decide_submit(line, len(line), item),
        "complete_root": lambda: reg.complete("/"),
        "complete_model": lambda: reg.complete("/model claude"),
        "complete_resume": lambda: reg.complete("/resume"),
        "index_search": lambda: idx.search("mod"),
        **_diff_work(),
    }

    print("\nhot path                  min     median      p95   budget  batch")
    failed: list[str] = []
    noisy: list[str] = []
    for name, fn in jobs.items():
        sample = _sample(fn)
        budget = BUDGET_MS[name]
        print(
            f"  {name:<20} {sample.minimum:7.3f}  {sample.median:7.3f}  "
            f"{sample.p95:7.3f}  {budget:6.2f}  x{sample.batch}"
        )
        if sample.median > budget:
            failed.append(f"{name} median {sample.median:.3f}ms > {budget:.2f}ms")
        if sample.median > 0 and sample.p95 / sample.median > 4:
            noisy.append(name)
    if noisy:
        print("  (p95 instável em: " + ", ".join(noisy) + " — máquina ocupada)")
    assert not failed, "slowdown: " + "; ".join(failed)
