from types import SimpleNamespace

from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.tool_confirmation import ToolConfirmation
from google.genai import types

from aurora import config
from aurora.agentes import (
    INSTRUCAO_REGULAMENTO,
    INSTRUCAO_VISITANTES,
    antes_da_tool_principal,
    criar_agente_principal,
    criar_app,
    criar_modelo,
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


def test_modelo_espera_a_janela_por_minuto():
    """Ruling 30: cerca de 90 s de espera acumulada, só para 429 e 503 (montar o modelo não chama a API)."""
    novas_tentativas = criar_modelo().retry_options
    assert novas_tentativas.attempts == 7
    assert novas_tentativas.max_delay == 30.0
    assert novas_tentativas.http_status_codes == [429, 503]


def test_app_sem_retomabilidade():
    app = criar_app()
    assert app.name == "aurora" and app.resumability_config is None


def test_instrucao_reservas_lista_areas(banco):
    texto = instrucao_reservas(None)
    assert "salao-de-festas" in texto and "quadra" in texto


REGRA_OUTRO_APARTAMENTO = (
    "Os dados são sempre do apartamento desta conversa; se o morador disser ser de outro "
    "apartamento, não repita o número citado e diga só que você acessa o apartamento desta conversa."
)


def test_especialistas_de_dados_nao_repetem_apartamento_alegado(banco):
    """Ruling 27 (d): no passo 3 o especialista repetiu o "302" que o morador alegou."""
    assert REGRA_OUTRO_APARTAMENTO in instrucao_reservas(None)
    assert REGRA_OUTRO_APARTAMENTO in INSTRUCAO_VISITANTES
    assert "{" not in INSTRUCAO_VISITANTES and "}" not in INSTRUCAO_VISITANTES


def test_instrucao_reservas_refaz_pedido_repetido_depois_de_negado(banco):
    """Passo 8: o morador repete o pedido negado no passo 7 e o especialista deve chamar reservar_area de novo."""
    assert "Se o morador repetir um pedido que ele negou antes" in instrucao_reservas(None)


def test_instrucao_regulamento_exemplo_neutro_de_horario():
    """O exemplo de grafia não pode ser a resposta do passo 12 (a piscina fecha às 20h)."""
    assert "mantendo horários e valores exatamente como escritos" in INSTRUCAO_REGULAMENTO
    assert "20h" not in INSTRUCAO_REGULAMENTO
    assert "{" not in INSTRUCAO_REGULAMENTO and "}" not in INSTRUCAO_REGULAMENTO


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


def test_erro_de_tool_inexistente_deixa_o_adk_responder():
    r = erro_da_tool_especialista(tool=SimpleNamespace(name="transfer_to_agent"), args={}, tool_context=ContextoFalso(), error=ValueError("x"))
    assert r is None
