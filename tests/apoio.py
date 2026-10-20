"""Apoio compartilhado pelos testes das tools e dos agentes."""

import json
import re
from types import SimpleNamespace

from google.adk.events import Event, EventActions
from google.adk.tools.function_tool import FunctionTool
from google.genai import types

from aurora.ferramentas import (
    FERRAMENTA_REGULAMENTO,
    FERRAMENTAS_RESERVAS,
    FERRAMENTAS_VISITANTES,
)


class ContextoFalso:
    """Imita o ToolContext com o que as tools e as funções de confirmação leem."""

    def __init__(
        self,
        apartamento="101",
        session_id="s1",
        function_call_id="c1",
        confirmacao=None,
        state=None,
    ):
        self.state = {"apartamento": apartamento} if state is None else state
        self.session = SimpleNamespace(id=session_id)
        self.function_call_id = function_call_id
        self.tool_confirmation = confirmacao
        self.actions = SimpleNamespace(skip_summarization=False)
        self.user_content = None


def ferramenta(nome: str) -> FunctionTool:
    todas = [*FERRAMENTAS_RESERVAS, *FERRAMENTAS_VISITANTES, FERRAMENTA_REGULAMENTO]
    return next(t for t in todas if t.name == nome)


def sem_vazamento(resposta) -> bool:
    texto = json.dumps(resposta, ensure_ascii=False)
    return not (
        "RSV-4821" in texto
        or "Marina Duarte" in texto
        or re.search(r"(?<!\d)302(?!\d)", texto)
    )


AREAS = {
    "salao-de-festas": "Salão de festas",
    "churrasqueira": "Churrasqueira",
    "quadra": "Quadra poliesportiva",
}
SALAO = {"area": "Salão de festas", "data": "2030-04-20"}
REQ = {"error": "This tool call requires confirmation, please approve or reject."}


def _parte_pedido(id_conf, acao, args, id_original) -> types.Part:
    return types.Part(
        function_call=types.FunctionCall(
            id=id_conf,
            name="adk_request_confirmation",
            args={
                "originalFunctionCall": {"id": id_original, "name": acao, "args": args},
                "toolConfirmation": {"hint": "", "confirmed": False},
            },
        )
    )


def ev_pedidos(pares: list[tuple], autor="especialista_reservas") -> Event:
    """Um evento com um adk_request_confirmation por (id_conf, acao, args, id_original)."""
    return Event(
        author=autor,
        content=types.Content(role="model", parts=[_parte_pedido(*p) for p in pares]),
        long_running_tool_ids={p[0] for p in pares},
    )


def ev_pedido(id_conf, acao, args, id_original, autor="especialista_reservas") -> Event:
    return ev_pedidos([(id_conf, acao, args, id_original)], autor=autor)


def ev_resposta_usuario(id_conf, confirmado) -> Event:
    return Event(
        author="user",
        content=types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=id_conf,
                        name="adk_request_confirmation",
                        response={"confirmed": confirmado},
                    )
                )
            ],
        ),
    )


def ev_resposta_tool(
    id_chamada,
    nome,
    resposta: dict,
    autor="especialista_reservas",
    skip=False,
    texto=None,
) -> Event:
    partes = [
        types.Part(
            function_response=types.FunctionResponse(
                id=id_chamada, name=nome, response=resposta
            )
        )
    ]
    if texto is not None:
        partes.append(types.Part(text=texto))
    return Event(
        author=autor,
        content=types.Content(role="user", parts=partes),
        actions=EventActions(skip_summarization=skip),
    )


def ev_texto(autor, texto, thought=False) -> Event:
    return Event(
        author=autor,
        content=types.Content(
            role="user" if autor == "user" else "model",
            parts=[types.Part(text=texto, thought=thought or None)],
        ),
    )
