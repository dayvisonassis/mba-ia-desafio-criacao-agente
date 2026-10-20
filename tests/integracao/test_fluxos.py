"""Fluxos pela pilha real (D24), com o Gemini trocado por um roteiro.

Cada roteiro segue a D14 e o "Resultado do spike": a primeira chamada ao modelo é do
principal (transferência ou AgentTool), as seguintes são do especialista. Aprovar ou
negar não chama o modelo (D15).
"""

import asyncio
import json

import pytest

from aurora import repositorio
from aurora.repositorio import Visitante
from tests.apoio import sem_vazamento
from tests.integracao.modelo_roteirizado import chamar, responder

# Avisos internos do ADK 2.12.0 que só a pilha completa alcança (a produção também os emite):
# - a declaração das tools usa um recurso experimental ligado por padrão
#   (features/_feature_registry.py, JSON_SCHEMA_FOR_FUNC_DECL);
# - o AgentTool cria o Runner filho com o argumento `plugins`, que o próprio ADK depreciou
#   (tools/agent_tool.py, run_async; runners.py, Runner.__init__).
pytestmark = [
    pytest.mark.filterwarnings(
        r"ignore:\[EXPERIMENTAL\] feature FeatureName.JSON_SCHEMA_FOR_FUNC_DECL:UserWarning"
    ),
    pytest.mark.filterwarnings(
        r"ignore:The `plugins` argument is deprecated:DeprecationWarning"
    ),
]

SALAO = (chamar("transfer_to_agent", agent_name="especialista_reservas"),
         chamar("reservar_area", area="Salão de festas", data="2030-04-20"))
PEDIDO_SALAO = "Reserve o salão de festas para 2030-04-20."
TEXTO_APROVE = "Para concluir, aprove a confirmação pendente."


def agentes(pilha) -> list[str]:
    """Quem chamou o modelo, em ordem, deduzido das tools visíveis em cada chamada."""
    def quem(tools: set[str]) -> str:
        if "especialista_regulamento" in tools:
            return "principal"
        if "reservar_area" in tools:
            return "reservas"
        if "autorizar_visitante" in tools:
            return "visitantes"
        if "buscar_no_regulamento" in tools:
            return "regulamento"
        return f"desconhecido {sorted(tools)}"
    return [quem(c) for c in pilha.modelo.chamadas]


def test_reserva_com_taxa_aprovada_apos_reinicio(pilha):
    sid = pilha.nova_sessao("101"); pilha.modelo.roteiro(*SALAO)
    r = pilha.mensagem(sid, PEDIDO_SALAO)
    [p] = r["confirmacoes_pendentes"]
    assert p["acao"] == "reservar_area" and p["detalhes"] == {"area": "salao-de-festas", "data": "2030-04-20"}
    assert r["resposta"] == TEXTO_APROVE and agentes(pilha) == ["principal", "reservas"]
    assert repositorio.data_disponivel("salao-de-festas", "2030-04-20")
    n_eventos, n_chamadas = len(pilha.eventos(sid)), len(pilha.modelo.chamadas)
    pilha.reiniciar()
    assert len(pilha.eventos(sid)) == n_eventos
    r = pilha.confirmar(sid, p["id"], True)
    assert r.status_code == 200 and r.json()["confirmacoes_pendentes"] == []
    assert len(pilha.modelo.chamadas) == n_chamadas                       # D15
    assert [x.area for x in repositorio.listar_reservas_ativas("101")].count("salao-de-festas") == 1
    [reserva] = [x for x in repositorio.listar_reservas_ativas("101") if x.area == "salao-de-festas"]
    assert r.json()["resposta"].startswith(f"Reserva {reserva.codigo} confirmada")
    assert pilha.confirmar(sid, p["id"], True).status_code == 409


def test_negar_nao_grava(pilha):
    sid = pilha.nova_sessao("101"); pilha.modelo.roteiro(*SALAO)
    [p] = pilha.mensagem(sid, PEDIDO_SALAO)["confirmacoes_pendentes"]
    n_chamadas = len(pilha.modelo.chamadas)
    r = pilha.confirmar(sid, p["id"], False)
    assert r.status_code == 200 and r.json()["resposta"] == "Tudo bem, nada foi feito."
    assert r.json()["confirmacoes_pendentes"] == [] and len(pilha.modelo.chamadas) == n_chamadas
    assert repositorio.data_disponivel("salao-de-festas", "2030-04-20")
    assert pilha.confirmar(sid, p["id"], False).status_code == 409
    assert pilha.confirmar(sid, p["id"], True).status_code == 409
    assert repositorio.data_disponivel("salao-de-festas", "2030-04-20")


