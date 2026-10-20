import pytest
from fastapi.testclient import TestClient
from google.adk.sessions import InMemorySessionService

from aurora.api import criar_api
from aurora.confirmacoes import TEXTO_AVISO_FALHA
from tests.apoio import REQ, SALAO, RunnerFalso, ev_pedido, ev_resposta_tool


@pytest.fixture
def runner(banco):
    return RunnerFalso(InMemorySessionService())


@pytest.fixture
def cliente(runner):
    return TestClient(criar_api(runner=runner, session_service=runner.session_service))


def nova_sessao(cliente, apto="101") -> str:
    r = cliente.post("/sessoes", json={"apartamento": apto})
    assert r.status_code == 201
    return r.json()["session_id"]


def criar_pendencia(cliente, runner, sid):
    runner.roteiros.append(
        [
            ev_resposta_tool("o1", "reservar_area", REQ, skip=True),
            ev_pedido("c1", "reservar_area", SALAO, "o1"),
        ]
    )
    r = cliente.post(
        f"/sessoes/{sid}/mensagens",
        json={"texto": "Reserve o salão de festas para 2030-04-20."},
    )
    assert r.status_code == 200
    return r


def test_criar_sessao_e_eventos_vazios(cliente):
    r = cliente.post("/sessoes", json={"apartamento": "101"})
    assert r.status_code == 201
    assert cliente.get(f"/sessoes/{r.json()['session_id']}/eventos").json() == []


def test_entradas_malformadas(cliente, runner):
    assert cliente.post("/sessoes", json={"apartamento": "999"}).status_code == 422
    assert cliente.post("/sessoes", json={}).status_code == 422
    sid = nova_sessao(cliente)
    assert cliente.post(f"/sessoes/{sid}/mensagens", json={"texto": "   "}).status_code == 422
    assert cliente.post(f"/sessoes/{sid}/mensagens", json={}).status_code == 422
    assert runner.chamadas == 0


def test_sessao_inexistente_404(cliente):
    assert cliente.get("/sessoes/sessao-inexistente/eventos").status_code == 404
    assert cliente.post("/sessoes/x/mensagens", json={"texto": "oi"}).status_code == 404
    assert (
        cliente.post("/sessoes/x/confirmacoes", json={"id": "a", "confirmado": True}).status_code
        == 404
    )


def test_pendencia_aprovacao_e_reenvio(cliente, runner):
    sid = nova_sessao(cliente)
    runner.roteiros.append(
        [
            ev_resposta_tool("o1", "reservar_area", REQ, skip=True),
            ev_pedido("c1", "reservar_area", SALAO, "o1"),
        ]
    )
    r = cliente.post(
        f"/sessoes/{sid}/mensagens",
        json={"texto": "Reserve o salão de festas para 2030-04-20."},
    ).json()
    assert r == {
        "resposta": "Para concluir, aprove a confirmação pendente.",
        "confirmacoes_pendentes": [
            {
                "id": "c1",
                "acao": "reservar_area",
                "detalhes": {"area": "salao-de-festas", "data": "2030-04-20"},
            }
        ],
    }
    runner.roteiros.append(
        [
            ev_resposta_tool(
                "o1",
                "reservar_area",
                {"status": "criada", "mensagem": "Reserva confirmada."},
                skip=True,
            )
        ]
    )
    r = cliente.post(f"/sessoes/{sid}/confirmacoes", json={"id": "c1", "confirmado": True})
    assert r.status_code == 200
    assert r.json() == {"resposta": "Reserva confirmada.", "confirmacoes_pendentes": []}
    chamadas = runner.chamadas
    assert (
        cliente.post(f"/sessoes/{sid}/confirmacoes", json={"id": "c1", "confirmado": True}).status_code
        == 409
    )
    assert runner.chamadas == chamadas


def test_id_inexistente_409_sem_runner(cliente, runner):
    sid = nova_sessao(cliente)
    r = cliente.post(f"/sessoes/{sid}/confirmacoes", json={"id": "id-inexistente", "confirmado": True})
    assert r.status_code == 409
    assert runner.chamadas == 0


def test_aprovacao_que_nao_executa_vira_500(cliente, runner):
    sid = nova_sessao(cliente)
    criar_pendencia(cliente, runner, sid)
    runner.roteiros.append([])
    r = cliente.post(f"/sessoes/{sid}/confirmacoes", json={"id": "c1", "confirmado": True})
    assert r.status_code == 500


def test_falha_do_modelo_sem_efeito_503(cliente, runner):
    sid = nova_sessao(cliente)
    runner.roteiros.append([])
    runner.erro_depois = 0
    assert cliente.post(f"/sessoes/{sid}/mensagens", json={"texto": "oi"}).status_code == 503


def test_falha_do_modelo_com_efeito_200(cliente, runner):
    sid = nova_sessao(cliente)
    runner.roteiros.append(
        [ev_resposta_tool("o2", "reservar_area", {"status": "criada", "mensagem": "ok"})]
    )
    runner.erro_depois = 1
    r = cliente.post(
        f"/sessoes/{sid}/mensagens", json={"texto": "Reserve a quadra para 2030-04-06."}
    )
    assert r.status_code == 200
    assert r.json()["resposta"] == TEXTO_AVISO_FALHA


def test_rotas_de_verificacao(cliente):
    assert cliente.get("/apartamentos/101/reservas").json() == [
        {"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}
    ]
    assert cliente.get("/apartamentos/302/visitantes").json() == [
        {"nome": "Marina Duarte", "data": "2030-03-16"}
    ]
    assert cliente.get("/apartamentos/999/reservas").json() == []
    assert cliente.get("/apartamentos/999/visitantes").json() == []


def test_pendencia_de_outra_sessao_409(cliente, runner):
    s1 = nova_sessao(cliente)
    s2 = nova_sessao(cliente)
    criar_pendencia(cliente, runner, s1)
    chamadas = runner.chamadas
    r = cliente.post(f"/sessoes/{s2}/confirmacoes", json={"id": "c1", "confirmado": True})
    assert r.status_code == 409
    assert runner.chamadas == chamadas
    assert cliente.app.state.trava(s1) is cliente.app.state.trava(s1)
    assert cliente.app.state.trava(s1) is not cliente.app.state.trava(s2)
