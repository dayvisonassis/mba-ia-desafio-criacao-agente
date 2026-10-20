"""Carga do regulamento por capítulo e busca que devolve artigos de um só capítulo."""

import re
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from aurora.config import DIR_DADOS
from aurora.validacao import normalizar_texto

PALAVRAS_VAZIAS = frozenset(
    "a o as os um uma uns umas de da do das dos em no na nos nas ao aos à às por para com "
    "e ou que se qual quais como eu me meu minha seu sua posso pode quero quer saber "
    "sobre ate ha foi ser ter mais muito pra pro".split()
)
BONUS_TITULO = 2


@dataclass(frozen=True)
class Capitulo:
    titulo: str
    artigos: tuple[str, ...]


def carregar_capitulos(caminho: Path | None = None) -> list[Capitulo]:
    """Lê o regulamento; o caminho padrão fica em cache, um caminho explícito não."""
    if caminho is None:
        return list(_capitulos_padrao())
    return _analisar(caminho.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _capitulos_padrao() -> tuple[Capitulo, ...]:
    return tuple(_analisar((DIR_DADOS / "regulamento.md").read_text(encoding="utf-8")))


def _analisar(texto: str) -> list[Capitulo]:
    capitulos: list[Capitulo] = []
    titulo: str | None = None
    artigos: list[str] = []
    atual: list[str] = []

    def fechar_artigo() -> None:
        if atual:
            artigos.append("\n".join(atual))
            atual.clear()

    def fechar_capitulo() -> None:
        fechar_artigo()
        if titulo is not None:
            capitulos.append(Capitulo(titulo, tuple(artigos)))
        artigos.clear()

    for linha in texto.splitlines():
        linha = linha.strip()
        if linha.startswith("## "):
            fechar_capitulo()
            titulo = linha[3:].strip()
        elif titulo is None or not linha:
            continue
        elif linha.startswith("**Art."):
            fechar_artigo()
            atual.append(linha)
        elif atual:
            atual.append(linha)
    fechar_capitulo()
    return capitulos


def _termos(texto: str) -> set[str]:
    """Palavras úteis, sem acento e sem o 's' final (plural e singular casam)."""
    palavras = re.findall(r"\w+", normalizar_texto(texto))
    return {p.removesuffix("s") for p in palavras if p not in PALAVRAS_VAZIAS}


def buscar(consulta: str, limite: int = 4) -> tuple[str, list[str]]:
    """Capítulo vencedor e até `limite` dos seus melhores artigos; ("", []) sem correspondência.

    Cada artigo vale o número de termos da consulta que ele contém. O capítulo soma o
    melhor artigo, os demais artigos que pontuam e um bônus por termo presente no título.
    """
    termos = _termos(consulta)
    melhor = 0
    escolhido: tuple[str, list[str]] = ("", [])
    for capitulo in carregar_capitulos():
        pontos = [(len(termos & _termos(a)), i) for i, a in enumerate(capitulo.artigos)]
        com_pontos = [p for p in pontos if p[0] > 0]
        bonus = BONUS_TITULO * len(termos & _termos(capitulo.titulo))
        if not com_pontos and not bonus:
            continue
        nota = sum(p for p, _ in com_pontos) + bonus
        if nota > melhor:
            ordem = sorted(com_pontos, key=lambda p: (-p[0], p[1]))[:limite]
            if not ordem:
                ordem = [(0, i) for i in range(min(limite, len(capitulo.artigos)))]
            melhor = nota
            ordem_texto = [capitulo.artigos[i] for _, i in sorted(ordem, key=lambda p: p[1])]
            escolhido = (capitulo.titulo, ordem_texto)
    return escolhido


class RegistroBuscas:
    """Marca chaves já vistas; guarda só as `maximo` mais recentes."""

    def __init__(self, maximo: int = 1000) -> None:
        self._maximo = maximo
        self._vistas: OrderedDict[str, None] = OrderedDict()

    def registrar(self, chave: str) -> bool:
        """True na primeira vez que a chave aparece, False nas seguintes."""
        if chave in self._vistas:
            return False
        self._vistas[chave] = None
        while len(self._vistas) > self._maximo:
            self._vistas.popitem(last=False)
        return True