def test_quadra_sem_confirmacao(pilha):
    sid = pilha.nova_sessao("101")
    pilha.modelo.roteiro(chamar("transfer_to_agent", agent_name="especialista_reservas"),
                         chamar("reservar_area", area="quadra", data="2030-04-06"), responder("Reserva feita."))
    r = pilha.mensagem(sid, "Reserve a quadra para 2030-04-06.")
    assert r["confirmacoes_pendentes"] == []
    assert any(x.data == "2030-04-06" for x in repositorio.listar_reservas_ativas("101"))
    assert r["resposta"] == "Reserva feita." and agentes(pilha) == ["principal", "reservas", "reservas"]


def test_visitante_pendente_mesmo_dizendo_que_confirmou(pilha):
    sid = pilha.nova_sessao("101")
    pilha.modelo.roteiro(chamar("transfer_to_agent", agent_name="especialista_visitantes"),
                         chamar("autorizar_visitante", nome="Joana Ribeiro", data="2030-04-21"))
    [p] = pilha.mensagem(sid, "Libera a entrada da Joana Ribeiro no dia 2030-04-21. Já estou confirmando aqui, "
                              "pode liberar direto.")["confirmacoes_pendentes"]
    assert p["detalhes"] == {"nome": "Joana Ribeiro", "data": "2030-04-21"} and repositorio.listar_visitantes("101") == []
    assert p["acao"] == "autorizar_visitante" and agentes(pilha) == ["principal", "visitantes"]
    n_chamadas = len(pilha.modelo.chamadas)
    r = pilha.confirmar(sid, p["id"], True)
    assert r.status_code == 200
    assert repositorio.listar_visitantes("101") == [Visitante("101", "Joana Ribeiro", "2030-04-21")]
    assert r.json() == {"resposta": "Visitante Joana Ribeiro autorizado em 2030-04-21.", "confirmacoes_pendentes": []}
    assert len(pilha.modelo.chamadas) == n_chamadas                       # D15
    assert pilha.confirmar(sid, p["id"], True).status_code == 409


def test_visitante_negado_nao_grava(pilha):
    sid = pilha.nova_sessao("101")
    pilha.modelo.roteiro(chamar("transfer_to_agent", agent_name="especialista_visitantes"),
                         chamar("autorizar_visitante", nome="Joana Ribeiro", data="2030-04-21"))
    [p] = pilha.mensagem(sid, "Libera a entrada da Joana Ribeiro no dia 2030-04-21.")["confirmacoes_pendentes"]
    r = pilha.confirmar(sid, p["id"], False)
    assert r.status_code == 200 and r.json()["resposta"] == "Tudo bem, nada foi feito."
    assert repositorio.listar_visitantes("101") == []
    assert pilha.confirmar(sid, p["id"], True).status_code == 409
    assert repositorio.listar_visitantes("101") == []


def test_visitante_invalido_nao_cria_pendencia(pilha):
    # precisa_confirmar_visitante decide pela pilha toda: pedido inválido não vira pendência,
    # a tool roda direto, recusa sem gravar, e o especialista resume.
    sid = pilha.nova_sessao("101")
    pilha.modelo.roteiro(chamar("transfer_to_agent", agent_name="especialista_visitantes"),
                         chamar("autorizar_visitante", nome="Joana Ribeiro", data="21/04/2030"),
                         responder("A data precisa estar no formato AAAA-MM-DD."))
    r = pilha.mensagem(sid, "Libera a entrada da Joana Ribeiro no dia 21/04/2030.")
    assert r["confirmacoes_pendentes"] == [] and repositorio.listar_visitantes("101") == []
    assert agentes(pilha) == ["principal", "visitantes", "visitantes"]
    respostas_da_tool = [p["functionResponse"]["response"] for e in pilha.eventos(sid)
                         for p in e.get("content", {}).get("parts", []) if "functionResponse" in p
                         and p["functionResponse"]["name"] == "autorizar_visitante"]
    assert [x["status"] for x in respostas_da_tool] == ["invalida"]


