from tests.apoio import sem_vazamento

UUID_COM_302 = "3f2b9c1e-a302-4d6e-9b1a-0c8e7f6d5a4b"


def test_sem_vazamento_ignora_uuid_com_302():
    assert sem_vazamento(
        {
            "id": UUID_COM_302,
            "invocationId": f"e-{UUID_COM_302}",
            "functionCall": {"id": f"adk-{UUID_COM_302}"},
        }
    )
    assert sem_vazamento({"id": UUID_COM_302.upper()})


def test_sem_vazamento_acusa_apartamento_302():
    assert not sem_vazamento({"texto": "apartamento 302"})
    assert not sem_vazamento({"id": UUID_COM_302, "texto": "Reserva do 302."})
    assert not sem_vazamento(f"{UUID_COM_302} 302")


def test_sem_vazamento_ignora_id_de_chamada():
    assert sem_vazamento({"id": "call_302"})
    assert sem_vazamento({"chamada_id": f"{UUID_COM_302}:call_302"})


def test_sem_vazamento_codigo_e_nome_valem_mesmo_junto_de_ids():
    assert not sem_vazamento({"id": f"{UUID_COM_302}RSV-4821"})
    assert not sem_vazamento({"id": f"adk-{UUID_COM_302}", "texto": f"{UUID_COM_302}:RSV-4821"})
    assert not sem_vazamento({"id": "call_1", "texto": "Marina Duarte"})
