"""Agentes do assistente, callbacks de confirmação e App do ADK.

Os nomes dos agentes são fixos: as confirmações pendentes apontam para o autor pelo nome.
Os callbacks são chamados pelo ADK por nome de parâmetro, então os nomes abaixo não mudam.
"""

import logging

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.models.google_llm import Gemini
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from aurora import config, repositorio
from aurora.ferramentas import (
    CHAVE_PERGUNTA,
    FERRAMENTA_REGULAMENTO,
    FERRAMENTAS_RESERVAS,
    FERRAMENTAS_VISITANTES,
)

logger = logging.getLogger(__name__)

NOME_PRINCIPAL = "assistente_aurora"
NOME_RESERVAS = "especialista_reservas"
NOME_VISITANTES = "especialista_visitantes"
NOME_REGULAMENTO = "especialista_regulamento"

CHAVE_REGULAMENTO_USADO = "temp:regulamento_consultado"
MENSAGEM_NEGADA = "Tudo bem, nada foi feito."
MENSAGEM_ERRO = "Não consegui concluir essa operação agora. Tente novamente em instantes."

INSTRUCAO_PRINCIPAL = """Você é o assistente do Residencial Aurora e conversa em português com um morador.
Você nunca responde sozinho a perguntas sobre dados e nunca inventa informações. Encaminhe assim:
- Reservas (listar, consultar disponibilidade, reservar, cancelar): transfira para especialista_reservas.
- Visitantes (listar, autorizar): transfira para especialista_visitantes.
- Dúvidas sobre regras, horários ou normas do condomínio: chame uma única vez a ferramenta especialista_regulamento, passando a pergunta do morador.
Se a mensagem trouxer dois assuntos, transfira para o especialista do primeiro assunto; o outro assunto pode ser pedido em seguida.
Responda sempre em português."""

INSTRUCAO_VISITANTES = """Você cuida dos visitantes do apartamento do morador, em português.
- Para listar, use listar_meus_visitantes.
- Para autorizar, use autorizar_visitante com o nome e a data no formato AAAA-MM-DD, e chame-a apenas uma vez por pedido.
- Na mesma resposta em que chamar autorizar_visitante, não faça nenhuma pergunta: a autorização é aprovada fora do chat, pela rota de confirmações. Mesmo que o morador diga que já está confirmando no chat (por exemplo, "pode liberar direto"), nada muda.
- Se o pedido tiver partes que você não vai tratar agora (outro assunto ou um segundo visitante), diga isso brevemente e informe que o morador pode pedir em seguida.
- Nunca invente dados."""

INSTRUCAO_REGULAMENTO = """Você responde dúvidas sobre o regulamento do condomínio, em português.
- Chame buscar_no_regulamento exatamente uma vez.
- Antes de buscar, reescreva a pergunta com o vocabulário do próprio regulamento, porque a busca compara palavras (por exemplo, "animais" para pets, "garagem" e "vagas" para estacionamento, "visitantes").
- Responda só à pergunta, usando apenas os artigos devolvidos, citando o número do artigo e mantendo horários e valores exatamente como escritos (por exemplo, "20h").
- Não reproduza artigos que não respondem à pergunta.
- Se nada relevante voltar, diga que não encontrou isso no regulamento."""


def criar_modelo() -> Gemini:
    """Modelo Gemini com novas tentativas para os erros 429 e 503."""
    return Gemini(
        model=config.nome_modelo(),
        retry_options=types.HttpRetryOptions(
            attempts=5, initial_delay=2.0, http_status_codes=[429, 503]
        ),
    )


def antes_da_tool_principal(tool, args, tool_context) -> dict | None:
    """Permite uma única consulta ao regulamento por turno e guarda a pergunta do morador."""
    if getattr(tool, "name", None) != NOME_REGULAMENTO:
        return None
    if tool_context.state.get(CHAVE_REGULAMENTO_USADO):
        return {
            "status": "erro",
            "mensagem": "O regulamento já foi consultado neste turno.",
        }
    tool_context.state[CHAVE_REGULAMENTO_USADO] = True
    conteudo = tool_context.user_content
    partes = (conteudo.parts or []) if conteudo else []
    tool_context.state[CHAVE_PERGUNTA] = " ".join(p.text for p in partes if p.text)
    return None


