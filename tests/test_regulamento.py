import pytest

from aurora import config
from aurora.regulamento import RegistroBuscas, buscar, carregar_capitulos

PISCINA = ["Até que horas a piscina funciona aos domingos?", "horário da piscina no domingo",
           "A piscina fecha que horas no domingo?",
           "Até que horas a piscina funciona aos domingos? O morador quer saber o horário de "
           "funcionamento da piscina aos domingos"]


def test_carrega_14_capitulos_e_96_artigos():
    caps = carregar_capitulos()
    assert len(caps) == 14 and sum(len(c.artigos) for c in caps) == 96
    assert caps[3].titulo == "Capítulo IV: Piscina"


def test_aceita_crlf(tmp_path):
    p = tmp_path / "r.md"
    p.write_bytes((config.DIR_DADOS / "regulamento.md").read_bytes().replace(b"\n", b"\r\n"))
    assert [c.titulo for c in carregar_capitulos(p)] == [c.titulo for c in carregar_capitulos()]


@pytest.mark.parametrize("pergunta", PISCINA)
def test_piscina(pergunta):
    titulo, artigos = buscar(pergunta)
    assert titulo == "Capítulo IV: Piscina" and 1 <= len(artigos) <= 4
    assert "das 9h às 20h" in "\n".join(artigos)


@pytest.mark.parametrize("c", ["barulho depois das 22h", "posso levar meu cachorro no elevador",
                               "mudança no sábado", "reservar a churrasqueira", "piscina"])
def test_artigos_de_um_unico_capitulo(c):
    titulo, artigos = buscar(c)
    capitulo = next(x for x in carregar_capitulos() if x.titulo == titulo)
    assert all(a in capitulo.artigos for a in artigos)


def test_sem_correspondencia_devolve_vazio():
    assert buscar("e o a de") == ("", [])
    assert buscar("") == ("", [])


def test_registro_de_buscas():
    r = RegistroBuscas(maximo=2)
    assert r.registrar("a") and not r.registrar("a")
    r.registrar("b"); r.registrar("c")
    assert r.registrar("a")
