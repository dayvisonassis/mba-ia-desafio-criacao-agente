import pytest

from aurora.validacao import (
    ErroValidacao,
    chave_nome,
    normalizar_texto,
    validar_area,
    validar_data,
    validar_nome,
)

AREAS = {
    "salao-de-festas": "Salão de festas",
    "churrasqueira": "Churrasqueira",
    "quadra": "Quadra poliesportiva",
}


def test_validar_data_aceita_iso():
    assert validar_data("2030-04-20") == "2030-04-20"


@pytest.mark.parametrize("v", ["20/04/2030", "2030-4-20", "2030-02-30", 20300420, None, ""])
def test_validar_data_recusa(v):
    with pytest.raises(ErroValidacao):
        validar_data(v)


@pytest.mark.parametrize(
    "v", ["salao-de-festas", "Salão de Festas", "salao de festas", " SALÃO DE FESTAS "]
)
def test_validar_area_aceita_nome_com_acento(v):
    assert validar_area(v, AREAS) == "salao-de-festas"


def test_validar_area_quadra_por_nome():
    assert validar_area("quadra poliesportiva", AREAS) == "quadra"


@pytest.mark.parametrize("v", ["piscina", "", None, 3])
def test_validar_area_recusa(v):
    with pytest.raises(ErroValidacao):
        validar_area(v, AREAS)


def test_validar_nome_normaliza_espacos():
    assert validar_nome("  Joana   Ribeiro ") == "Joana Ribeiro"


@pytest.mark.parametrize("v", ["", "   ", None, 12])
def test_validar_nome_recusa(v):
    with pytest.raises(ErroValidacao):
        validar_nome(v)


def test_chave_nome_ignora_caixa():
    assert chave_nome("Joana Ribeiro") == chave_nome("JOANA ribeiro")


def test_normalizar_texto():
    assert normalizar_texto("  Até   QUE Horas ") == "ate que horas"
