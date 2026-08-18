"""Skills reutilizáveis (formato Grok/Claude `SKILL.md`).

Uma skill é uma pasta com um arquivo `SKILL.md`: frontmatter YAML plano
(bloco `---`) + corpo markdown. O `SkillIndex` descobre skills em roots
ordenados por prioridade (o primeiro vence no dedup por nome) e serve dois
caminhos de invocação:

- comando `/nome` (ver `commands/builtin/skills.py`);
- tools `list_skills` / `load_skill` para o modelo decidir em runtime
  (ver `tools/skills.py`).

Parser mínimo de frontmatter, sem PyYAML: linhas `chave: valor`, listas por
vírgula ou por linhas `- item`, booleans true/1/yes e false/0/no. Frontmatter
malformado cai no fallback (corpo inteiro, nome da pasta) — nunca quebra o boot.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

from b3code.config.dirs import b3code_home
from b3code.config.schema import SkillSettings

MAX_SKILLS = 200
MAX_SKILL_BODY = 12_000
_CATALOG_CHARS = 4_000
_DESCRIPTION_CHARS = 300

# Frontmatter: bloco `---` ... `---` no início do arquivo.
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", re.DOTALL)
_SLUG = re.compile(r"[^a-z0-9]+")
_KEY = re.compile(r"[^a-z0-9]+")
_TRUTHY = frozenset({"true", "1", "yes"})
_FALSY = frozenset({"false", "0", "no"})


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    when_to_use: str
    argument_hint: str
    allowed_tools: tuple[str, ...]
    body: str
    path: Path
    scope: str  # project | user | config
    user_invocable: bool = True
    disable_model_invocation: bool = False
    disabled: bool = False


def normalize_skill_name(raw: str) -> str:
    """Minúsculas, `[^a-z0-9]+` vira `-`, sem `-` nas pontas, máx. 64 chars."""
    text = _SLUG.sub("-", raw.strip().lower()).strip("-")
    return text[:64]


def parse_skill_file(path: Path) -> tuple[dict[str, object], str]:
    """Frontmatter plano + corpo. Sem frontmatter → ({}, texto completo)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}, ""
    match = _FRONTMATTER.match(raw)
    if match is None:
        return {}, raw
    meta = _parse_frontmatter(match.group(1))
    body = raw[match.end():].lstrip("\n")
    return meta, body


def _parse_frontmatter(head: str) -> dict[str, object]:
    meta: dict[str, object] = {}
    last_key: str | None = None
    for line in head.splitlines():
        stripped = line.strip()
        if not stripped:
            last_key = None
            continue
        if stripped.startswith("- "):
            items = meta.get(last_key) if last_key is not None else None
            if isinstance(items, list):
                items.append(_parse_scalar(stripped[2:]))
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        key = _key_name(key)
        if not key:
            continue
        last_key = key
        meta[key] = _parse_value(value.strip())
    return meta


def skill_from_file(path: Path, scope: str) -> Skill | None:
    """Constrói uma Skill. Parser inválido ou nome vazio → None."""
    meta, body = parse_skill_file(path)
    raw_name = meta.get("name")
    name = normalize_skill_name(str(raw_name) if raw_name else path.parent.name)
    if not name:
        return None
    description = _as_str(meta.get("description")) or _first_paragraph(body)
    description = description[: _DESCRIPTION_CHARS]
    when_to_use = _as_str(meta.get("when-to-use"))
    argument_hint = _as_str(meta.get("argument-hint"))
    raw_tools = meta.get("allowed-tools")
    allowed_tools: tuple[str, ...]
    if raw_tools is None:
        allowed_tools = ()
    elif isinstance(raw_tools, str):
        allowed_tools = (raw_tools,)
    elif isinstance(raw_tools, list):
        allowed_tools = tuple(
            str(item) for item in raw_tools if str(item).strip()
        )
    else:
        allowed_tools = ()
    return Skill(
        name=name,
        description=description,
        when_to_use=when_to_use,
        argument_hint=argument_hint,
        allowed_tools=allowed_tools,
        body=body[:MAX_SKILL_BODY],
        path=path,
        scope=scope,
        user_invocable=_as_bool(meta.get("user-invocable"), True),
        disable_model_invocation=_as_bool(
            meta.get("disable-model-invocation"), False
        ),
    )


