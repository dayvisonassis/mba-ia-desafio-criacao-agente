import re
import threading

import pytest

from aurora import repositorio
from aurora.banco import garantir_esquema, inicializar_se_necessario, restaurar_dados
from aurora.repositorio import (
    ConflitoDeChamada,
    DataOcupada,
    Reserva,
    Visitante,
    apartamento_da_sessao_id,
    autorizar_visitante,
    buscar_area,
    cancelar_reserva,
    criar_reserva,
    data_disponivel,
    gerar_codigo,
    listar_areas,
    listar_reservas_ativas,
    listar_visitantes,
    registrar_sessao,
)


def test_restauracao_carrega_json(banco):
    assert listar_reservas_ativas("101") == [
        Reserva("RSV-1377", "101", "quadra", "2030-03-09", "ativa")
    ]
    assert listar_visitantes("302") == [Visitante("302", "Marina Duarte", "2030-03-16")]
    assert {a.id: a.taxa for a in listar_areas()} == {
        "salao-de-festas": 150.0,
        "churrasqueira": 80.0,
        "quadra": 0,
    }
    assert buscar_area("salao-de-festas").nome == "Salão de festas"  # UTF-8


def test_segunda_reserva_ativa_e_recusada(banco):
    with pytest.raises(DataOcupada):
        criar_reserva("101", "salao-de-festas", "2030-03-16", None)


def test_concorrencia_duas_threads(banco):
    barreira = threading.Barrier(2)
    resultados = []

    def tentar(apartamento):
        barreira.wait(timeout=10)
        try:
            criar_reserva(apartamento, "salao-de-festas", "2030-05-11", None)
            resultados.append("ok")
        except DataOcupada:
            resultados.append("ocupada")

    threads = [threading.Thread(target=tentar, args=(a,)) for a in ("101", "201")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    assert sorted(resultados) == ["ocupada", "ok"]
    assert (
        sum(
            r.data == "2030-05-11"
            for a in ("101", "201")
            for r in listar_reservas_ativas(a)
        )
        == 1
    )


def test_cancelada_libera_data(banco):
    assert cancelar_reserva("101", "quadra", "2030-03-09").codigo == "RSV-1377"
    assert listar_reservas_ativas("101") == []
    assert criar_reserva("201", "quadra", "2030-03-09", None).codigo != "RSV-1377"


def test_cancelar_de_outro_apartamento_nao_encontra(banco):
    assert cancelar_reserva("101", "salao-de-festas", "2030-03-16") is None
    assert [r.codigo for r in listar_reservas_ativas("302")] == ["RSV-4821"]


def test_mesma_chamada_nao_grava_de_novo(banco):
    a = criar_reserva("101", "salao-de-festas", "2030-04-20", "s1:c1")
    b = criar_reserva("101", "salao-de-festas", "2030-04-20", "s1:c1")
    assert a.codigo == b.codigo and len(listar_reservas_ativas("101")) == 2


def test_mesma_chamada_com_outros_dados_e_conflito(banco):
    criar_reserva("101", "salao-de-festas", "2030-04-20", "s1:c1")
    with pytest.raises(ConflitoDeChamada):
        criar_reserva("101", "churrasqueira", "2030-04-20", "s1:c1")


def test_formato_do_codigo():
    for _ in range(50):
        assert re.fullmatch(r"RSV-N[BCDFGHJKLMNPQRSTVWXZ]{8}", gerar_codigo())


def test_codigo_emitido_nunca_se_repete_mesmo_apos_restaurar(banco, monkeypatch):
    usado = criar_reserva("101", "churrasqueira", "2030-06-01", None).codigo
    restaurar_dados()
    seq = iter([usado, "RSV-NBBBBBBBB"])
    monkeypatch.setattr(repositorio, "gerar_codigo", lambda: next(seq))
    assert (
        criar_reserva("101", "churrasqueira", "2030-06-01", None).codigo
        == "RSV-NBBBBBBBB"
    )


def test_restauracao_preserva_sessoes_e_zera_reservas(banco):
    registrar_sessao("s1", "101")
    criar_reserva("101", "churrasqueira", "2030-06-01", None)
    restaurar_dados()
    assert apartamento_da_sessao_id("s1") == "101"
    assert [r.codigo for r in listar_reservas_ativas("101")] == ["RSV-1377"]


def test_visitante_idempotente(banco):
    autorizar_visitante("101", "Joana Ribeiro", "2030-04-21", "s1:c9")
    autorizar_visitante("101", "Joana Ribeiro", "2030-04-21", "s1:c9")
    assert listar_visitantes("101") == [Visitante("101", "Joana Ribeiro", "2030-04-21")]


def test_data_disponivel(banco):
    assert not data_disponivel("salao-de-festas", "2030-03-16")
    assert data_disponivel("salao-de-festas", "2030-04-20")


def test_inicializar_nao_apaga_banco_existente(tmp_path, monkeypatch):
    monkeypatch.setenv("AURORA_DIR_VAR", str(tmp_path))
    inicializar_se_necessario()
    criar_reserva("101", "churrasqueira", "2030-06-01", None)
    inicializar_se_necessario()
    assert len(listar_reservas_ativas("101")) == 2


def test_inicializar_recarrega_banco_sem_dados(tmp_path, monkeypatch):
    monkeypatch.setenv("AURORA_DIR_VAR", str(tmp_path))
    garantir_esquema()
    inicializar_se_necessario()
    assert [r.codigo for r in listar_reservas_ativas("101")] == ["RSV-1377"]
