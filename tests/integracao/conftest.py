"""Pilha real para a integração (D24): API, Runner, agentes, tools, callbacks e SQLite.

Só o Gemini é trocado, pelo `ModeloRoteirizado`, injetado em `criar_app(modelo=...)`.
Cada teste usa um único event loop (um `asyncio.Runner`) para todas as requisições,
o `asyncio.gather` da disputa e o reinício: conexões `aiosqlite` e `asyncio.Lock`
nunca passam de um loop para outro.
"""

import asyncio
from collections.abc import Coroutine
from pathlib import Path

import httpx
import pytest
from google.adk.runners import Runner
from google.adk.sessions.sqlite_session_service import SqliteSessionService

from aurora.agentes import criar_app
from aurora.api import criar_api
from aurora.banco import garantir_esquema, restaurar_dados
from tests.integracao.modelo_roteirizado import ModeloRoteirizado


class Pilha:
    def __init__(self, dir_var: Path):
        self._caminho_sessoes = str(dir_var / "sessoes.db")
        self._loop = asyncio.Runner()
        self.modelo = ModeloRoteirizado()
        self._runner: Runner | None = None
        self._servico: SqliteSessionService | None = None
        self._cliente: httpx.AsyncClient | None = None
        self.executar(self._montar())

    def executar(self, corrotina: Coroutine):
        """Roda a corrotina no loop único deste teste."""
        return self._loop.run(corrotina)

    async def _montar(self) -> None:
        self._servico = SqliteSessionService(self._caminho_sessoes)
        self._runner = Runner(app=criar_app(modelo=self.modelo), session_service=self._servico)
        api = criar_api(runner=self._runner, session_service=self._servico)
        # O ASGITransport não roda o lifespan: o esquema e a carga vêm da fixture.
        self._cliente = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api), base_url="http://aurora"
        )

    async def _desmontar(self) -> None:
        if self._cliente is not None:
            await self._cliente.aclose()
        if self._runner is not None:
            await self._runner.close()
        if self._servico is not None:
            await self._servico.close()
        self._cliente = self._runner = self._servico = None

    async def _reiniciar(self) -> None:
        await self._desmontar()
        await self._montar()

    # Variantes assíncronas, para combinar requisições com asyncio.gather.
    async def nova_sessao_async(self, apto: str) -> str:
        r = await self._cliente.post("/sessoes", json={"apartamento": apto})
        assert r.status_code == 201, r.text
        return r.json()["session_id"]

    async def mensagem_async(self, sid: str, texto: str) -> dict:
        r = await self._cliente.post(f"/sessoes/{sid}/mensagens", json={"texto": texto})
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()

    async def confirmar_async(self, sid: str, id: str, confirmado: bool) -> httpx.Response:
        return await self._cliente.post(
            f"/sessoes/{sid}/confirmacoes", json={"id": id, "confirmado": confirmado}
        )

    async def eventos_async(self, sid: str) -> list:
        r = await self._cliente.get(f"/sessoes/{sid}/eventos")
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()

    # Variantes síncronas, no mesmo loop.
    def nova_sessao(self, apto: str) -> str:
        return self.executar(self.nova_sessao_async(apto))

    def mensagem(self, sid: str, texto: str) -> dict:
        return self.executar(self.mensagem_async(sid, texto))

    def confirmar(self, sid: str, id: str, confirmado: bool) -> httpx.Response:
        return self.executar(self.confirmar_async(sid, id, confirmado))

    def eventos(self, sid: str) -> list:
        return self.executar(self.eventos_async(sid))

    def reiniciar(self) -> None:
        """Garantia 3: serviço de sessões, Runner e API novos sobre os mesmos arquivos."""
        self.executar(self._reiniciar())

    def fechar(self) -> None:
        try:
            self.executar(self._desmontar())
        finally:
            self._loop.close()


@pytest.fixture
def pilha(tmp_path, monkeypatch):
    monkeypatch.setenv("AURORA_DIR_VAR", str(tmp_path))
    garantir_esquema()
    restaurar_dados()
    pilha = Pilha(tmp_path)
    yield pilha
    pilha.fechar()
    assert not pilha.modelo.fila, (
        f"Sobraram {len(pilha.modelo.fila)} respostas no roteiro: "
        "o fluxo chamou o modelo menos vezes do que o roteiro previa."
    )
