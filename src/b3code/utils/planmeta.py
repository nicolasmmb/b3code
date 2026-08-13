"""Parser puro do markdown de plano — título, seções, linhas."""


def plan_meta(content: str) -> tuple[str, list[str], int]:
    """title, ## headings, line count — for the approval strip."""
    title = "untitled"
    heads: list[str] = []
    lines = content.splitlines()
    for line in lines:
        if line.startswith("# ") and not line.startswith("##"):
            title = line[2:].strip() or title
        elif line.startswith("## "):
            heads.append(line[3:].strip())
    return title, heads, len(lines)