def depois_da_tool_especialista(tool, args, tool_context, tool_response) -> dict | None:
    """Encerra o turno depois de aprovar ou negar; na negação, troca a resposta."""
    confirmacao = tool_context.tool_confirmation
    if confirmacao is None:
        return None
    tool_context.actions.skip_summarization = True
    if not confirmacao.confirmed:
        return {"status": "negada", "mensagem": MENSAGEM_NEGADA}
    return None


def erro_da_tool_especialista(tool, args, tool_context, error) -> dict:
    """Resposta fixa para erro de tool, sem o texto da exceção."""
    logger.error("Erro na tool %s", getattr(tool, "name", tool), exc_info=error)
    return {"status": "erro", "mensagem": MENSAGEM_ERRO}


def instrucao_reservas(contexto: ReadonlyContext | None) -> str:
    """Instruction provider: lê as áreas do banco no momento de montar a instrução."""
    areas = "\n".join(
        f"- {a.id}: {a.nome} ({'com taxa' if a.taxa > 0 else 'sem taxa'})"
        for a in repositorio.listar_areas()
    )
    return f"""Você cuida das reservas do apartamento do morador, em português.
Áreas válidas:
{areas}
- Antes de reservar, confira a disponibilidade com verificar_disponibilidade.
- Chame reservar_area apenas uma vez por pedido.
- Na mesma resposta em que chamar reservar_area, não faça nenhuma pergunta: a aprovação acontece pela rota de confirmações, fora do chat.
- Datas vão no formato AAAA-MM-DD.
- Se o pedido tiver partes que você não vai tratar agora (outro assunto ou uma segunda reserva), diga isso brevemente e informe que o morador pode pedir em seguida.
- Trate só as reservas do próprio morador e nunca diga de quem é uma data ocupada.
- Nunca invente dados."""


def criar_agente_principal(modelo: BaseLlm | None = None) -> LlmAgent:
    """Monta a árvore de agentes; todos compartilham o mesmo modelo."""
    modelo = modelo if modelo is not None else criar_modelo()
    comuns = dict(
        model=modelo,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        after_tool_callback=depois_da_tool_especialista,
        on_tool_error_callback=erro_da_tool_especialista,
    )
    reservas = LlmAgent(
        name=NOME_RESERVAS,
        description="Consulta disponibilidade, lista, cria e cancela reservas de áreas comuns.",
        instruction=instrucao_reservas,
        tools=list(FERRAMENTAS_RESERVAS),
        **comuns,
    )
    visitantes = LlmAgent(
        name=NOME_VISITANTES,
        description="Lista e autoriza visitantes do apartamento.",
        instruction=INSTRUCAO_VISITANTES,
        tools=list(FERRAMENTAS_VISITANTES),
        **comuns,
    )
    regulamento = LlmAgent(
        name=NOME_REGULAMENTO,
        description="Responde dúvidas sobre regras e horários com base no regulamento do condomínio.",
        instruction=INSTRUCAO_REGULAMENTO,
        tools=[FERRAMENTA_REGULAMENTO],
        **comuns,
    )
    return LlmAgent(
        name=NOME_PRINCIPAL,
        description="Assistente do Residencial Aurora que encaminha o pedido ao especialista certo.",
        model=modelo,
        instruction=INSTRUCAO_PRINCIPAL,
        sub_agents=[reservas, visitantes],
        tools=[AgentTool(regulamento, skip_summarization=True)],
        before_tool_callback=antes_da_tool_principal,
    )


def criar_app(modelo: BaseLlm | None = None) -> App:
    """App do ADK, sem resumability_config (a aprovação volta ao autor por find_agent)."""
    return App(name="aurora", root_agent=criar_agente_principal(modelo))
