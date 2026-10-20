import os

from aurora import config


def test_nome_modelo_padrao(monkeypatch):
    monkeypatch.setenv("GEMINI_MODELO", " ")
    assert config.nome_modelo() == config.MODELO_PADRAO


def test_nome_modelo_da_variavel(monkeypatch):
    monkeypatch.setenv("GEMINI_MODELO", "gemini-3.8-flash")
    assert config.nome_modelo() == "gemini-3.8-flash"


def test_carregar_ambiente_forca_ai_studio(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    config.carregar_ambiente(tmp_path / ".env")
    assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "FALSE"


def test_carregar_ambiente_preserva_dir_var_do_processo(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("AURORA_DIR_VAR=\nGOOGLE_API_KEY=x\n", encoding="utf-8")
    monkeypatch.setenv("AURORA_DIR_VAR", str(tmp_path))
    monkeypatch.setenv("GOOGLE_API_KEY", "outro")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    config.carregar_ambiente(env)
    assert os.environ["AURORA_DIR_VAR"] == str(tmp_path)
    assert os.environ["GOOGLE_API_KEY"] == "x"


def test_caminhos_absolutos():
    assert config.caminho_banco().is_absolute()
    assert config.caminho_banco().name == "aurora.db"
    assert config.caminho_sessoes().name == "sessoes.db"


def test_dir_var_respeita_variavel(monkeypatch, tmp_path):
    monkeypatch.setenv("AURORA_DIR_VAR", str(tmp_path))
    assert config.caminho_banco() == tmp_path / "aurora.db"
    monkeypatch.setenv("AURORA_DIR_VAR", "")
    assert config.dir_var() == config.RAIZ / "var"
