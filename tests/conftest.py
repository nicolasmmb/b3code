"""Fixtures globais (autouse).

- `B3CODE_HOME` sempre aponta para um tmp por teste: nenhum teste escreve no
  diretório real do usuário (`~/.b3code`).
- `OPENAI_API_KEY` dummy: testes de agentes constroem `OpenAIChatModel` sem
  chamar a API; um valor qualquer satisfaz a validação do provider em
  qualquer ambiente (nenhum teste depende da ausência da chave).
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def b3code_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "b3code-home"
    monkeypatch.setenv("B3CODE_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def _model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
