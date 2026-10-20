"""Apoio compartilhado pelos testes das tools e dos agentes."""

import json
import re
from types import SimpleNamespace

from google.adk.tools.function_tool import FunctionTool

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
