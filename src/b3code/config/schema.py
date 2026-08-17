"""Config persistida. JSON antigo (sem os campos novos) continua válido."""

import re
from typing import Literal, TypeAlias, get_args

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator
from pydantic_ai.settings import ThinkingEffort

DEFAULT_ACCENT = "#00b0e6"
DEFAULT_THEME_NAME = "b3code"


# Níveis do Pydantic AI (minimal..xhigh) + níveis do app:
# "off" = não enviar o setting; "auto" = default do provider.
# Unpacking estrelado em Literal é rejeitado pelo mypy (valid-type); ignore de propósito.
_THINKING_EFFORTS: tuple[str, ...] = get_args(ThinkingEffort)
ThinkingEffortLevels: TypeAlias = Literal[*_THINKING_EFFORTS, "off", "auto"]  # type: ignore[valid-type]  # noqa: UP040

DEFAULT_THINKING = "off"


def thinking_badge(level: str) -> str:
    if level == "off":
        return ""
    if level == "auto":
        return "think"
    return f"[think {level}]"


_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_SLUG_CHUNK = re.compile(r"[^a-z0-9]+")
_MCP_NAME = re.compile(r"^[A-Za-z0-9_-]+$")

DEFAULT_EXCLUDE_DIRECTORIES: list[str] = [
    ".git",
    ".venv",
    ".b3code",
    "node_modules",
    "__pycache__",
    "dist",
    "target",
    "build",
    "vendor",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
    ".pytest_cache",
]

# B3 institucional (guia da marca): ciano #00b0e6 / navy #003475.
# Fundo e superfícies ficam cinza-neutro — navy de canvas quebra contraste.
THEME_COLOR_DEFAULTS: dict[str, str] = {
    "background": "#1c1d1f",
    "foreground": "#e6e8ea",
    "accent": DEFAULT_ACCENT,
    "muted": "#8b9198",
    "border": "#3c4046",
    "surface": "#26282c",
    "error": "#e05a5a",
    "success": "#3fba7a",
}


def parse_hex(value: object, default: str) -> str:
    if isinstance(value, str) and _HEX.match(value.strip()):
        return value.strip()
    return default


def slugify_theme(value: str) -> str:
    text = _SLUG_CHUNK.sub("-", value.strip().lower()).strip("-")
    if not text or not text[0].isalpha():
        return ""
    return text[:32]


def parse_theme_name(value: object, default: str = DEFAULT_THEME_NAME) -> str:
    if not isinstance(value, str):
        return default
    return slugify_theme(value) or default


def _normalize_exclude_directories(value: object) -> list[str]:
    if not isinstance(value, list):
        return value
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _normalize_exclude_extensions(value: object) -> list[str]:
    if not isinstance(value, list):
        return value
    result: list[str] = []
    for item in value:
        text = str(item).strip().lower()
        if not text:
            continue
        if not text.startswith("."):
            text = "." + text
        result.append(text)
    return result


class ThemeColors(BaseModel):
    name: str = DEFAULT_THEME_NAME
    label: str = ""
    background: str = THEME_COLOR_DEFAULTS["background"]
    foreground: str = THEME_COLOR_DEFAULTS["foreground"]
    accent: str = THEME_COLOR_DEFAULTS["accent"]
    muted: str = THEME_COLOR_DEFAULTS["muted"]
    border: str = THEME_COLOR_DEFAULTS["border"]
    surface: str = THEME_COLOR_DEFAULTS["surface"]
    error: str = THEME_COLOR_DEFAULTS["error"]
    success: str = THEME_COLOR_DEFAULTS["success"]

    @model_validator(mode="before")
    @classmethod
    def _slug_and_label(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        raw = data.get("name")
        if not isinstance(raw, str):
            return data
        slug = slugify_theme(raw)
        if not slug:
            data["name"] = DEFAULT_THEME_NAME
            return data
        data["name"] = slug
        label = data.get("label")
        if isinstance(label, str) and label.strip():
            data["label"] = label.strip()
        else:
            pretty = raw.strip()
            data["label"] = pretty if pretty != slug else ""
        return data

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: object) -> str:
        return parse_theme_name(value)

    @field_validator(
        "background",
        "foreground",
        "accent",
        "muted",
        "border",
        "surface",
        "error",
        "success",
        mode="before",
    )
    @classmethod
    def _hex(cls, value: object, info: ValidationInfo) -> str:
        default = THEME_COLOR_DEFAULTS[info.field_name]
        return parse_hex(value, default)

    @property
    def display(self) -> str:
        return self.label or self.name


def github_dark_theme() -> ThemeColors:
    # Primer dark: canvas-default, fg-default, accent-fg, fg-muted,
    # border-default, canvas-subtle, danger-fg, success-fg.
    return ThemeColors(
        name="github-dark",
        background="#0d1117",
        foreground="#e6edf3",
        accent="#58a6ff",
        muted="#8b949e",
        border="#30363d",
        surface="#161b22",
        error="#f85149",
        success="#3fb950",
    )


