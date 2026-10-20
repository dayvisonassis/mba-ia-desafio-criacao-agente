import asyncio
import inspect
import re

import pytest
from google.adk.tools.tool_confirmation import ToolConfirmation

from aurora import repositorio
from aurora.ferramentas import (
    FERRAMENTA_REGULAMENTO,
    FERRAMENTAS_RESERVAS,
    FERRAMENTAS_VISITANTES,
    autorizar_visitante,
    buscar_no_regulamento,
    cancelar_reserva,
    listar_meus_visitantes,
    listar_minhas_reservas,
    precisa_confirmar_reserva,
    precisa_confirmar_visitante,
    reservar_area,
    verificar_disponibilidade,
)
from tests.apoio import ContextoFalso, ferramenta, sem_vazamento


def test_nenhuma_tool_recebe_apartamento():
    for t in FERRAMENTAS_RESERVAS + FERRAMENTAS_VISITANTES + [FERRAMENTA_REGULAMENTO]:
        assert "apartamento" not in inspect.signature(t.func).parameters


@pytest.mark.parametrize(
    "args,esperado",
    [
        ({"area": "salao-de-festas", "data": "2030-04-20"}, True),
        ({"area": "Salão de festas", "data": "2030-04-20"}, True),
        ({"area": "churrasqueira", "data": "2030-04-20"}, True),
        ({"area": "quadra", "data": "2030-04-06"}, False),
        ({"area": "salao-de-festas", "data": "20/04/2030"}, False),
        ({"area": "salao-de-festas"}, False),
        ({"area": "salao-de-festas", "data": 20300420}, False),
        ({"area": "piscina", "data": "2030-04-20"}, False),
    ],
)
def test_confirmacao_reserva_pelo_function_tool(banco, args, esperado):
    assert (
        asyncio.run(
            ferramenta("reservar_area").check_require_confirmation(
                args, ContextoFalso()
            )
        )
        is esperado
    )


@pytest.mark.parametrize(
    "args,esperado",
    [
        ({"nome": "Joana Ribeiro", "data": "2030-04-21"}, True),
        ({"nome": "  ", "data": "2030-04-21"}, False),
        ({"nome": "Joana", "data": "amanhã"}, False),
        ({"data": "2030-04-21"}, False),
    ],
)
def test_confirmacao_visitante_pelo_function_tool(banco, args, esperado):
    assert (
        asyncio.run(
            ferramenta("autorizar_visitante").check_require_confirmation(
                args, ContextoFalso()
            )
        )
        is esperado
    )


@pytest.mark.parametrize("valor", [None, 1, {}, [], object()])
def test_precisa_confirmar_nunca_lanca(banco, valor):
    assert precisa_confirmar_reserva(valor, valor, valor) is False
    assert precisa_confirmar_visitante(valor, valor, valor) is False
    assert precisa_confirmar_reserva() is False
    assert precisa_confirmar_visitante() is False


def test_quadra_grava_sem_confirmacao(banco):
    r = reservar_area("quadra", "2030-04-06", ContextoFalso())
    assert r["status"] == "criada" and re.fullmatch(r"RSV-N[A-Z]{8}", r["codigo"])


@pytest.mark.parametrize("conf", [None, ToolConfirmation(confirmed=False)])
def test_salao_sem_aprovacao_nao_grava(banco, conf):
    assert (
        reservar_area("salao-de-festas", "2030-04-20", ContextoFalso(confirmacao=conf))[
            "status"
        ]
        == "nao_confirmada"
    )
    assert repositorio.data_disponivel("salao-de-festas", "2030-04-20")


def test_salao_aprovado_grava_uma_vez(banco):
    ctx = ContextoFalso(confirmacao=ToolConfirmation(confirmed=True))
    assert (
        reservar_area("salao-de-festas", "2030-04-20", ctx)["codigo"]
        == reservar_area("salao-de-festas", "2030-04-20", ctx)["codigo"]
    )
    assert (
        sum(
            r.area == "salao-de-festas"
            for r in repositorio.listar_reservas_ativas("101")
        )
        == 1
    )


def test_data_ocupada_sem_vazar(banco):
    r = reservar_area(
        "salao-de-festas",
        "2030-03-16",
        ContextoFalso(confirmacao=ToolConfirmation(confirmed=True)),
    )
    assert (
        r["status"] == "recusada"
        and r["motivo"] == "data_ocupada"
        and sem_vazamento(r)
    )


def test_disponibilidade_sem_dono(banco):
    r = verificar_disponibilidade("salao-de-festas", "2030-03-16", ContextoFalso())
    assert r["disponivel"] is False and sem_vazamento(r)


def test_cancelar_de_outro_apartamento(banco):
    r = cancelar_reserva("salao-de-festas", "2030-03-16", ContextoFalso())
    assert r["status"] == "nao_encontrada" and sem_vazamento(r)


def test_cancelar_propria(banco):
    assert (
        cancelar_reserva("quadra", "2030-03-09", ContextoFalso())["codigo"]
        == "RSV-1377"
    )


def test_listar_so_do_apartamento(banco):
    assert listar_minhas_reservas(ContextoFalso())["reservas"] == [
        {"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}
    ]
    assert listar_meus_visitantes(ContextoFalso())["visitantes"] == []


def test_visitante_exige_aprovacao(banco):
    assert (
        autorizar_visitante("Joana Ribeiro", "2030-04-21", ContextoFalso())["status"]
        == "nao_confirmada"
    )
    assert (
        autorizar_visitante(
            "Joana Ribeiro",
            "2030-04-21",
            ContextoFalso(confirmacao=ToolConfirmation(confirmed=True)),
        )["status"]
        == "autorizado"
    )
    assert listar_meus_visitantes(ContextoFalso())["visitantes"] == [
        {"nome": "Joana Ribeiro", "data": "2030-04-21"}
    ]


@pytest.mark.parametrize("chamar", [
    lambda ctx: reservar_area("302", "2030-04-20", ctx),
    lambda ctx: verificar_disponibilidade("302", "2030-04-20", ctx),
    lambda ctx: cancelar_reserva("302", "2030-04-20", ctx),
])
def test_area_invalida_nao_repete_o_valor(banco, chamar):
    r = chamar(ContextoFalso())
    assert r["status"] == "invalida" and sem_vazamento(r)


def test_data_invalida(banco):
    assert (
        reservar_area("quadra", "20/04/2030", ContextoFalso())["status"] == "invalida"
    )


def test_sem_apartamento_na_sessao(banco):
    with pytest.raises(RuntimeError):
        reservar_area("quadra", "2030-04-06", ContextoFalso(state={}))


def test_regulamento_usa_pergunta_do_morador_e_limita(banco):
    ctx = ContextoFalso(
        session_id="filho-1",
        state={"pergunta_regulamento": "Até que horas a piscina funciona aos domingos?"},
    )
    r = buscar_no_regulamento("horário de funcionamento", ctx)
    assert r["capitulo"] == "Capítulo IV: Piscina" and "das 9h às 20h" in "\n".join(
        r["artigos"]
    )
    assert buscar_no_regulamento("piscina", ctx)["status"] == "erro"
