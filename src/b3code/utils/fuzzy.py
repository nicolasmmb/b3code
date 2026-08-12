"""Fuzzy match simples — rapidfuzz no path relativo."""

from pathlib import Path

from rapidfuzz import fuzz, process


def rank_paths(query: str, paths: list[Path], limit: int = 20) -> list[Path]:
    if not paths:
        return []
    if not query:
        return paths[:limit]
    choices = {str(p): p for p in paths}
    hits = process.extract(
        query,
        choices.keys(),
        scorer=fuzz.WRatio,
        limit=limit,
    )
    return [choices[name] for name, score, _ in hits if score >= 40]