def default_themes() -> list[ThemeColors]:
    return [ThemeColors(), github_dark_theme()]


def parse_mcp_name(value: object) -> str:
    if not isinstance(value, str) or not _MCP_NAME.match(value):
        raise ValueError(f"invalid mcp server name {value!r}")
    return value


class McpServerConfig(BaseModel):
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    transport: str = ""
    startup_timeout_sec: int = 30
    tool_timeout_sec: int = 120

    @model_validator(mode="after")
    def _normalize(self) -> "McpServerConfig":
        has_cmd = bool(self.command.strip())
        has_url = bool(self.url.strip())
        if has_cmd == has_url:
            raise ValueError("mcp server needs either command or url")
        kind = self.transport.strip().lower()
        if not kind:
            kind = _infer_mcp_transport(has_cmd, self.url)
        if kind not in {"stdio", "http", "sse"}:
            raise ValueError("mcp transport must be stdio, http, or sse")
        if kind == "stdio" and not has_cmd:
            raise ValueError("stdio mcp server needs command")
        if kind in {"http", "sse"} and not has_url:
            raise ValueError("http/sse mcp server needs url")
        self.transport = kind
        return self

    @property
    def target(self) -> str:
        if self.url:
            return self.url
        return " ".join([self.command, *self.args]).strip()


def _infer_mcp_transport(has_cmd: bool, url: str) -> str:
    if has_cmd:
        return "stdio"
    if url.rstrip("/").endswith("/sse"):
        return "sse"
    return "http"


class AppConfig(BaseModel):
    # true = Azure do JSON é o gateway. false = catálogo pydantic-ai.
    use_provider_gateway: bool = True
    gateway_api_key: str = ""
    gateway_api_endpoint: str = ""
    gateway_api_models: list[str] = Field(default_factory=lambda: ["gpt-4o"])
    # Modelo ativo. No gateway é um item de gateway_api_models; no catálogo é provider:model.
    selected_model: str = ""
    # Pastas omitidas na descoberta (walk, índice, list_dir, grep).
    exclude_directories: list[str] = Field(
        default_factory=lambda: list(DEFAULT_EXCLUDE_DIRECTORIES)
    )
    # Extensões omitidas na descoberta. Normalizadas com ponto e minúsculas.
    exclude_extensions: list[str] = Field(default_factory=list)
    # Paths absolutos que o Shell pode usar sem perguntar de novo.
    shell_allowed_paths: list[str] = Field(default_factory=list)
    selected_theme: str = DEFAULT_THEME_NAME
    themes: list[ThemeColors] = Field(default_factory=default_themes)
    # true = paste preserva \n; Shift+Enter / Alt+Enter inserem newline.
    # false = composer de uma linha (Enter envia; newline não entra).
    multiline: bool = True
    # Unified Pydantic AI Thinking effort. off = do not send the setting.
    thinking: ThinkingEffortLevels = DEFAULT_THINKING
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)

    @field_validator("mcp_servers", mode="before")
    @classmethod
    def _mcp_server_names(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {parse_mcp_name(name): spec for name, spec in value.items()}

    @field_validator("selected_theme", mode="before")
    @classmethod
    def _selected_theme_name(cls, value: object) -> str:
        return parse_theme_name(value)

    @field_validator("thinking", mode="before")
    @classmethod
    def _thinking_level(cls, value: object) -> str:
        if not isinstance(value, str):
            return DEFAULT_THINKING
        level = value.strip().lower()
        if level not in get_args(ThinkingEffortLevels):
            raise ValueError(
                f"thinking must be one of {', '.join(get_args(ThinkingEffortLevels))}"
            )
        return level

    @field_validator("exclude_directories", mode="before")
    @classmethod
    def _normalize_exclude_dirs(cls, value: object) -> object:
        return _normalize_exclude_directories(value)

    @field_validator("exclude_extensions", mode="before")
    @classmethod
    def _normalize_exclude_exts(cls, value: object) -> object:
        return _normalize_exclude_extensions(value)

    @model_validator(mode="after")
    def _default_selected(self) -> "AppConfig":
        if not self.selected_model:
            self.selected_model = (
                self.gateway_api_models[0] if self.gateway_api_models else "gpt-4o"
            )
        if not self.themes:
            self.themes = default_themes()
        names = {item.name for item in self.themes}
        if self.selected_theme not in names:
            self.selected_theme = self.themes[0].name
        return self

    @property
    def model(self) -> str:
        return self.selected_model

    @property
    def theme(self) -> ThemeColors:
        for item in self.themes:
            if item.name == self.selected_theme:
                return item
        return self.themes[0]

    @property
    def accent(self) -> str:
        return self.theme.accent
