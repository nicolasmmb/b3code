"""Parsers de argumentos de comando. Sem I/O."""


def slash_tokens(line: str) -> list[str]:
    """`/model ` (espaço no fim) = próximo token vazio, para listar subcomandos."""
    body = line[1:]
    parts = body.split()
    if body.endswith(" ") or body == "":
        return parts + [""]
    return parts


def parse_on_off(token: str) -> bool | None:
    """Aceita on/true e off/false. Qualquer outra coisa → None."""
    lowered = token.strip().lower()
    if lowered in {"on", "true"}:
        return True
    if lowered in {"off", "false"}:
        return False
    return None
