"""Gemini falso para a suíte de integração (D24): responde seguindo um roteiro.

Fica na fronteira do modelo. Runner, agentes, tools, callbacks e bancos são os reais.
"""

import itertools
from collections.abc import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field

_ids = itertools.count(1)


class RoteiroEsgotado(AssertionError):
    """O ADK chamou o modelo mais vezes do que o roteiro previa."""


class ModeloRoteirizado(BaseLlm):
    """Consome uma resposta do roteiro por chamada e registra quem chamou."""

    model: str = "modelo-roteirizado"
    fila: list[LlmResponse] = Field(default_factory=list)
    chamadas: list[set[str]] = Field(default_factory=list)
    """Por chamada, as tools visíveis: só o principal vê `especialista_regulamento`."""
    conteudos: list[list[types.Content]] = Field(default_factory=list)
    """Por chamada, uma cópia do histórico que o ADK mandou ao modelo."""

    def roteiro(self, *respostas: LlmResponse) -> None:
        self.fila.extend(respostas)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        visiveis = set(llm_request.tools_dict)
        self.chamadas.append(visiveis)
        self.conteudos.append([c.model_copy(deep=True) for c in llm_request.contents])
        if not self.fila:
            raise RoteiroEsgotado(
                f"O roteiro acabou na chamada {len(self.chamadas)} ao modelo; "
                f"tools visíveis para quem chamou: {sorted(visiveis)}"
            )
        # Cópia: o ADK não pode alterar a resposta guardada no roteiro.
        yield self.fila.pop(0).model_copy(deep=True)


def chamar(nome: str, /, **args) -> LlmResponse:
    """Resposta do modelo com uma única chamada de tool, de id único.

    `nome` é só posicional, para não colidir com o argumento `nome` de `autorizar_visitante`.
    """
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        id=f"call_{next(_ids)}", name=nome, args=args
                    )
                )
            ],
        )
    )


def responder(texto: str) -> LlmResponse:
    """Resposta do modelo só com texto."""
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=texto)])
    )
