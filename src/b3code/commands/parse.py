"""Parsers de argumentos de comando. Sem I/O."""

from dataclasses import dataclass, field


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


@dataclass
class McpAddRequest:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


def parse_kv(token: str) -> tuple[str, str] | None:
    if "=" not in token:
        return None
    key, value = token.split("=", 1)
    if not key.strip():
        return None
    return key.strip(), value


def parse_mcp_add(tokens: tuple[str, ...]) -> McpAddRequest:
    transport = "stdio"
    env: dict[str, str] = {}
    headers: dict[str, str] = {}
    positionals: list[str] = []
    i = 0
    items = list(tokens)
    while i < len(items):
        token = items[i]
        if token == "--":
            positionals.extend(items[i + 1 :])
            break
        taken = _flag_pair(items, i, env, headers)
        if taken is not None:
            if isinstance(taken, str):
                transport = taken
            i += 2
            continue
        positionals.append(token)
        i += 1
    return _finish_mcp_add(transport, env, headers, positionals)


def _flag_pair(
    items: list[str],
    index: int,
    env: dict[str, str],
    headers: dict[str, str],
) -> str | bool | None:
    if index + 1 >= len(items):
        return None
    token, nxt = items[index], items[index + 1]
    if token == "--transport":
        return nxt
    pair = parse_kv(nxt)
    if token in {"-e", "--env"} and pair:
        env[pair[0]] = pair[1]
        return True
    if token == "--header" and pair:
        headers[pair[0]] = pair[1]
        return True
    return None


def _finish_mcp_add(
    transport: str,
    env: dict[str, str],
    headers: dict[str, str],
    positionals: list[str],
) -> McpAddRequest:
    if transport not in {"stdio", "http", "sse"}:
        raise ValueError("usage: /mcp add --transport http|sse <name> <url>")
    if not positionals:
        raise ValueError("usage: /mcp add <name> -- <command> [args...]")
    name = positionals[0]
    rest = positionals[1:]
    if transport != "stdio":
        if len(rest) != 1:
            raise ValueError("usage: /mcp add --transport http|sse <name> <url>")
        return McpAddRequest(
            name=name, transport=transport, url=rest[0], env=env, headers=headers
        )
    if not rest:
        raise ValueError("usage: /mcp add <name> -- <command> [args...]")
    return McpAddRequest(
        name=name,
        command=rest[0],
        args=rest[1:],
        env=env,
        headers=headers,
    )
