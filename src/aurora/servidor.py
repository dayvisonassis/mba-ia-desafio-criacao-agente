"""Comando `uv run api`: sobe a API em http://127.0.0.1:8000."""

import uvicorn

from aurora.api import criar_api


def main() -> None:
    uvicorn.run(criar_api(), host="127.0.0.1", port=8000)
