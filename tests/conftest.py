import pytest

from aurora.banco import garantir_esquema, restaurar_dados


@pytest.fixture
def banco(tmp_path, monkeypatch):
    """Banco isolado numa pasta temporária, já com a carga inicial."""
    monkeypatch.setenv("AURORA_DIR_VAR", str(tmp_path))
    garantir_esquema()
    restaurar_dados()
    yield
