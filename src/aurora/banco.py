"""Banco SQLite do condomínio: esquema, conexão e carga inicial."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime

from aurora import config

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS apartamentos (numero TEXT PRIMARY KEY, morador TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS areas (id TEXT PRIMARY KEY, nome TEXT NOT NULL, taxa REAL NOT NULL);
CREATE TABLE IF NOT EXISTS reservas (
  codigo       TEXT PRIMARY KEY,
  apartamento  TEXT NOT NULL REFERENCES apartamentos(numero),
  area         TEXT NOT NULL REFERENCES areas(id),
  data         TEXT NOT NULL,                       -- AAAA-MM-DD
  status       TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa','cancelada')),
  chamada_id   TEXT UNIQUE,                         -- "session_id:function_call_id" (NULL nas reservas iniciais)
  criada_em    TEXT NOT NULL,
  cancelada_em TEXT
);
-- Garantia 5: no máximo uma reserva ATIVA por área e data, valendo no instante da gravação.
CREATE UNIQUE INDEX IF NOT EXISTS ux_reserva_ativa_area_data ON reservas(area, data) WHERE status = 'ativa';
CREATE TABLE IF NOT EXISTS visitantes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  apartamento TEXT NOT NULL REFERENCES apartamentos(numero),
  nome        TEXT NOT NULL,
  data        TEXT NOT NULL,
  chamada_id  TEXT UNIQUE,
  criada_em   TEXT NOT NULL
);
-- Regra 5: todo código já usado, inclusive os iniciais. A restauração nunca apaga esta tabela.
CREATE TABLE IF NOT EXISTS codigos_emitidos (codigo TEXT PRIMARY KEY, emitido_em TEXT NOT NULL);
-- Liga o session_id ao apartamento (usado como user_id do ADK) para achar a sessão nas rotas.
CREATE TABLE IF NOT EXISTS sessoes (session_id TEXT PRIMARY KEY, apartamento TEXT NOT NULL, criada_em TEXT NOT NULL);
"""


def agora_iso() -> str:
    """Instante atual em ISO-8601 UTC."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def conectar() -> sqlite3.Connection:
    """Abre uma conexão nova; quem chama deve fechá-la."""
    conexao = sqlite3.connect(config.caminho_banco(), timeout=10, isolation_level=None)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys=ON")
    conexao.execute("PRAGMA journal_mode=WAL")
    return conexao


@contextmanager
def transacao() -> Iterator[sqlite3.Connection]:
    """Conexão com BEGIN IMMEDIATE: COMMIT ao sair, ROLLBACK em qualquer exceção."""
    with closing(conectar()) as conexao:
        conexao.execute("BEGIN IMMEDIATE")
        try:
            yield conexao
        except BaseException:
            conexao.execute("ROLLBACK")
            raise
        conexao.execute("COMMIT")


def garantir_esquema() -> None:
    config.dir_var().mkdir(parents=True, exist_ok=True)
    with closing(conectar()) as conexao:
        for comando in ESQUEMA_SQL.split(";"):
            if sqlite3.complete_statement(comando + ";") and any(
                linha.strip() and not linha.strip().startswith("--")
                for linha in comando.splitlines()
            ):
                conexao.execute(comando)


def _ler(nome: str) -> list[dict]:
    caminho = config.DIR_DADOS / nome
    return json.loads(caminho.read_text(encoding="utf-8"))


def restaurar_dados() -> None:
    """Recarrega os JSON de dados/ numa única transação (spec 8.4)."""
    agora = agora_iso()
    reservas = _ler("reservas.json")
    with transacao() as conexao:
        for tabela in ("reservas", "visitantes", "areas", "apartamentos"):
            conexao.execute(f"DELETE FROM {tabela}")
        conexao.executemany(
            "INSERT INTO apartamentos (numero, morador) VALUES (?, ?)",
            [(a["numero"], a["morador"]) for a in _ler("apartamentos.json")],
        )
        conexao.executemany(
            "INSERT INTO areas (id, nome, taxa) VALUES (?, ?, ?)",
            [(a["id"], a["nome"], a["taxa"]) for a in _ler("areas.json")],
        )
        conexao.executemany(
            "INSERT INTO reservas (codigo, apartamento, area, data, status, chamada_id, criada_em)"
            " VALUES (?, ?, ?, ?, 'ativa', NULL, ?)",
            [(r["codigo"], r["apartamento"], r["area"], r["data"], agora) for r in reservas],
        )
        conexao.executemany(
            "INSERT INTO visitantes (apartamento, nome, data, chamada_id, criada_em)"
            " VALUES (?, ?, ?, NULL, ?)",
            [(v["apartamento"], v["nome"], v["data"], agora) for v in _ler("visitantes.json")],
        )
        conexao.executemany(
            "INSERT OR IGNORE INTO codigos_emitidos (codigo, emitido_em) VALUES (?, ?)",
            [(r["codigo"], agora) for r in reservas],
        )


def _inicializado() -> bool:
    """Banco existente, com a tabela apartamentos e ao menos uma linha."""
    if not config.caminho_banco().exists():
        return False
    with closing(conectar()) as conexao:
        tabela = conexao.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'apartamentos'"
        ).fetchone()
        if tabela is None:
            return False
        return conexao.execute("SELECT 1 FROM apartamentos LIMIT 1").fetchone() is not None


def inicializar_se_necessario() -> None:
    """Carrega o banco se ele não existir ou ainda não tiver dados; nunca altera um populado."""
    if not _inicializado():
        garantir_esquema()
        restaurar_dados()
