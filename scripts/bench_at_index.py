"""Benchmark do autocomplete `@` — índice de arquivos + fuzzy (novo vs antigo).

Gera um monorepo sintético (determinístico) no disco e mede:
  - `FileIndex.scan()` — walk + `.gitignore` + sort (tempo de parede)
  - `rank_paths` novo (b3code.utils.fuzzy) vs antigo (WRatio puro) em
    vários tipos de query: vazia, substring, path com "/", id único, typo, 1 char
  - `search_async` com índice quente (custo por tecla na TUI)
  - `refresh_if_stale` com índice fresco (skip) e com índice velho (re-scan)
  - memória pico do índice via tracemalloc

Uso:
  uv run python scripts/bench_at_index.py [N] [--keep]

Saída: JSON no stdout (os números para docs/perf/results/).
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from rapidfuzz import fuzz, process

from b3code.services.files import FileIndex
from b3code.utils.fuzzy import rank_paths

REPO_ROOT = Path(__file__).resolve().parent.parent


def _rank_paths_old(
    query: str, paths: list[str], limit: int = 20
) -> list[Path]:
    """Implementação anterior (antes da mudança): WRatio puro sobre tudo."""
    if not paths:
        return []
    if not query:
        return [Path(p) for p in paths[:limit]]
    choices = {str(p): Path(p) for p in paths}
    hits = process.extract(query, choices.keys(), scorer=fuzz.WRatio, limit=limit)
    return [choices[name] for name, score, _ in hits if score >= 40]


def _sample_ms(fn, rounds: int = 9) -> dict:
    """min/median/p95 (ms) de fn() com lote calibrado e GC pausado.

    Mesma técnica do tests/test_perf.py: aquece, calibra o lote para um
    round durar ~50 ms e julga pela mediana (imune a GC e relógio).
    """
    fn()
    t0 = time.perf_counter()
    fn()
    one = max(time.perf_counter() - t0, 1e-9)
    batch = max(1, min(5000, int(0.05 / one)))
    for _ in range(2):
        for _ in range(batch):
            fn()
    gc.collect()
    enabled = gc.isenabled()
    gc.disable()
    raw: list[float] = []
    try:
        for _ in range(rounds):
            start = time.perf_counter()
            for _ in range(batch):
                fn()
            raw.append((time.perf_counter() - start) * 1000 / batch)
    finally:
        if enabled:
            gc.enable()
    raw.sort()
    idx95 = min(len(raw) - 1, int(round(len(raw) * 0.95)))
    return {
        "min_ms": round(raw[0], 4),
        "median_ms": round(statistics.median(raw), 4),
        "p95_ms": round(raw[idx95], 4),
        "batch": batch,
    }


def _build_repo(root: Path, n: int) -> None:
    """Monorepo sintético determinístico: ~n arquivos com paths aninhados."""
    count = 0
    for app in ("app", "web", "api", "core", "lib"):
        d = root / "src" / app
        d.mkdir(parents=True, exist_ok=True)
        per = max(1, n // 5)
        for i in range(per):
            if count >= n:
                break
            (d / f"mod_{i:04d}.py").write_text("x = 1\n")
            count += 1
        if count >= n:
            break
    deep = root / "src" / "deep" / "a" / "b" / "c" / "d" / "e" / "f"
    deep.mkdir(parents=True, exist_ok=True)
    per_deep = max(1, n // 10)
    for i in range(per_deep):
        if count >= n:
            break
        (deep / f"deep_file_{i:05d}.rs").write_text("fn main() {}\n")
        count += 1
    (root / "app.py").write_text("print(1)\n")
    (root / "main.py").write_text("print(1)\n")
    (root / "README.md").write_text("# repo\n")


QUERIES = ("", "ap", "app/main", "mod_0123", "apl.py", "a")


def _bench_rank(queries: tuple[str, ...], paths: list[str]) -> dict:
    out: dict[str, dict] = {}
    for q in queries:
        out[q] = {
            "old": _sample_ms(lambda q=q: _rank_paths_old(q, paths)),
            "new": _sample_ms(lambda q=q: rank_paths(q, paths)),
        }
    return out


async def _bench_async(idx: FileIndex, queries: tuple[str, ...]) -> dict:
    out: dict[str, dict] = {}
    for q in queries:
        lat: list[float] = []
        for _ in range(7):
            t0 = time.perf_counter()
            await idx.search_async(q)
            lat.append((time.perf_counter() - t0) * 1000)
        lat.sort()
        out[q] = {
            "median_ms": round(statistics.median(lat), 4),
            "min_ms": round(lat[0], 4),
            "p95_ms": round(lat[int(round(len(lat) * 0.95)) - 1], 4),
        }
    return out


async def _bench_refresh(idx: FileIndex) -> dict:
    # skip com índice fresco: custo por chamada do worker periódico.
    # Zera o relógio do índice antes para nenhuma chamada re-scannear
    # (a primeira chamada com índice velho contaminaria a média).
    idx._scanned_at = time.monotonic()
    start = time.perf_counter()
    for _ in range(300):
        await idx.refresh_if_stale()
    skip_us = (time.perf_counter() - start) * 1e6 / 300
    # re-scan com índice velho (o que o worker faz a cada 5 s)
    idx._scanned_at = 0.0
    start = time.perf_counter()
    await idx.refresh_if_stale()
    stale_ms = (time.perf_counter() - start) * 1000
    return {"skip_us": round(skip_us, 2), "stale_scan_ms": round(stale_ms, 2)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("n", nargs="?", type=int, default=50_000, help="arquivos")
    parser.add_argument("--keep", action="store_true", help="não apagar o repo")
    args = parser.parse_args()
    n = max(1000, args.n)

    tmp = Path(tempfile.mkdtemp(prefix="bench_at_"))
    try:
        _build_repo(tmp, n)
        idx = FileIndex(tmp, cap=n)

        tracemalloc.start()
        t0 = time.perf_counter()
        idx.scan()
        scan_ms = (time.perf_counter() - t0) * 1000
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        paths = idx._listed()
        results = {
            "benchmark": "at-index",
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "python": sys.version.split()[0],
            "files_indexed": len(paths),
            "synthetic_repo": str(tmp),
            "scan_ms": round(scan_ms, 2),
            "memory_peak_mb": round(peak / 1024 / 1024, 2),
            "rank_paths": _bench_rank(QUERIES, paths),
            "search_async_warm": asyncio.run(_bench_async(idx, QUERIES)),
            "refresh_if_stale": asyncio.run(_bench_refresh(idx)),
        }
        if args.keep:
            print(f"repo kept at: {tmp}", file=sys.stderr)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0
    finally:
        if not args.keep:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
