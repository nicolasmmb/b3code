"""Fuzzy match simples — rapidfuzz no path relativo."""

from pathlib import Path

from rapidfuzz import fuzz, process


def rank_paths(
    query: str, paths: list[Path] | list[str], limit: int = 20
) -> list[Path]:
    if not paths:
        return []
    if not query:
        return [Path(p) for p in paths[:limit]]
    choices = {str(p): Path(p) for p in paths}
    hits = process.extract(
        query,
        choices.keys(),
        scorer=fuzz.WRatio,
        limit=limit,
    )
    return [choices[name] for name, score, _ in hits if score >= 40]