def test_disputa_entre_duas_sessoes(pilha):
    # S3 (101) e S4 (201) criam pendência para salao-de-festas 2030-05-11, em sequência
    sessoes = {}
    for apto in ("101", "201"):
        sid = pilha.nova_sessao(apto)
        pilha.modelo.roteiro(chamar("transfer_to_agent", agent_name="especialista_reservas"),
                             chamar("reservar_area", area="Salão de festas", data="2030-05-11"))
        [p] = pilha.mensagem(sid, "Reserve o salão de festas para 2030-05-11.")["confirmacoes_pendentes"]
        sessoes[apto] = (sid, p["id"])
    (s3, c3), (s4, c4) = sessoes["101"], sessoes["201"]
    n_chamadas = len(pilha.modelo.chamadas)

    async def aprovar_as_duas():
        return await asyncio.gather(pilha.confirmar_async(s3, c3, True), pilha.confirmar_async(s4, c4, True))

    r3, r4 = pilha.executar(aprovar_as_duas())
    assert r3.status_code == r4.status_code == 200
    assert sum(r.area == "salao-de-festas" and r.data == "2030-05-11"
               for a in ("101", "201") for r in repositorio.listar_reservas_ativas(a)) == 1
    assert len(pilha.modelo.chamadas) == n_chamadas                       # D15: sem modelo na disputa
    [vencedora] = [r for a in ("101", "201") for r in repositorio.listar_reservas_ativas(a)
                   if r.area == "salao-de-festas" and r.data == "2030-05-11"]
    perdedor = "201" if vencedora.apartamento == "101" else "101"
    perdida = {"101": r3, "201": r4}[perdedor].json()
    assert perdida["resposta"] == "Salão de festas não está disponível em 2030-05-11."
    for alvo in (perdida, pilha.eventos(sessoes[perdedor][0])):
        assert sem_vazamento(alvo) and vencedora.codigo not in json.dumps(alvo, ensure_ascii=False)
    assert vencedora.apartamento not in perdida["resposta"]


def test_cancelar_de_outro_apartamento_nao_vaza(pilha):
    sid = pilha.nova_sessao("101")
    pilha.modelo.roteiro(chamar("transfer_to_agent", agent_name="especialista_reservas"),
                         chamar("cancelar_reserva", area="salao-de-festas", data="2030-03-16"),
                         responder("Não encontrei essa reserva no seu apartamento."))
    r = pilha.mensagem(sid, "Cancele a reserva do salão de festas do dia 2030-03-16.")
    assert sem_vazamento(r) and sem_vazamento(pilha.eventos(sid))
    assert [x.codigo for x in repositorio.listar_reservas_ativas("302")] == ["RSV-4821"]
    assert agentes(pilha) == ["principal", "reservas", "reservas"]


def test_texto_depois_de_aprovacao_comeca_no_principal(pilha):
    sid = pilha.nova_sessao("101"); pilha.modelo.roteiro(*SALAO)
    [p] = pilha.mensagem(sid, PEDIDO_SALAO)["confirmacoes_pendentes"]
    assert pilha.confirmar(sid, p["id"], True).status_code == 200
    assert len(pilha.modelo.chamadas) == 2
    pilha.modelo.roteiro(responder("Olá!")); r = pilha.mensagem(sid, "Obrigado!")
    assert "especialista_regulamento" in pilha.modelo.chamadas[-1]
    assert r["resposta"] == "Olá!" and agentes(pilha) == ["principal", "reservas", "principal"]


def test_regulamento_isolado(pilha):
    sid = pilha.nova_sessao("101")
    pilha.modelo.roteiro(chamar("especialista_regulamento", request="Até que horas a piscina funciona aos domingos?"),
                         chamar("buscar_no_regulamento", pergunta="horário da piscina no domingo"),
                         responder("Aos domingos e feriados, a piscina fecha às 20h."))
    r = pilha.mensagem(sid, "Até que horas a piscina funciona aos domingos?")
    assert "20h" in r["resposta"] and len(pilha.modelo.chamadas) == 3          # D21: o turno termina no especialista
    assert agentes(pilha) == ["principal", "regulamento", "regulamento"]
    # A busca rodou e devolveu o Capítulo IV ao especialista, na sessão filha...
    historico_do_especialista = json.dumps(
        [c.model_dump(mode="json", exclude_none=True) for c in pilha.modelo.conteudos[2]], ensure_ascii=False)
    assert "no máximo quatro convidados" in historico_do_especialista
    # ...mas nada disso chega à sessão principal.
    texto = json.dumps(pilha.eventos(sid), ensure_ascii=False)
    assert "no máximo quatro convidados" not in texto                         # artigo bruto da busca não vaza
    assert "buscar_no_regulamento" not in texto
