"""Baseline / after bench: wall clock + event-loop stall.

Does not depend on the real cwd. Builds a synthetic tree, times the hot
paths the TUI hits, and optionally compares against a previous JSON.

    uv run python scripts/bench_loop.py --out .b3code/bench-before.json
    uv run python scripts/bench_loop.py --out .b3code/bench-after.json --compare .b3code/bench-before.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import inspect
import json
import statistics
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

# Make `src/` importable when run as a script.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from pydantic_ai.messages import (  # noqa: E402
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel  # noqa: E402

from b3code.commands.apply import apply_suggestion, decide_submit  # noqa: E402
from b3code.commands.registry import CommandRegistry  # noqa: E402
from b3code.commands.types import Suggestion  # noqa: E402
from b3code.config.schema import (  # noqa: E402
    DEFAULT_EXCLUDE_DIRECTORIES,
    AppConfig,
)
from b3code.config.store import ConfigStore  # noqa: E402
from b3code.services.catalog import list_models  # noqa: E402
from b3code.services.chat import ChatService  # noqa: E402
from b3code.services.files import FileIndex  # noqa: E402
from b3code.services.session import SessionStore  # noqa: E402
from b3code.tools.workspace import workspace_toolset  # noqa: E402
from b3code.utils.prompt import expand_attachments  # noqa: E402

USEFUL = 2_000
JUNK = 3_000
ATTACH_BYTES = 80_000
SESSION_TURNS = 40  # 40 * (user+assistant+tool) = 120 messages
DELTA_BURST = 200
HEARTBEAT = 0.010
STALL_GATE_MS = 30.0


def _write_tree(root: Path) -> list[str]:
    src = root / "src"
    src.mkdir()
    attach_names: list[str] = []
    payload = "x" * ATTACH_BYTES
    for i in range(USEFUL):
        sub = src / f"pkg_{i // 100:02d}"
        sub.mkdir(exist_ok=True)
        name = f"mod_{i:04d}.py"
        body = f"class Foo{i}:\n    pass\n"
        if i < 3:
            body = payload + "\n" + body
            attach_names.append(str(Path("src") / f"pkg_{i // 100:02d}" / name))
        (sub / name).write_text(body, encoding="utf-8")

    for folder in ("node_modules", ".git"):
        junk = root / folder / "pkg"
        junk.mkdir(parents=True)
        blob = "junk\n"
        for i in range(JUNK):
            (junk / f"f{i:04d}.js").write_text(blob, encoding="utf-8")

    (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
    return attach_names


def _synth_messages() -> list[Any]:
    msgs: list[Any] = []
    for i in range(SESSION_TURNS):
        msgs.append(
            ModelRequest(parts=[UserPromptPart(content=f"please look at file {i}")])
        )
        msgs.append(
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_file", args={"path": f"src/mod_{i:04d}.py"}
                    ),
                    TextPart(
                        content=f"here is a summary of file {i} " + ("word " * 40)
                    ),
                ]
            )
        )
    return msgs


def _ready_index(cwd: Path) -> FileIndex:
    """Index usable for search — works before (eager ctor) and after (lazy + scan)."""
    idx = FileIndex(cwd, skip_dirs=DEFAULT_EXCLUDE_DIRECTORIES)
    files = getattr(idx, "_files", None)
    if files:
        return idx
    for name in ("scan", "refresh"):
        fn = getattr(idx, name, None)
        if not callable(fn) or inspect.iscoroutinefunction(fn):
            continue
        fn()
        return idx
    return idx


async def _app_index_build(cwd: Path) -> FileIndex:
    """Path the TUI will take: ctor today (blocks); ensure_scanned after (thread)."""
    idx = FileIndex(cwd, skip_dirs=DEFAULT_EXCLUDE_DIRECTORIES)
    ensure = getattr(idx, "ensure_scanned", None)
    if callable(ensure):
        result = ensure()
        if asyncio.iscoroutine(result):
            await result
        return idx
    return idx


async def _app_search(idx: FileIndex, query: str) -> list[Path]:
    search_async = getattr(idx, "search_async", None)
    if callable(search_async):
        result = search_async(query)
        if asyncio.iscoroutine(result):
            return await result
    # After: UI does to_thread(search). Detect lazy API and offload.
    if hasattr(idx, "ensure_scanned"):
        return await asyncio.to_thread(idx.search, query)
    return idx.search(query)


async def _app_refresh(idx: FileIndex) -> None:
    """TUI path: async refresh() off-loop. Old API blocks on scan/refresh."""
    refresh = getattr(idx, "refresh", None)
    if callable(refresh) and inspect.iscoroutinefunction(refresh):
        await refresh()
        return
    if callable(refresh) and not inspect.iscoroutinefunction(refresh):
        refresh()
        return
    idx.scan()


def _add_path(idx: FileIndex, rel: str) -> None:
    fn = getattr(idx, "add_path", None)
    if callable(fn):
        fn(rel)
        return
    scan = getattr(idx, "scan", None)
    if callable(scan):
        scan()


def _remove_path(idx: FileIndex, rel: str) -> None:
    fn = getattr(idx, "remove_path", None)
    if callable(fn):
        fn(rel)
        return
    scan = getattr(idx, "scan", None)
    if callable(scan):
        scan()


def _add_batch(idx: FileIndex, n: int = 200) -> None:
    for i in range(n):
        _add_path(idx, f"extra_{i:04d}.py")


def _remove_batch(idx: FileIndex, n: int = 200) -> None:
    for i in range(n):
        _remove_path(idx, f"src/pkg_00/mod_{i:04d}.py")


async def _app_expand(text: str, cwd: Path, idx: FileIndex) -> str:
    expand_async = getattr(idx, "read_async", None)
    if hasattr(idx, "ensure_scanned"):
        return await asyncio.to_thread(expand_attachments, text, cwd, idx.read)
    if callable(expand_async):
        result = expand_async
        _ = result
    return expand_attachments(text, cwd, idx.read)


async def _app_replace(store: SessionStore, messages: list[Any]) -> None:
    for name in ("areplace", "replace_async"):
        fn = getattr(store, name, None)
        if callable(fn):
            result = fn(messages)
            if asyncio.iscoroutine(result):
                await result
                return
    store.replace(messages)


async def _app_messages(store: SessionStore) -> list[Any]:
    fn = getattr(store, "aget_messages", None)
    if callable(fn):
        result = fn()
        if asyncio.iscoroutine(result):
            return await result
    if hasattr(store, "replace_async"):
        return await asyncio.to_thread(lambda: store.messages)
    return store.messages


def _delta_updates() -> dict[str, float]:
    try:
        from b3code.ui.coalesce import count_markdown_updates

        n = count_markdown_updates(DELTA_BURST)
    except ImportError:
        n = DELTA_BURST
    return {
        "wall_ms": 0.0,
        "max_gap_ms": 0.0,
        "p95_gap_ms": 0.0,
        "missed_ticks": 0.0,
        "updates": float(n),
    }


async def _stall(
    work: Callable[[], Awaitable[Any] | Any],
) -> tuple[Any, dict[str, float]]:
    gaps: list[float] = []
    last = time.perf_counter()
    running = True

    async def beat() -> None:
        nonlocal last
        while running:
            now = time.perf_counter()
            gaps.append(now - last)
            last = now
            await asyncio.sleep(HEARTBEAT)

    task = asyncio.create_task(beat())
    await asyncio.sleep(0)
    t0 = time.perf_counter()
    result = work()
    if asyncio.iscoroutine(result):
        result = await result
    done = time.perf_counter()
    # Beat may still be inside sleep(); record the stall that just happened.
    gaps.append(done - last)
    wall_ms = (done - t0) * 1000
    running = False
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    gaps_ms = [g * 1000 for g in gaps if g > 0]
    if not gaps_ms:
        gaps_ms = [wall_ms]
    p95 = (
        statistics.quantiles(gaps_ms, n=20)[18] if len(gaps_ms) >= 20 else max(gaps_ms)
    )
    missed = sum(1 for g in gaps_ms if g > HEARTBEAT * 1000 * 2.5)
    return result, {
        "wall_ms": wall_ms,
        "max_gap_ms": max(gaps_ms),
        "p95_gap_ms": p95,
        "missed_ticks": float(missed),
    }


def _row(name: str, m: dict[str, float]) -> str:
    extra = ""
    if "updates" in m:
        extra = f"  updates={int(m['updates'])}"
    return (
        f"{name:<22} wall={m['wall_ms']:8.1f}ms  "
        f"max_gap={m['max_gap_ms']:8.1f}ms  "
        f"p95_gap={m['p95_gap_ms']:7.1f}ms  "
        f"missed={int(m['missed_ticks']):3d}{extra}"
    )


async def run_bench() -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix="b3code-bench-"))
    attach = _write_tree(tmp)
    messages = _synth_messages()
    session_path = tmp / "sessions.json"
    store = SessionStore(session_path)
    store.replace(messages)
    store = SessionStore(session_path)

    results: dict[str, dict[str, float]] = {}

    _, results["index_build"] = await _stall(lambda: _app_index_build(tmp))
    idx = _ready_index(tmp)

    _, results["index_search"] = await _stall(lambda: _app_search(idx, "mod"))
    _, results["index_refresh"] = await _stall(lambda: _app_refresh(idx))
    _, results["index_add_path"] = await _stall(lambda: _add_batch(idx))
    _, results["index_remove_path"] = await _stall(lambda: _remove_batch(idx))
    prompt = "explica " + " ".join(f"@{n}" for n in attach)
    _, results["expand"] = await _stall(lambda: _app_expand(prompt, tmp, idx))

    # First access after a fresh load (no cache). Second access (cache after opt).
    store = SessionStore(session_path)
    _, results["session_messages"] = await _stall(lambda: _app_messages(store))
    _, results["session_messages_2"] = await _stall(lambda: _app_messages(store))

    store.replace(messages)
    _, results["session_replace"] = await _stall(lambda: _app_replace(store, messages))

    tools = {name: tool.function for name, tool in workspace_toolset(tmp).tools.items()}
    _, results["grep"] = await _stall(lambda: tools["grep"]("class "))

    results["delta_updates"] = _delta_updates()

    cfg = AppConfig(use_provider_gateway=False, gateway_api_models=["gpt-4o"])
    ConfigStore(tmp / "config.json").save(cfg)
    chat = ChatService(cfg, store, tmp, model=TestModel())
    reg = CommandRegistry.build(ConfigStore(tmp / "config.json"), cfg, store, chat)
    list_models(cfg)
    item = Suggestion(
        value="anthropic:claude-fable-5",
        label="anthropic:claude-fable-5",
        hint="catalog",
        kind="arg",
        consume=True,
    )
    typed = "/model claude-fable"

    def _repeat(fn, n: int) -> None:
        for _ in range(n):
            fn()

    _, results["complete_root"] = await _stall(
        lambda: _repeat(lambda: reg.complete("/"), 500)
    )
    _, results["complete_model"] = await _stall(
        lambda: _repeat(lambda: reg.complete("/model claude"), 100)
    )
    _, results["decide_submit"] = await _stall(
        lambda: _repeat(lambda: decide_submit(typed, len(typed), item), 2_000)
    )
    _, results["apply_suggestion"] = await _stall(
        lambda: _repeat(lambda: apply_suggestion(typed, len(typed), item), 2_000)
    )

    return {
        "fixture": {
            "useful": USEFUL,
            "junk_per_dir": JUNK,
            "session_messages": len(messages),
            "delta_burst": DELTA_BURST,
        },
        "metrics": results,
    }


def _print_compare(
    bm: dict[str, dict[str, float]], am: dict[str, dict[str, float]]
) -> None:
    print("\ncompare (before → after)")
    for name in bm:
        if name not in am:
            continue
        b, a = bm[name], am[name]
        wall_pct = (
            ((a["wall_ms"] - b["wall_ms"]) / b["wall_ms"] * 100)
            if b["wall_ms"]
            else 0.0
        )
        print(
            f"  {name:<22} wall {b['wall_ms']:8.1f} → {a['wall_ms']:8.1f} ({wall_pct:+6.1f}%)  "
            f"max_gap {b['max_gap_ms']:8.1f} → {a['max_gap_ms']:8.1f}"
        )


def _stall_failures(am: dict[str, dict[str, float]]) -> list[str]:
    names = (
        "index_build",
        "index_search",
        "index_refresh",
        "expand",
        "session_replace",
    )
    failures: list[str] = []
    for name in names:
        gap = am[name]["max_gap_ms"]
        if gap > STALL_GATE_MS:
            failures.append(f"{name} max_gap_ms {gap:.1f} > {STALL_GATE_MS}")
    return failures


def _wall_failures(
    bm: dict[str, dict[str, float]], am: dict[str, dict[str, float]]
) -> list[str]:
    failures: list[str] = []
    for name in ("index_build", "grep"):
        if am[name]["wall_ms"] > bm[name]["wall_ms"] * 1.15 + 5:
            failures.append(
                f"{name} wall_ms regressed {bm[name]['wall_ms']:.1f} → {am[name]['wall_ms']:.1f}"
            )
    for name in ("index_add_path", "index_remove_path"):
        if name not in bm or name not in am:
            continue
        if am[name]["wall_ms"] > bm[name]["wall_ms"] * 0.5 and bm[name]["wall_ms"] > 5:
            failures.append(
                f"{name} wall_ms not incremental {bm[name]['wall_ms']:.1f} → {am[name]['wall_ms']:.1f}"
            )
    return failures


def _compare(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    bm = before["metrics"]
    am = after["metrics"]
    _print_compare(bm, am)
    failures = _stall_failures(am) + _wall_failures(bm, am)
    b2 = bm.get("session_messages_2", bm["session_messages"])
    a2 = am.get("session_messages_2", am["session_messages"])
    if a2["wall_ms"] > b2["wall_ms"] * 0.6 + 2 and a2["wall_ms"] > 1.0:
        failures.append(
            f"session_messages_2 not cached enough {b2['wall_ms']:.1f} → {a2['wall_ms']:.1f}"
        )
    updates = am["delta_updates"].get("updates", DELTA_BURST)
    if updates >= DELTA_BURST * 0.5:
        failures.append(
            f"delta_updates {int(updates)} not coalesced (burst={DELTA_BURST})"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--compare", type=Path, default=None)
    args = parser.parse_args()

    data = asyncio.run(run_bench())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    print("fixture", data["fixture"])
    for name, m in data["metrics"].items():
        print(_row(name, m))
    print(f"wrote {args.out}")

    if args.compare is None:
        return 0
    before = json.loads(args.compare.read_text(encoding="utf-8"))
    failures = _compare(before, data)
    if failures:
        print("\nGATES FAILED:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nall gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