class SkillIndex:
    """Descoberta, dedup por nome (primeiro root vence) e catálogo."""

    def __init__(
        self,
        cwd: Path,
        settings: SkillSettings | None = None,
        home: Path | None = None,
    ) -> None:
        self.cwd = Path(cwd).resolve()
        self.settings = settings or SkillSettings()
        self.home = Path(home).expanduser() if home is not None else Path.home()
        self._skills: list[Skill] = []
        self.scan()

    def roots(self) -> list[tuple[Path, str]]:
        entries: list[tuple[Path, str]] = [
            (b3code_home() / "skills", "user"),
            (self.home / ".grok" / "skills", "user"),
            (self.home / ".claude" / "skills", "user"),
        ]
        for raw in self.settings.extra_paths:
            entries.append((Path(raw).expanduser(), "config"))
        return entries

    def scan(self) -> None:
        """Síncrono e rápido. Recarrega o índice do disco."""
        self._skills = []
        if not self.settings.enabled:
            return
        seen: set[str] = set()
        ignored = self._ignored_prefixes()
        extra = {Path(raw).expanduser() for raw in self.settings.extra_paths}
        for root, scope in self.roots():
            if len(self._skills) >= MAX_SKILLS:
                break
            self._scan_root(root, scope, root in extra, ignored, seen)
        self._skills.sort(key=lambda s: (s.scope, s.name))

    def _scan_root(
        self,
        root: Path,
        scope: str,
        recursive: bool,
        ignored: list[Path],
        seen: set[str],
    ) -> None:
        candidates = (
            _skills_from_extra(root) if recursive else _skills_in_root(root)
        )
        for path in candidates:
            if len(self._skills) >= MAX_SKILLS:
                return
            skill = self._candidate(path, scope, ignored, seen)
            if skill is not None:
                self._skills.append(skill)

    def _candidate(
        self,
        path: Path,
        scope: str,
        ignored: list[Path],
        seen: set[str],
    ) -> Skill | None:
        if _under(path, ignored):
            return None
        skill = skill_from_file(path, scope)
        if skill is None or skill.name in seen:
            return None
        if skill.name in self.settings.disabled:
            skill = replace(skill, disabled=True)
        seen.add(skill.name)
        return skill

    def skills(self, *, include_disabled: bool = False) -> list[Skill]:
        if include_disabled:
            return list(self._skills)
        return [s for s in self._skills if not s.disabled]

    def get(self, name: str) -> Skill | None:
        for skill in self._skills:
            if skill.name == name:
                return skill
        return None

    def catalog(self) -> str:
        """Linhas `nome — descrição`, com ` (when: <when-to-use>)` quando houver."""
        lines: list[str] = []
        for skill in self.skills():
            if skill.disable_model_invocation:
                continue
            line = f"{skill.name} — {skill.description}"
            if skill.when_to_use:
                line += f" (when: {skill.when_to_use})"
            lines.append(line)
            if sum(len(item) for item in lines) >= _CATALOG_CHARS:
                lines.append("… (more skills — call /skills)")
                break
        return "\n".join(lines) or "no skills available"

    def load(self, name: str) -> str:
        """Corpo da skill em bloco `<skill>` (entra no user turn)."""
        skill = self.get(name)
        if skill is None:
            return ""
        return (
            f'<skill name="{skill.name}" scope="{skill.scope}">\n'
            f"{skill.body[:MAX_SKILL_BODY]}\n</skill>"
        )

    def _ignored_prefixes(self) -> list[Path]:
        prefixes: list[Path] = []
        for raw in self.settings.ignore:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = self.cwd / path
            prefixes.append(path.resolve())
        return prefixes


def _key_name(raw: str) -> str:
    return _KEY.sub("-", raw.strip().lower()).strip("-")


def _parse_scalar(value: str) -> object:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", "\""}:
        text = text[1:-1].strip()
    lowered = text.lower()
    if lowered in _TRUTHY:
        return True
    if lowered in _FALSY:
        return False
    return text


def _parse_value(value: str) -> object:
    if not value:
        return []  # lista pendente: linhas `- item` seguem
    if "," in value:
        return [
            item
            for item in (_parse_scalar(part) for part in value.split(","))
            if item != ""
        ]
    return _parse_scalar(value)


def _as_str(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value) if value is not None else ""


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _first_paragraph(body: str) -> str:
    for para in body.split("\n\n"):
        text = para.strip()
        if not text or set(text) <= {"-", "_", "*"}:
            continue  # regra horizontal do markdown / frontmatter quebrado
        return text
    return ""


def _skills_in_root(root: Path) -> list[Path]:
    """Subpastas diretas com `SKILL.md` (sem seguir symlinks)."""
    try:
        with os.scandir(root) as it:
            entries = list(it)
    except OSError:
        return []
    found: list[Path] = []
    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        skill = Path(entry.path) / "SKILL.md"
        try:
            if skill.is_file():
                found.append(skill)
        except OSError:
            continue
    return found


def _skills_from_extra(entry: Path) -> list[Path]:
    """Arquivo `SKILL.md` direto ou walk recursivo da pasta (sem symlinks)."""
    try:
        if entry.is_file() and entry.name == "SKILL.md":
            return [entry]
        if not entry.is_dir():
            return []
    except OSError:
        return []
    found: list[Path] = []
    try:
        for root, _dirs, files in os.walk(entry, followlinks=False):
            if "SKILL.md" in files:
                found.append(Path(root) / "SKILL.md")
    except OSError:
        return []
    return found


def _under(path: Path, prefixes: list[Path]) -> bool:
    if not prefixes:
        return False
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for prefix in prefixes:
        try:
            if resolved.is_relative_to(prefix):
                return True
        except ValueError:
            continue
    return False
