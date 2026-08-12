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
  "api_key": "...",
  "api_endpoint": "https://SEU-RECURSO.openai.azure.com/openai/v1/",
  "api_models": ["gpt-4o"]
}
```

- `@arquivo` — anexa o conteúdo no turno
- `/help` `/new` `/resume` `/model` `/quit`
- sessão em `.b3code/sessions.json` (gitignore)

```bash
uv run pytest
```
