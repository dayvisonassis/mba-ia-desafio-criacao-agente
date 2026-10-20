"""Validação e normalização compartilhadas por banco, tools e API."""

import re
import unicodedata
from collections.abc import Mapping
from datetime import date


class ErroValidacao(ValueError):
    pass


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sem acentos, espaços colapsados e sem pontas."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.lower().split())


def validar_data(valor: object) -> str:
    if not isinstance(valor, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        raise ErroValidacao("Data inválida: use o formato AAAA-MM-DD.")
    try:
        date.fromisoformat(valor)
    except ValueError:
        raise ErroValidacao("Data inválida: essa data não existe.") from None
    return valor


def validar_area(valor: object, areas: Mapping[str, str]) -> str:
    """Devolve o id da área; casa pelo id ou pelo nome, sem caixa nem acento."""
    if not isinstance(valor, str):
        raise ErroValidacao("Área inválida.")
    procurado = normalizar_texto(valor).replace("-", " ")
    for id_area, nome in areas.items():
        if procurado in (
            normalizar_texto(id_area).replace("-", " "),
            normalizar_texto(nome),
        ):
            return id_area
    raise ErroValidacao(f"Área desconhecida. As áreas são: {', '.join(areas.values())}.")


def validar_nome(valor: object) -> str:
    if not isinstance(valor, str) or not (nome := " ".join(valor.split())):
        raise ErroValidacao("Nome inválido: informe um nome não vazio.")
    return nome


def chave_nome(nome: str) -> str:
    return normalizar_texto(nome).casefold()
