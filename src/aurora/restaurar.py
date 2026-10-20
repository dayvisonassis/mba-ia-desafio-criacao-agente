"""Comando `uv run restaurar`: devolve o banco ao estado inicial dos dados."""

from contextlib import closing

from aurora import config
from aurora.banco import conectar, garantir_esquema, restaurar_dados


def main() -> None:
    config.carregar_ambiente()
    garantir_esquema()
    restaurar_dados()
    with closing(conectar()) as conexao:
        contagens = {
            tabela: conexao.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
            for tabela in ("apartamentos", "areas", "reservas", "visitantes")
        }
    print(f"Banco restaurado em {config.caminho_banco()}")
    print(", ".join(f"{n} {tabela}" for tabela, n in contagens.items()))
