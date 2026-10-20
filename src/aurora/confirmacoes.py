"""Pendências de confirmação e resposta, derivadas dos eventos da sessão.

Funções puras sobre listas de `Event`: nada aqui lê ou grava estado.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from google.adk.events import Event

from aurora.validacao import (
    ErroValidacao,
    chave_nome,
    validar_area,
    validar_data,
    validar_nome,
)

NOME_CONFIRMACAO = "adk_request_confirmation"
TEXTO_APROVE = "Para concluir, aprove a confirmação pendente."
TEXTO_AVISO_FALHA = (
    "Seu pedido foi registrado, mas não consegui concluir a resposta. "
    "Confira suas reservas e visitantes."
)
_STATUS_COM_EFEITO = {"criada", "cancelada", "autorizado"}


@dataclass(frozen=True)
class Pendente:
    id: str
    acao: str
    detalhes: dict[str, str]
    id_chamada_original: str


def _partes(evento: Event) -> list:
    content = evento.content
    return list(content.parts or []) if content is not None else []


def _respostas(evento: Event) -> Iterator:
    for parte in _partes(evento):
        if parte.function_response is not None:
            yield parte.function_response


def _dict(resposta: object) -> dict:
    return resposta if isinstance(resposta, dict) else {}


def _valido(validar, valor: object, *extra) -> str:
    try:
        return validar(valor, *extra)
    except ErroValidacao:
        return str(valor)


def _normalizar(acao: str, args: Mapping, areas: Mapping[str, str]) -> dict[str, str]:
    if acao == "reservar_area":
        return {
            "area": _valido(validar_area, args.get("area", ""), areas),
            "data": _valido(validar_data, args.get("data", "")),
        }
    if acao == "autorizar_visitante":
        return {
            "nome": _valido(validar_nome, args.get("nome", "")),
            "data": _valido(validar_data, args.get("data", "")),
        }
    return {str(k): str(v) for k, v in args.items()}


def _chave(p: Pendente) -> tuple:
    detalhes = {
        k: (chave_nome(v) if k == "nome" else v) for k, v in p.detalhes.items()
    }
    return p.acao, tuple(sorted(detalhes.items()))


def _candidatas(eventos: Sequence[Event], areas: Mapping[str, str]) -> list[Pendente]:
    candidatas = []
    for evento in eventos:
        for parte in _partes(evento):
            chamada = parte.function_call
            if chamada is None or chamada.name != NOME_CONFIRMACAO or not chamada.id:
                continue
            original = _dict(chamada.args).get("originalFunctionCall")
            if not isinstance(original, dict) or not original.get("name"):
                continue
            args = original.get("args")
            candidatas.append(
                Pendente(
                    id=chamada.id,
                    acao=str(original["name"]),
                    detalhes=_normalizar(
                        str(original["name"]), args if isinstance(args, dict) else {}, areas
                    ),
                    id_chamada_original=str(original.get("id") or ""),
                )
            )
    return candidatas


def listar_pendentes(eventos: Sequence[Event], areas: Mapping[str, str]) -> list[Pendente]:
    """Confirmações ainda sem resposta e não substituídas por uma mais nova igual."""
    candidatas = _candidatas(eventos, areas)
    respondidos = {r.id for e in eventos for r in _respostas(e) if r.id}
    guardadas: dict[tuple, Pendente] = {}
    for candidata in reversed(candidatas):
        guardadas.setdefault(_chave(candidata), candidata)
    mantidas = {id(p) for p in guardadas.values()}
    return [p for p in candidatas if id(p) in mantidas and p.id not in respondidos]


def encontrar_pendente(
    eventos: Sequence[Event], areas: Mapping[str, str], id: str
) -> Pendente | None:
    return next((p for p in listar_pendentes(eventos, areas) if p.id == id), None)


def acao_executada(eventos_emitidos: Sequence[Event], id_chamada_original: str) -> bool:
    """A tool respondeu à chamada original num evento que não é do usuário."""
    return any(
        r.id == id_chamada_original
        for e in eventos_emitidos
        if e.author != "user"
        for r in _respostas(e)
    )


def houve_efeito(eventos_emitidos: Sequence[Event]) -> bool:
    return any(
        _dict(r.response).get("status") in _STATUS_COM_EFEITO
        for e in eventos_emitidos
        if e.author != "user"
        for r in _respostas(e)
    )


def montar_resposta(eventos_emitidos: Sequence[Event], criou_pendente: bool) -> str:
    """Texto da resposta: texto dos eventos finais ou `mensagem` das tools."""
    pedacos: list[str] = []
    for evento in eventos_emitidos:
        if evento.author == "user" or not evento.is_final_response():
            continue
        textos = [p.text for p in _partes(evento) if p.text and not p.thought]
        if not textos:
            textos = [
                m
                for r in _respostas(evento)
                if "error" not in (corpo := _dict(r.response))
                and isinstance(m := corpo.get("mensagem"), str)
                and m
            ]
        for texto in textos:
            if not pedacos or pedacos[-1] != texto:
                pedacos.append(texto)
    resposta = "\n\n".join(pedacos)
    return resposta or (TEXTO_APROVE if criou_pendente else "")
