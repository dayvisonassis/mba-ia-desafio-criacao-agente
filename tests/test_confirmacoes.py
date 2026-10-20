"""Testes das pendências derivadas dos eventos e da montagem da resposta."""

from aurora.confirmacoes import (
    TEXTO_APROVE,
    Pendente,
    acao_executada,
    encontrar_pendente,
    houve_efeito,
    listar_pendentes,
    montar_resposta,
)
from tests.apoio import (
    AREAS,
    REQ,
    SALAO,
    ev_pedido,
    ev_pedidos,
    ev_resposta_tool,
    ev_resposta_usuario,
    ev_texto,
)


def test_pendente_simples():
    assert listar_pendentes([ev_pedido("c1", "reservar_area", SALAO, "o1")], AREAS) == [
        Pendente("c1", "reservar_area", {"area": "salao-de-festas", "data": "2030-04-20"}, "o1")
    ]


def test_respondida_pelo_usuario_some():
    evs = [ev_pedido("c1", "reservar_area", SALAO, "o1"), ev_resposta_usuario("c1", False)]
    assert listar_pendentes(evs, AREAS) == []


def test_encerrada_por_outro_autor_some():
    evs = [
        ev_pedido("c1", "reservar_area", SALAO, "o1"),
        ev_resposta_tool("c1", "adk_request_confirmation", {"aborted": True}),
    ]
    assert listar_pendentes(evs, AREAS) == []


def test_substituida_por_duplicata_mais_nova():
    evs = [
        ev_pedido("c1", "reservar_area", SALAO, "o1"),
        ev_pedido("c2", "reservar_area", {"area": "salao-de-festas", "data": "2030-04-20"}, "o2"),
    ]
    assert [p.id for p in listar_pendentes(evs, AREAS)] == ["c2"]
    assert encontrar_pendente(evs, AREAS, "c1") is None


def test_duplicata_com_nome_em_outra_caixa_e_substituida():
    evs = [
        ev_pedido("c1", "autorizar_visitante", {"nome": "Joana Ribeiro", "data": "2030-04-21"}, "o1", autor="especialista_visitantes"),
        ev_pedido("c2", "autorizar_visitante", {"nome": "joana  RIBEIRO", "data": "2030-04-21"}, "o2", autor="especialista_visitantes"),
    ]
    assert [p.id for p in listar_pendentes(evs, AREAS)] == ["c2"]


def test_duplicatas_no_mesmo_evento():
    ev = ev_pedidos([("c1", "reservar_area", SALAO, "o1"), ("c2", "reservar_area", SALAO, "o2")])
    assert [p.id for p in listar_pendentes([ev], AREAS)] == ["c2"]


def test_diferentes_no_mesmo_evento_continuam():
    ev = ev_pedidos([
        ("c1", "reservar_area", SALAO, "o1"),
        ("c2", "reservar_area", {"area": "churrasqueira", "data": "2030-06-02"}, "o2"),
    ])
    assert [p.id for p in listar_pendentes([ev], AREAS)] == ["c1", "c2"]


def test_nova_mensagem_nao_expira():
    evs = [ev_pedido("c1", "reservar_area", SALAO, "o1"), ev_texto("user", "outra coisa")]
    assert [p.id for p in listar_pendentes(evs, AREAS)] == ["c1"]


def test_ordem_invertida_apos_recarga():
    a = ev_resposta_tool("o1", "reservar_area", REQ, skip=True)
    b = ev_pedido("c1", "reservar_area", SALAO, "o1")
    assert [p.id for p in listar_pendentes([a, b], AREAS)] == ["c1"] == [
        p.id for p in listar_pendentes([b, a], AREAS)
    ]


def test_negada_e_repetida_lista_so_a_nova():  # passos 7 -> 8
    evs = [
        ev_pedido("c1", "reservar_area", SALAO, "o1"),
        ev_resposta_usuario("c1", False),
        ev_pedido("c2", "reservar_area", SALAO, "o2"),
    ]
    assert [p.id for p in listar_pendentes(evs, AREAS)] == ["c2"]


def test_dois_pedidos_num_evento_e_uma_resposta_requer_confirmacao():
    pedidos = ev_pedidos([
        ("c1", "reservar_area", SALAO, "o1"),
        ("c2", "reservar_area", {"area": "churrasqueira", "data": "2030-06-02"}, "o2"),
    ])
    reqs = ev_resposta_tool("o1", "reservar_area", REQ, skip=True)
    reqs.content.parts.append(ev_resposta_tool("o2", "reservar_area", REQ).content.parts[0])
    assert [p.id for p in listar_pendentes([pedidos, reqs], AREAS)] == ["c1", "c2"]


def test_candidata_sem_chamada_original_e_ignorada():
    quebrado = ev_pedido("c1", "reservar_area", SALAO, "o1")
    del quebrado.content.parts[0].function_call.args["originalFunctionCall"]
    evs = [quebrado, ev_pedido("c2", "reservar_area", SALAO, "o2")]
    assert [p.id for p in listar_pendentes(evs, AREAS)] == ["c2"]


def test_acao_executada():
    feito = ev_resposta_tool("o1", "reservar_area", {"status": "criada", "mensagem": "ok"}, skip=True)
    assert acao_executada([feito], "o1") and not acao_executada([], "o1")
    assert not acao_executada([ev_resposta_usuario("c1", True)], "o1")


def test_houve_efeito():
    assert houve_efeito([ev_resposta_tool("o1", "reservar_area", {"status": "criada"})])
    assert not houve_efeito([ev_resposta_tool("o1", "reservar_area", {"status": "nao_confirmada"})])


def test_montar_resposta_texto():
    assert montar_resposta([ev_texto("especialista_reservas", "Reserva feita.")], False) == "Reserva feita."


def test_montar_resposta_usa_mensagem_da_tool():
    ev = ev_resposta_tool("o1", "reservar_area", {"status": "criada", "mensagem": "Reserva confirmada."}, skip=True)
    assert montar_resposta([ev], False) == "Reserva confirmada."


def test_montar_resposta_regulamento_sem_duplicar():
    ev = ev_resposta_tool("o9", "especialista_regulamento", {"result": "Fecha às 20h."}, autor="assistente_aurora", skip=True, texto="Fecha às 20h.")
    assert montar_resposta([ev], False) == "Fecha às 20h."


def test_montar_resposta_pendente_usa_texto_fixo():
    evs = [ev_resposta_tool("o1", "reservar_area", REQ, skip=True), ev_pedido("c1", "reservar_area", SALAO, "o1")]
    assert montar_resposta(evs, True) == TEXTO_APROVE == "Para concluir, aprove a confirmação pendente."


def test_montar_resposta_vazia_e_pensamento():
    assert montar_resposta([], False) == ""
    assert montar_resposta([ev_texto("especialista_reservas", "rascunho", thought=True)], False) == ""
