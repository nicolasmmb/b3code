# b3code

TUI minimalista de chat (Textual + Pydantic AI + CodeMode + Azure).

```bash
uv sync
# edite .b3code/config.json (criado no primeiro run)
uv run b3code
```

Config (`.b3code/config.json`):

```json
{
  "use_provider_gateway": true,
  "api_key": "...",
  "api_endpoint": "https://SEU-RECURSO.openai.azure.com/openai/v1/",
  "api_models": ["gpt-4o"],
  "selected_model": "gpt-4o"
}
```

- `use_provider_gateway: true` — Azure do JSON (o gateway). `/model` lista `api_models`.
- `false` — catálogo do Pydantic AI (`openai:gpt-5.2`, `anthropic:claude-sonnet-4-6`, …). O provider lê a env dele (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …). Extra atual: `[openai]`; outros pedem `uv add "pydantic-ai-slim[anthropic]"` etc.
- `/gateway on|off` — persiste a flag
- `@arquivo` — anexa o conteúdo no turno
- `/help` `/new` `/resume` `/model` `/gateway` `/quit`
- sessão em `.b3code/sessions.json` (gitignore)

```bash
uv run pytest
```
