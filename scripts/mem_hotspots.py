"""RSS + tracemalloc dos hotspots (scan, sessão, @, grep, diff).

uv run python scripts/mem_hotspots.py --out .b3code/mem-before.txt
uv run python scripts/mem_hotspots.py --out .b3code/mem-after.txt
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import tempfile
import tracemalloc
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from pydantic_ai.messages import (  # noqa: E402
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)

from b3code.services.files import FileIndex  # noqa: E402
from b3code.services.session import SessionStore, turns_from_messages  # noqa: E402
from b3code.tools.workspace import workspace_toolset  # noqa: E402
from b3code.utils.diffview import diff_texts  # noqa: E402
from b3code.utils.prompt import expand_attachments  # noqa: E402

USEFUL = 400
ATTACH_CHARS = 120_000
SESSION_TURNS = 40
DIFF_LINES = 2_000


def _rss_kb() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def _write_tree(root: Path) -> Path:
    src = root / "src"
    src.mkdir()
    big = src / "big.txt"
    big.write_text("x" * ATTACH_CHARS, encoding="utf-8")
    for i in range(USEFUL):
        sub = src / f"pkg_{i // 50:02d}"
        sub.mkdir(exist_ok=True)
        (sub / f"mod_{i:04d}.py").write_text(
            f"class Foo{i}:\n    pass\n", encoding="utf-8"
        )
    junk = root / "target" / "pkg"
    junk.mkdir(parents=True)
    for i in range(80):
        (junk / f"out_{i}.o").write_text("obj\n", encoding="utf-8")
    (root / "blob.bin").write_bytes(b"class Hidden\x00" + b"z" * 1000)
    return big


def _synth_messages() -> list:
    msgs = []
    blob = "payload " * 800
    for i in range(SESSION_TURNS):
        msgs.append(ModelRequest(parts=[UserPromptPart(content=f"look at {i}")]))
        msgs.append(
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_file", args={"path": blob}),
                    TextPart(content=f"summary {i} " + ("word " * 20)),
                ]
            )
        )
    return msgs


def _snap(label: str, extra: dict | None = None) -> dict:
    current, peak = tracemalloc.get_traced_memory()
    row = {
        "label": label,
        "rss_kb": _rss_kb(),
        "traced_current_kb": current // 1024,
        "traced_peak_kb": peak // 1024,
    }
    if extra:
        row.update(extra)
    return row


def run() -> dict:
    tracemalloc.start()
    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        big = _write_tree(root)

        idx = FileIndex(root)
        idx.scan()
        stored = [str(p) for p in idx.search("", limit=100_000)]
        rows.append(
            _snap(
                "index_scan",
                {
                    "indexed_files": len(stored),
                    "indexed_target": sum(
                        1 for n in stored if n == "target" or n.startswith("target/")
                    ),
                },
            )
        )

        add_path = getattr(idx, "add_path", None)
        remove_path = getattr(idx, "remove_path", None)
        if callable(add_path):
            add_path(stored[0] if stored else "keep.py")
        if callable(remove_path):
            remove_path("missing-no-such-file.py")
        mutated = [str(p) for p in idx.search("", limit=100_000)]
        rows.append(
            _snap(
                "index_mutate",
                {
                    "indexed_files": len(mutated),
                    "stable": len(mutated) == len(stored),
                },
            )
        )

        expanded = expand_attachments("veja @src/big.txt", root, idx.read)
        rows.append(
            _snap(
                "expand_120k",
                {
                    "expand_chars": len(expanded),
                    "truncated": "...[truncated]" in expanded,
                },
            )
        )

        store = SessionStore(root / ".b3code" / "sessions.json")
        store.replace(_synth_messages())
        turns = turns_from_messages(store.messages)
        tool_text = sum(len(t.text) for t in turns if t.role == "tool")
        rows.append(
            _snap(
                "session_40_turns",
                {
                    "session_json_bytes": (root / ".b3code" / "sessions.json")
                    .stat()
                    .st_size
                    if (root / ".b3code" / "sessions.json").exists()
                    else 0,
                    "display_tool_text_chars": tool_text,
                    "split_dir": (root / ".b3code" / "sessions").is_dir(),
                },
            )
        )

        grep = workspace_toolset(root).tools["grep"].function
        hits = grep("class")
        rows.append(
            _snap(
                "grep_class",
                {
                    "grep_chars": len(hits),
                    "grep_hit_bin": "blob.bin" in hits,
                },
            )
        )

        new = "\n".join(f"line {i}" for i in range(DIFF_LINES))
        change = diff_texts("huge.py", "", new)
        rows.append(
            _snap(
                "diff_2k",
                {
                    "diff_stored_lines": len(change.lines),
                    "diff_added": change.added,
                },
            )
        )
        _ = big

    top = tracemalloc.take_snapshot().statistics("lineno")[:15]
    return {
        "rss_kb": _rss_kb(),
        "steps": rows,
        "top_alloc": [f"{s.traceback}: {s.size // 1024} KiB" for s in top],
    }


def _compare(before: dict, after: dict) -> None:
    print("compare (before → after)")
    by_before = {row["label"]: row for row in before["steps"]}
    for row in after["steps"]:
        old = by_before.get(row["label"], {})
        print(f"  {row['label']}")
        for key, value in row.items():
            if key in {"label", "rss_kb", "traced_current_kb", "traced_peak_kb"}:
                continue
            prev = old.get(key)
            print(f"    {key}: {prev!r} → {value!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--compare", type=Path, default=None)
    args = parser.parse_args()
    data = run()
    text = json.dumps(data, indent=2) + "\n"
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    if args.compare is not None:
        _compare(json.loads(args.compare.read_text(encoding="utf-8")), data)


if __name__ == "__main__":
    main()
