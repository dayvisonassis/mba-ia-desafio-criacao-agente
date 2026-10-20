"""Caminhos, ambiente e modelo do projeto."""

import os
from pathlib import Path

from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parents[2]
DIR_DADOS = RAIZ / "dados"
MODELO_PADRAO = "gemini-3.5-flash-lite"
MODELO_ALTERNATIVO = "gemini-3.8-flash"


def dir_var() -> Path:
    """Pasta dos bancos; lida a cada chamada para os testes poderem trocá-la."""
    valor = os.environ.get("AURORA_DIR_VAR", "")
    return Path(valor) if valor else RAIZ / "var"


def caminho_banco() -> Path:
    return dir_var() / "aurora.db"


def caminho_sessoes() -> Path:
    return dir_var() / "sessoes.db"


def carregar_ambiente(caminho: Path | None = None) -> None:
    """Aplica o .env ao processo (o .env vence variáveis globais) e força o AI Studio.

    AURORA_DIR_VAR já definida no processo não é sobrescrita, para que um .env
    copiado do exemplo não desvie os bancos dos testes para o var/ real.
    """
    valores = dotenv_values(caminho or RAIZ / ".env")
    for chave, valor in valores.items():
        if valor is None:
            continue
        if chave == "AURORA_DIR_VAR" and chave in os.environ:
            continue
        os.environ[chave] = valor
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"


def nome_modelo() -> str:
    return os.environ.get("GEMINI_MODELO", "").strip() or MODELO_PADRAO
