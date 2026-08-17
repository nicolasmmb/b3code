"""Fuzzy match de paths — gate de substring + WRatio com fallback."""

from __future__ import annotations

from pathlib import Path

from rapidfuzz import fuzz, process

_MIN_SCORE = 40


def _tokens(query: str) -> list[str]:
    return [t for t in query.lower().replace("\\", "/").split("/") if t]


def _basename(rel: str) -> str:
    return rel.replace("\\", "/").rsplit("/", 1)[-1]


def _matches_substring(query: str, rel: str, tokens: list[str]) -> bool:
    lower = rel.lower()
    if query.lower() in lower:
        return True
    return any(t in lower for t in tokens)


def _select_matched(query: str, rels: list[str], tokens: list[str]) -> list[str]:
    """Candidatos do gate de substring; vazio = fallback (conjunto inteiro)."""
    matched = [rel for rel in rels if _matches_substring(query, rel, tokens)]
    return matched or rels


def rank_paths(
    query: str, paths: list[Path] | list[str], limit: int = 20
) -> list[Path]:
    """Ranqueia paths por score path+basename, com fallback WRatio.

    O gate de substring é barato em repos grandes: só candidatos que
    contêm um token da query passam para o WRatio. Se nenhum candidato
    passa (typo sem substring), o fallback roda WRatio sobre o conjunto.
    """
    if not paths:
        return []
    if not query:
        return [Path(p) for p in paths[:limit]]
    choices = {str(p): Path(p) for p in paths}
    rels = list(choices)
    q_lower = query.lower()
    tokens = _tokens(query)
    matched = _select_matched(query, rels, tokens)
    # O score roda em C++ (process.extract) sobre o conjunto já filtrado
    # pelo gate — evita o overhead de chamar fuzz.WRatio em loop Python.
    hits = process.extract(
        query, matched, scorer=fuzz.WRatio, limit=max(limit * 4, 80)
    )
    scored: list[tuple[float, str, Path]] = []
    for name, raw, _ in hits:
        base = _basename(name)
        if raw < _MIN_SCORE and q_lower not in base.lower():
            continue
        bonus = 0
        if base.lower().startswith(q_lower):
            bonus += 25
        elif any(seg.startswith(t) for seg in name.split("/") for t in tokens):
            bonus += 15
        if name.lower().startswith(q_lower):
            bonus += 10
        scored.append((-(raw + bonus), name.lower(), choices[name]))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [path for _, _, path in scored[:limit]]
