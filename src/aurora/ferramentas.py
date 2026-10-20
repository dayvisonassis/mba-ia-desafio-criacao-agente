"""Tools dos especialistas e funções que decidem se uma chamada pede confirmação.

Nenhuma tool recebe o apartamento: ele vem sempre do state da sessão.
"""

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from aurora import regulamento, repositorio
from aurora.validacao import ErroValidacao, validar_area, validar_data, validar_nome

CHAVE_PERGUNTA = "pergunta_regulamento"
REGISTRO_BUSCAS = regulamento.RegistroBuscas()


def apartamento_da_sessao(tool_context: ToolContext) -> str:
    apartamento = tool_context.state.get("apartamento")
    if not apartamento:
        raise RuntimeError("Sessão sem apartamento.")
    return str(apartamento)


def _chamada_id(tool_context: ToolContext) -> str:
    return f"{tool_context.session.id}:{tool_context.function_call_id}"


def _invalida(erro: ErroValidacao) -> dict:
    return {"status": "invalida", "mensagem": str(erro)}


def _aprovada(tool_context: ToolContext) -> bool:
    confirmacao = tool_context.tool_confirmation
    return confirmacao is not None and bool(confirmacao.confirmed)


def _real(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def precisa_confirmar_reserva(
    area: object = "", data: object = "", tool_context: object = None
) -> bool:
    """True só se o pedido é válido e a área tem taxa maior que zero. Nunca lança."""
    try:
        id_area = validar_area(area, repositorio.mapa_areas())
        validar_data(data)
        encontrada = repositorio.buscar_area(id_area)
        return encontrada is not None and encontrada.taxa > 0
    except Exception:
        return False


def precisa_confirmar_visitante(
    nome: object = "", data: object = "", tool_context: object = None
) -> bool:
    """True sempre que o nome e a data são válidos. Nunca lança."""
    try:
        validar_nome(nome)
        validar_data(data)
        return True
    except Exception:
        return False


def listar_minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do morador desta conversa (código, área e data)."""
    apartamento = apartamento_da_sessao(tool_context)
    return {
        "status": "ok",
        "reservas": [
            {"codigo": r.codigo, "area": r.area, "data": r.data}
            for r in repositorio.listar_reservas_ativas(apartamento)
        ],
    }


def verificar_disponibilidade(area: str, data: str, tool_context: ToolContext) -> dict:
    """Diz se uma área comum está livre numa data.

    Args:
        area: id ou nome da área (por exemplo, salao-de-festas ou "Salão de festas").
        data: data no formato AAAA-MM-DD.
    """
    apartamento_da_sessao(tool_context)
    try:
        id_area = validar_area(area, repositorio.mapa_areas())
        data = validar_data(data)
    except ErroValidacao as erro:
        return _invalida(erro)
    return {
        "status": "ok",
        "area": id_area,
        "data": data,
        "disponivel": repositorio.data_disponivel(id_area, data),
    }


def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict:
    """Reserva uma área comum para o morador desta conversa.

    A aprovação do morador acontece fora do chat, quando a área tem taxa. Chame esta
    ferramenta uma única vez por pedido e não repita a chamada por conta própria.

    Args:
        area: id ou nome da área (por exemplo, salao-de-festas ou "Salão de festas").
        data: data no formato AAAA-MM-DD.
    """
    apartamento = apartamento_da_sessao(tool_context)
    try:
        id_area = validar_area(area, repositorio.mapa_areas())
        data = validar_data(data)
    except ErroValidacao as erro:
        return _invalida(erro)
    dados_area = repositorio.buscar_area(id_area)
    if dados_area is None:
        return {"status": "invalida", "mensagem": "Área desconhecida."}
    if dados_area.taxa > 0 and not _aprovada(tool_context):
        return {
            "status": "nao_confirmada",
            "mensagem": "A reserva exige a aprovação do morador e nada foi gravado.",
        }
    try:
        reserva = repositorio.criar_reserva(
            apartamento, id_area, data, _chamada_id(tool_context)
        )
    except repositorio.DataOcupada:
        return {
            "status": "recusada",
            "motivo": "data_ocupada",
            "mensagem": f"{dados_area.nome} não está disponível em {data}.",
        }
    taxa = f" Taxa: {_real(dados_area.taxa)}." if dados_area.taxa > 0 else ""
    return {
        "status": "criada",
        "codigo": reserva.codigo,
        "area": id_area,
        "data": data,
        "taxa": dados_area.taxa,
        "mensagem": (
            f"Reserva {reserva.codigo} confirmada: {dados_area.nome} em {data}.{taxa}"
        ),
    }


def cancelar_reserva(area: str, data: str, tool_context: ToolContext) -> dict:
    """Cancela a reserva ativa do morador desta conversa numa área e data.

    Args:
        area: id ou nome da área (por exemplo, quadra ou "Salão de festas").
        data: data no formato AAAA-MM-DD.
    """
    apartamento = apartamento_da_sessao(tool_context)
    try:
        id_area = validar_area(area, repositorio.mapa_areas())
        data = validar_data(data)
    except ErroValidacao as erro:
        return _invalida(erro)
    reserva = repositorio.cancelar_reserva(apartamento, id_area, data)
    if reserva is None:
        return {
            "status": "nao_encontrada",
            "mensagem": "Não encontrei uma reserva sua para essa área e data.",
        }
    return {
        "status": "cancelada",
        "codigo": reserva.codigo,
        "area": id_area,
        "data": data,
        "mensagem": f"Reserva {reserva.codigo} cancelada.",
    }


def listar_meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista os visitantes autorizados pelo morador desta conversa (nome e data)."""
    apartamento = apartamento_da_sessao(tool_context)
    return {
        "status": "ok",
        "visitantes": [
            {"nome": v.nome, "data": v.data}
            for v in repositorio.listar_visitantes(apartamento)
        ],
    }


def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza a entrada de um visitante numa data.

    A aprovação do morador acontece fora do chat. Chame esta ferramenta uma única vez
    por pedido e não repita a chamada por conta própria.

    Args:
        nome: nome completo do visitante.
        data: data da visita no formato AAAA-MM-DD.
    """
    apartamento = apartamento_da_sessao(tool_context)
    try:
        nome_limpo = validar_nome(nome)
        data = validar_data(data)
    except ErroValidacao as erro:
        return _invalida(erro)
    if not _aprovada(tool_context):
        return {
            "status": "nao_confirmada",
            "mensagem": "A autorização exige a aprovação do morador e nada foi gravado.",
        }
    visitante = repositorio.autorizar_visitante(
        apartamento, nome_limpo, data, _chamada_id(tool_context)
    )
    return {
        "status": "autorizado",
        "nome": visitante.nome,
        "data": visitante.data,
        "mensagem": f"Visitante {visitante.nome} autorizado em {visitante.data}.",
    }


def buscar_no_regulamento(pergunta: str, tool_context: ToolContext) -> dict:
    """Busca no regulamento do condomínio os artigos de um capítulo sobre o assunto.

    Args:
        pergunta: a dúvida do morador, em português.
    """
    if not REGISTRO_BUSCAS.registrar(tool_context.session.id):
        return {
            "status": "erro",
            "mensagem": "Só é possível uma busca no regulamento por consulta.",
        }
    capitulo, artigos = regulamento.buscar(
        f"{pergunta} {tool_context.state.get(CHAVE_PERGUNTA, '')}"
    )
    return {"status": "ok", "capitulo": capitulo, "artigos": artigos}


FERRAMENTAS_RESERVAS: list[FunctionTool] = [
    FunctionTool(listar_minhas_reservas),
    FunctionTool(verificar_disponibilidade),
    FunctionTool(reservar_area, require_confirmation=precisa_confirmar_reserva),
    FunctionTool(cancelar_reserva),
]
FERRAMENTAS_VISITANTES: list[FunctionTool] = [
    FunctionTool(listar_meus_visitantes),
    FunctionTool(autorizar_visitante, require_confirmation=precisa_confirmar_visitante),
]
FERRAMENTA_REGULAMENTO = FunctionTool(buscar_no_regulamento)
