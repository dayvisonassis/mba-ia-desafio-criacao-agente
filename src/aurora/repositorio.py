"""Acesso SQL aos dados do condomínio. Não valida entradas: as tools validam antes."""

import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass

from aurora.banco import agora_iso, conectar, transacao
from aurora.validacao import chave_nome

CONSOANTES = "BCDFGHJKLMNPQRSTVWXZ"
TENTATIVAS_CODIGO = 5


@dataclass(frozen=True)
class Area:
    id: str
    nome: str
    taxa: float


@dataclass(frozen=True)
class Reserva:
    codigo: str
    apartamento: str
    area: str
    data: str
    status: str


@dataclass(frozen=True)
class Visitante:
    apartamento: str
    nome: str
    data: str


class DataOcupada(Exception):
    """Já existe reserva ativa para a área nessa data."""


class ConflitoDeChamada(RuntimeError):
    """O mesmo chamada_id já gravou outros dados (erro de programação)."""


def _reserva(linha: sqlite3.Row) -> Reserva:
    return Reserva(
        linha["codigo"],
        linha["apartamento"],
        linha["area"],
        linha["data"],
        linha["status"],
    )


def listar_areas() -> list[Area]:
    with closing(conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT id, nome, taxa FROM areas ORDER BY rowid"
        ).fetchall()
    return [Area(l["id"], l["nome"], l["taxa"]) for l in linhas]


def mapa_areas() -> dict[str, str]:
    return {a.id: a.nome for a in listar_areas()}


def buscar_area(area_id: str) -> Area | None:
    with closing(conectar()) as conexao:
        linha = conexao.execute(
            "SELECT id, nome, taxa FROM areas WHERE id = ?", (area_id,)
        ).fetchone()
    return Area(linha["id"], linha["nome"], linha["taxa"]) if linha else None


def apartamento_existe(numero: str) -> bool:
    with closing(conectar()) as conexao:
        return (
            conexao.execute(
                "SELECT 1 FROM apartamentos WHERE numero = ?", (numero,)
            ).fetchone()
            is not None
        )


def listar_reservas_ativas(apartamento: str) -> list[Reserva]:
    with closing(conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT codigo, apartamento, area, data, status FROM reservas"
            " WHERE apartamento = ? AND status = 'ativa' ORDER BY data, codigo",
            (apartamento,),
        ).fetchall()
    return [_reserva(l) for l in linhas]


def data_disponivel(area: str, data: str) -> bool:
    with closing(conectar()) as conexao:
        return (
            conexao.execute(
                "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND status = 'ativa'",
                (area, data),
            ).fetchone()
            is None
        )


def gerar_codigo() -> str:
    return "RSV-N" + "".join(secrets.choice(CONSOANTES) for _ in range(8))


def criar_reserva(
    apartamento: str, area: str, data: str, chamada_id: str | None
) -> Reserva:
    with transacao() as conexao:
        if chamada_id is not None:
            existente = conexao.execute(
                "SELECT codigo, apartamento, area, data, status FROM reservas"
                " WHERE chamada_id = ?",
                (chamada_id,),
            ).fetchone()
            if existente:
                mesmos = (existente["apartamento"], existente["area"], existente["data"])
                if mesmos == (apartamento, area, data):
                    return _reserva(existente)
                raise ConflitoDeChamada(
                    f"chamada_id {chamada_id!r} já gravou outra reserva."
                )
        agora = agora_iso()
        for tentativa in range(TENTATIVAS_CODIGO):
            codigo = gerar_codigo()
            try:
                conexao.execute(
                    "INSERT INTO codigos_emitidos (codigo, emitido_em) VALUES (?, ?)",
                    (codigo, agora),
                )
                conexao.execute(
                    "INSERT INTO reservas (codigo, apartamento, area, data, status,"
                    " chamada_id, criada_em) VALUES (?, ?, ?, ?, 'ativa', ?, ?)",
                    (codigo, apartamento, area, data, chamada_id, agora),
                )
            except sqlite3.IntegrityError as erro:
                mensagem = str(erro)
                if "reservas.area, reservas.data" in mensagem:
                    raise DataOcupada(f"{area} já está reservada em {data}.") from erro
                if (
                    "codigos_emitidos.codigo" in mensagem
                    and tentativa < TENTATIVAS_CODIGO - 1
                ):
                    continue
                raise
            return Reserva(codigo, apartamento, area, data, "ativa")
    raise AssertionError("inalcançável")


def cancelar_reserva(apartamento: str, area: str, data: str) -> Reserva | None:
    with transacao() as conexao:
        linha = conexao.execute(
            "SELECT codigo, apartamento, area, data, status FROM reservas"
            " WHERE apartamento = ? AND area = ? AND data = ? AND status = 'ativa'",
            (apartamento, area, data),
        ).fetchone()
        if linha is None:
            return None
        conexao.execute(
            "UPDATE reservas SET status = 'cancelada', cancelada_em = ? WHERE codigo = ?",
            (agora_iso(), linha["codigo"]),
        )
        return Reserva(
            linha["codigo"],
            linha["apartamento"],
            linha["area"],
            linha["data"],
            "cancelada",
        )


def listar_visitantes(apartamento: str) -> list[Visitante]:
    with closing(conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT apartamento, nome, data FROM visitantes"
            " WHERE apartamento = ? ORDER BY data, id",
            (apartamento,),
        ).fetchall()
    return [Visitante(l["apartamento"], l["nome"], l["data"]) for l in linhas]


def autorizar_visitante(
    apartamento: str, nome: str, data: str, chamada_id: str | None
) -> Visitante:
    with transacao() as conexao:
        if chamada_id is not None:
            existente = conexao.execute(
                "SELECT apartamento, nome, data FROM visitantes WHERE chamada_id = ?",
                (chamada_id,),
            ).fetchone()
            if existente:
                mesmos = (
                    existente["apartamento"],
                    chave_nome(existente["nome"]),
                    existente["data"],
                )
                if mesmos == (apartamento, chave_nome(nome), data):
                    return Visitante(
                        existente["apartamento"], existente["nome"], existente["data"]
                    )
                raise ConflitoDeChamada(
                    f"chamada_id {chamada_id!r} já gravou outro visitante."
                )
        conexao.execute(
            "INSERT INTO visitantes (apartamento, nome, data, chamada_id, criada_em)"
            " VALUES (?, ?, ?, ?, ?)",
            (apartamento, nome, data, chamada_id, agora_iso()),
        )
    return Visitante(apartamento, nome, data)


def registrar_sessao(session_id: str, apartamento: str) -> None:
    with transacao() as conexao:
        conexao.execute(
            "INSERT OR REPLACE INTO sessoes (session_id, apartamento, criada_em)"
            " VALUES (?, ?, ?)",
            (session_id, apartamento, agora_iso()),
        )


def apartamento_da_sessao_id(session_id: str) -> str | None:
    with closing(conectar()) as conexao:
        linha = conexao.execute(
            "SELECT apartamento FROM sessoes WHERE session_id = ?", (session_id,)
        ).fetchone()
    return linha["apartamento"] if linha else None
