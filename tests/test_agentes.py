from types import SimpleNamespace

from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.tool_confirmation import ToolConfirmation
from google.genai import types

from aurora import config
from aurora.agentes import (
    antes_da_tool_principal,
    criar_agente_principal,
    criar_app,
    depois_da_tool_especialista,
    erro_da_tool_especialista,
    instrucao_reservas,
)
from tests.apoio import ContextoFalso


def test_topologia():
    raiz = criar_agente_principal()
    assert raiz.name == "assistente_aurora"
    assert [a.name for a in raiz.sub_agents] == ["especialista_reservas", "especialista_visitantes"]
    assert all(e.disallow_transfer_to_parent and e.disallow_transfer_to_peers for e in raiz.sub_agents)
    [t] = raiz.tools
    assert isinstance(t, AgentTool) and t.agent.name == "especialista_regulamento" and t.skip_summarization


def test_tools_dos_especialistas():
    reservas, visitantes = criar_agente_principal().sub_agents
    assert {t.name for t in reservas.tools} == {"listar_minhas_reservas", "verificar_disponibilidade", "reservar_area", "cancelar_reserva"}
    assert {t.name for t in visitantes.tools} == {"listar_meus_visitantes", "autorizar_visitante"}


def test_principal_sem_regulamento_nas_instrucoes():
    texto = criar_agente_principal().instruction
    assert isinstance(texto, str) and "Capítulo" not in texto and "Art." not in texto
    for linha in (config.DIR_DADOS / "regulamento.md").read_text(encoding="utf-8").splitlines():
        if len(linha.strip()) > 30:
            assert linha.strip() not in texto


def test_app_sem_retomabilidade():
    app = criar_app()
    assert app.name == "aurora" and app.resumability_config is None


def test_instrucao_reservas_lista_areas(banco):
    texto = instrucao_reservas(None)
    assert "salao-de-festas" in texto and "quadra" in texto


def test_antes_da_tool_principal_uma_chamada_e_copia_pergunta():
    ctx = ContextoFalso(state={})
    ctx.user_content = types.Content(role="user", parts=[types.Part(text="Até que horas a piscina funciona aos domingos?")])
    reg = SimpleNamespace(name="especialista_regulamento")
    assert antes_da_tool_principal(tool=reg, args={"request": "x"}, tool_context=ctx) is None
    assert ctx.state["pergunta_regulamento"] == "Até que horas a piscina funciona aos domingos?"
    assert antes_da_tool_principal(tool=reg, args={}, tool_context=ctx)["status"] == "erro"
    assert antes_da_tool_principal(tool=SimpleNamespace(name="transfer_to_agent"), args={}, tool_context=ctx) is None


def test_depois_da_tool_negada():
    ctx = ContextoFalso(confirmacao=ToolConfirmation(confirmed=False))
    r = depois_da_tool_especialista(tool=None, args={}, tool_context=ctx, tool_response={"error": "This tool call is rejected."})
    assert r == {"status": "negada", "mensagem": "Tudo bem, nada foi feito."} and ctx.actions.skip_summarization


def test_depois_da_tool_aprovada():
    ctx = ContextoFalso(confirmacao=ToolConfirmation(confirmed=True))
    assert depois_da_tool_especialista(tool=None, args={}, tool_context=ctx, tool_response={"status": "criada"}) is None
    assert ctx.actions.skip_summarization


def test_depois_da_tool_sem_confirmacao():
    ctx = ContextoFalso()
    assert depois_da_tool_especialista(tool=None, args={}, tool_context=ctx, tool_response={"status": "ok"}) is None
    assert not ctx.actions.skip_summarization


def test_erro_da_tool_nao_vaza_excecao():
    r = erro_da_tool_especialista(tool=None, args={}, tool_context=ContextoFalso(), error=RuntimeError("segredo interno"))
    assert r["status"] == "erro" and "segredo" not in r["mensagem"]
