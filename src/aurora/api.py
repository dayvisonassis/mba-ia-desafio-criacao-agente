"""API FastAPI do assistente: sessões, mensagens, confirmações e rotas de verificação."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from google.adk.runners import Runner
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types
from pydantic import BaseModel, field_validator

from aurora import agentes, banco, config, repositorio
from aurora.confirmacoes import (
    NOME_CONFIRMACAO,
    TEXTO_AVISO_FALHA,
    acao_executada,
    encontrar_pendente,
    houve_efeito,
    listar_pendentes,
    montar_resposta,
)

APP_NAME = "aurora"
log = logging.getLogger(__name__)


class NovaSessao(BaseModel):
    apartamento: str


class NovaMensagem(BaseModel):
    texto: str

    @field_validator("texto")
    @classmethod
    def _nao_vazio(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("o texto não pode ser vazio")
        return valor


class RespostaDeConfirmacao(BaseModel):
    id: str
    confirmado: bool


def _criou_pendente(emitidos: list) -> bool:
    return any(
        p.function_call and p.function_call.name == NOME_CONFIRMACAO
        for e in emitidos
        for p in (e.content.parts if e.content and e.content.parts else [])
    )


def criar_api(runner=None, session_service=None) -> FastAPI:
    """Monta a API. Sem `runner`, cria o de produção (carrega o .env e usa SQLite)."""
    if runner is None:
        config.carregar_ambiente()
        session_service = SqliteSessionService(str(config.caminho_sessoes()))
        runner = Runner(app=agentes.criar_app(), session_service=session_service)
    servico = session_service

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        banco.inicializar_se_necessario()
        yield

    app = FastAPI(title="Residencial Aurora", lifespan=lifespan)
    travas: dict[str, asyncio.Lock] = {}

    def trava(session_id: str) -> asyncio.Lock:
        return travas.setdefault(session_id, asyncio.Lock())

    app.state.trava = trava

    async def carregar_sessao(sid: str):
        """Devolve (apartamento, sessão) ou responde 404."""
        apto = repositorio.apartamento_da_sessao_id(sid)
        sessao = (
            await servico.get_session(app_name=APP_NAME, user_id=apto, session_id=sid)
            if apto is not None
            else None
        )
        if sessao is None:
            raise HTTPException(status_code=404, detail="Sessão não encontrada.")
        return apto, sessao

    async def montar_saida(apto: str, sid: str, emitidos: list, resposta: str | None = None):
        sessao = await servico.get_session(app_name=APP_NAME, user_id=apto, session_id=sid)
        pendentes = listar_pendentes(sessao.events, repositorio.mapa_areas())
        if resposta is None:
            resposta = montar_resposta(emitidos, _criou_pendente(emitidos))
        return {
            "resposta": resposta,
            "confirmacoes_pendentes": [
                {"id": p.id, "acao": p.acao, "detalhes": p.detalhes} for p in pendentes
            ],
        }

    @app.post("/sessoes", status_code=201)
    async def criar_sessao(corpo: NovaSessao):
        if not repositorio.apartamento_existe(corpo.apartamento):
            raise HTTPException(status_code=422, detail="Apartamento não encontrado.")
        sessao = await servico.create_session(
            app_name=APP_NAME,
            user_id=corpo.apartamento,
            state={"apartamento": corpo.apartamento},
        )
        repositorio.registrar_sessao(sessao.id, corpo.apartamento)
        return {"session_id": sessao.id}

    @app.post("/sessoes/{sid}/mensagens")
    async def enviar_mensagem(sid: str, corpo: NovaMensagem):
        apto, _ = await carregar_sessao(sid)
        mensagem = types.Content(role="user", parts=[types.Part(text=corpo.texto)])
        emitidos: list = []
        async with trava(sid):
            try:
                async for evento in runner.run_async(
                    user_id=apto, session_id=sid, new_message=mensagem
                ):
                    emitidos.append(evento)
            except Exception:
                log.exception("Falha ao processar a mensagem da sessão %s", sid)
                if not houve_efeito(emitidos):
                    raise HTTPException(
                        status_code=503,
                        detail="O assistente está indisponível no momento. Tente novamente em instantes.",
                    )
                return await montar_saida(apto, sid, emitidos, TEXTO_AVISO_FALHA)
            return await montar_saida(apto, sid, emitidos)

    @app.post("/sessoes/{sid}/confirmacoes")
    async def responder_confirmacao(sid: str, corpo: RespostaDeConfirmacao):
        apto, _ = await carregar_sessao(sid)
        async with trava(sid):
            sessao = await servico.get_session(
                app_name=APP_NAME, user_id=apto, session_id=sid
            )
            pendente = encontrar_pendente(
                sessao.events, repositorio.mapa_areas(), corpo.id
            )
            if pendente is None:
                raise HTTPException(
                    status_code=409,
                    detail="Não há confirmação pendente com esse id nesta sessão.",
                )
            mensagem = types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=pendente.id,
                            name=NOME_CONFIRMACAO,
                            response={"confirmed": corpo.confirmado},
                        )
                    )
                ],
            )
            emitidos: list = []
            try:
                async for evento in runner.run_async(
                    user_id=apto, session_id=sid, new_message=mensagem
                ):
                    emitidos.append(evento)
            except Exception:
                log.exception(
                    "Falha ao processar a confirmação %s da sessão %s", corpo.id, sid
                )
                raise HTTPException(
                    status_code=500,
                    detail="Não foi possível processar a confirmação. Tente novamente.",
                )
            if not acao_executada(emitidos, pendente.id_chamada_original):
                log.error(
                    "Confirmação %s da sessão %s não chegou à tool (chamada original %s)",
                    corpo.id,
                    sid,
                    pendente.id_chamada_original,
                )
                raise HTTPException(
                    status_code=500,
                    detail="A confirmação foi recebida, mas a ação não foi executada.",
                )
            return await montar_saida(apto, sid, emitidos)

    @app.get("/sessoes/{sid}/eventos")
    async def listar_eventos(sid: str):
        _, sessao = await carregar_sessao(sid)
        return [
            e.model_dump(mode="json", by_alias=True, exclude_none=True)
            for e in sessao.events
        ]

    @app.get("/apartamentos/{numero}/reservas")
    def reservas(numero: str):
        return [
            {"codigo": r.codigo, "area": r.area, "data": r.data}
            for r in repositorio.listar_reservas_ativas(numero)
        ]

    @app.get("/apartamentos/{numero}/visitantes")
    def visitantes(numero: str):
        return [
            {"nome": v.nome, "data": v.data}
            for v in repositorio.listar_visitantes(numero)
        ]

    return app
