# Assistente do Residencial Aurora: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir a API do assistente do Residencial Aurora (Google ADK + FastAPI + SQLite) que passa nos 15 passos do avaliador, com as cinco garantias implementadas em código.

**Architecture:** O agente principal `assistente_aurora` tem dois subagentes com transferência bloqueada (reservas e visitantes) e um `AgentTool` isolado (regulamento). As regras críticas vivem em:
- tools e callbacks;
- SQLite, com índice único parcial e idempotência por chamada;
- API, com as pendências derivadas dos eventos e o `409`.

As sessões são persistidas com o `SqliteSessionService` do ADK.

**Tech Stack:** Python 3.12, uv, google-adk 2.12.0, FastAPI, uvicorn, sqlite3 (biblioteca padrão), pytest, httpx.

**Spec:** `docs/superpowers/specs/2026-10-19-residencial-aurora-design.md` (revisão 5, aprovada). Neste plano, "spec §N" aponta para as seções dela, e "D<N>" para as decisões da tabela da seção 4. O enunciado original está em `git show be87e1d:README.md`.

## Global Constraints

- Python `>=3.12`, `.python-version` = `3.12`, projeto gerenciado por `uv` (`pyproject.toml` e `uv.lock` versionados).
- `google-adk==2.12.0`, versão exata.
- Nunca alterar `dados/`. `git diff --exit-code be87e1d -- dados/` deve passar sempre.
- `.env` nunca versionado. `.env.example` contém só `GOOGLE_API_KEY=` e `GEMINI_MODELO=`, sem valores.
- Não usar `agents-cli`, Vertex AI nem Google Cloud (CLAUDE.md). Sem `ResumabilityConfig` (spec §10.2).
- Nomes de agentes fixos:
  - `assistente_aurora`
  - `especialista_reservas`
  - `especialista_visitantes`
  - `especialista_regulamento`
- Nenhuma tool tem parâmetro `apartamento`. O apartamento vem sempre de `tool_context.state["apartamento"]`.
- Os callbacks de tool usam exatamente os parâmetros `tool`, `args`, `tool_context`, `tool_response` e `error`, porque o ADK os chama por nome (`flows/llm_flows/tools/_caller.py`).
- Toda leitura de `dados/` usa `encoding="utf-8"`.
- Caminhos sempre via `aurora.config` (`config.caminho_banco()` e afins), chamados na hora do uso, nunca relativos ao diretório atual.
- Todo texto mostrado ao morador fica em português.
- API em `127.0.0.1:8000`.
- Commits locais na branch `feat/assistente-aurora`. `push` e merge na `main` só com autorização do usuário (Task 12).
- Testes: `uv run pytest`. Nenhum teste chama o Gemini. A suíte de integração (Task 9) usa a pilha real com um modelo falso injetado por `agentes.criar_app(modelo=...)` (D24). Só o spike (Task 1) e o roteiro (Task 10) chamam o Gemini.
- Os bancos ficam em `config.dir_var()`, que respeita a variável opcional `AURORA_DIR_VAR` (D25). Os testes apontam para uma pasta temporária com `monkeypatch.setenv("AURORA_DIR_VAR", str(tmp_path))`.

## Review Focus

1. **Área escrita pelo nome, com acento e maiúsculas** ("Salão de Festas"): deve ser normalizada para `salao-de-festas` na tool e em `detalhes`. Testes: Task 2 `test_validar_area_aceita_nome_com_acento` e Task 7 `test_pendente_simples`.
2. **Data em outro formato** ("20/04/2030", "2030-4-20", o número 20300420): não pode criar pendência, e a tool responde `invalida`. Testes: Task 2 `test_validar_data_recusa` e Task 5 `test_confirmacao_reserva_pelo_function_tool` / `test_data_invalida`.
3. **O mesmo visitante pedido duas vezes**, com caixa ou espaços diferentes: só uma pendência listada. Teste: Task 7 `test_duplicata_com_nome_em_outra_caixa_e_substituida`.
4. **Eventos relidos do SQLite em ordem invertida** (a resposta "requires confirmation" depois do pedido de confirmação): a pendência continua listada. Teste: Task 7 `test_ordem_invertida_apos_recarga`.
5. **Pedidos malformados na API** (texto só com espaços, campo ausente, apartamento inexistente): `422`, sem chamar o modelo. Teste: Task 8 `test_entradas_malformadas`.

---

### Task 0: Ambiente e esqueleto do projeto

**Files:**
- Create: `pyproject.toml`, `.python-version`, `src/aurora/__init__.py`, `tests/__init__.py`, `tests/test_ambiente.py`
- Modify: `.gitignore`
- Generated: `uv.lock`

**Interfaces:**
- Produces: o pacote `aurora` importável. Os comandos `uv run api` e `uv run restaurar` ficam registrados, e os módulos deles chegam nas Tasks 3 e 8.

- [ ] **Step 1: Garantir o `uv`.** Rode `uv --version`. Se o comando não existir, **peça autorização ao usuário** antes de instalar:
  - instalação: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`;
  - depois, abra um shell novo ou use `$env:USERPROFILE\.local\bin\uv.exe`;
  - resultado esperado: `uv 0.x.y`.
- [ ] **Step 2: Branch.** `git checkout -b feat/assistente-aurora`
- [ ] **Step 3: Commitar o que já existe.**
  - `git add CLAUDE.md HANDOFF.md .env.example .claude/skills docs/superpowers`
  - `git commit -m "docs: design, plano e regras do projeto"`
- [ ] **Step 4: Criar `pyproject.toml`** com estes valores, fixados pela spec §12:

```toml
[project]
name = "aurora"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["google-adk==2.12.0", "fastapi", "uvicorn", "python-dotenv"]

[project.scripts]
api = "aurora.servidor:main"
restaurar = "aurora.restaurar:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/aurora"]

[dependency-groups]
dev = ["pytest", "httpx"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 5: Configuração de apoio.**
  - Criar `.python-version` com `3.12`.
  - Acrescentar ao `.gitignore`: `var/`, `spike/`, `.claude/settings.local.json`, `.pytest_cache/`.
  - Criar `src/aurora/__init__.py` e `tests/__init__.py` vazios.
- [ ] **Step 6: Escrever o teste**

```python
# tests/test_ambiente.py
import sys
import google.adk

def test_versoes():
    assert google.adk.__version__ == "2.12.0"
    assert sys.version_info[:2] >= (3, 12)
```

- [ ] **Step 7: Instalar e rodar.** `uv sync`, depois `uv run pytest tests/test_ambiente.py -v`. Esperado: `1 passed`.
- [ ] **Step 8: Commit.** `git add pyproject.toml uv.lock .python-version .gitignore src tests` e `git commit -m "chore: esqueleto do projeto com uv e ADK 2.12.0"`

---

### Task 1: Spike de confirmação (descartável, porta de decisão)

Implementa a spec §14.1 e a D23. **Nada desta task é commitado**, exceto a seção "Resultado do spike" no fim deste plano. A pasta `spike/` está no `.gitignore`.

**Files:**
- Create: `spike/spike_confirmacao.py` (descartável)
- Modify: este plano (seção "Resultado do spike")

**Interfaces:**
- Consumes: o ambiente da Task 0 e a `GOOGLE_API_KEY` do `.env`.
- Produces: o registro dos formatos observados, que as Tasks 6, 7 e 8 usam, e a escolha do modelo (D8).

- [ ] **Step 1: Escrever o spike** reproduzindo a **topologia final** (spec §6), com dados mínimos:
  - **Agentes:** com os nomes e flags da spec §6. Especialistas com `disallow_transfer_to_parent=True` e `disallow_transfer_to_peers=True`. O principal tem `tools=[AgentTool(especialista_regulamento, skip_summarization=True)]`. Sem `ResumabilityConfig`.
  - **Tools mínimas:**
    - `reservar_area(area: str, data: str, tool_context)` com `require_confirmation=precisa(area: str = "", data: str = "", tool_context=None)`, que retorna `True` para `salao-de-festas` e `churrasqueira`;
    - `autorizar_visitante(nome: str, data: str, tool_context)` com `require_confirmation=True`;
    - `buscar_no_regulamento(pergunta: str, tool_context)`, que devolve um de dois capítulos fixos escolhidos por palavra-chave em `pergunta + state["pergunta_regulamento"]`: "Capítulo IV: Piscina ... Aos domingos e feriados, a piscina funciona das 9h às 20h." ou "Capítulo V: ... playground das 8h às 20h". Ela permite uma busca por `tool_context.session.id`.
  - **Gravação:** em `spike/var/spike.db`, com o índice único parcial e `chamada_id UNIQUE` (spec §8.2, só as colunas necessárias).
  - **Callbacks:** os da spec §6.1 e §7.4.
  - **Contagem de chamadas:** um `before_model_callback` em todos os agentes conta as chamadas ao modelo em `spike/var/chamadas.txt`.
  - **Sessões:** `SqliteSessionService` em `spike/var/sessoes.db`, com caminho absoluto.
  - **Aprovação:** feita exatamente como na spec §9, com `Part(function_response=FunctionResponse(id=..., name="adk_request_confirmation", response={"confirmed": ...}))`.
  - **Uso:** `uv run python spike/spike_confirmacao.py <cenario> <fase>`. O comando `todos` roda cada fase num **subprocesso novo**, o que simula o reinício. Ele imprime `PASS`/`FAIL`/`NAO REPRODUZIDO` por cenário e grava os eventos em `spike/var/eventos_<n>.json`.
- [ ] **Step 2: Implementar as verificações** dos 16 cenários da spec §14.1:

| Cenário | Verificação objetiva |
|---|---|
| 1 | Existe `function_call` `adk_request_confirmation`; nenhuma linha gravada; contador de modelo não sobe depois da tool. |
| 2 | Depois de `false`: nenhuma linha; a resposta da tool é `{"status": "negada", ...}`; o contador não sobe. |
| 3 | Em outro processo, `true`: exatamente 1 linha; o autor da resposta da tool é `especialista_reservas`; o contador não sobe. |
| 4 | Reenviar o mesmo `true`: continua 1 linha (o Runner não lança exceção ou, se lançar, registre qual). |
| 5 | `quadra`: 1 linha sem `adk_request_confirmation`. |
| 6 | Sequência da spec §14.1 item 6: cada tool executa uma vez; quem responde cada aprovação é o especialista autor; a mensagem final é atendida primeiro por `assistente_aurora`. |
| 7 | Duas sessões aprovam a mesma área e data em paralelo (`asyncio.gather`): 1 linha, as duas terminam sem exceção, a perdedora recebe `data_ocupada`. |
| 8 | O JSON dos eventos da sessão principal não contém o texto bruto do capítulo devolvido pela busca, só a resposta do especialista. |
| 9 | Depois de recarregar do SQLite, registrar a ordem entre a resposta "requires confirmation" e o `adk_request_confirmation`; a aprovação do cenário 3 funcionou nessa ordem. |
| 10 | Registrar o total de chamadas ao modelo por cenário e se houve `429`. |
| 11 | Fluxo de visitantes: pedido, reinício, aprovação, 1 linha. |
| 12 | Depois de uma aprovação, a mensagem de texto seguinte é atendida primeiro por `assistente_aurora`. |
| 13 | Pedir explicitamente "chame reservar_area duas vezes com os mesmos argumentos". Se vierem duas chamadas, registrar o formato do evento. Se não vierem, marcar `NAO REPRODUZIDO`, porque a Task 7 cobre com eventos sintéticos. |
| 14 | A segunda chamada a `especialista_regulamento` no mesmo turno recebe erro sem executar; a segunda busca na mesma execução recebe erro. |
| 15 | "Reserve o salão para 2030-06-01 e a churrasqueira para 2030-06-02": duas pendências; aprovar uma e depois a outra; 2 linhas. |
| 16 | A pergunta da piscina, com o principal livre para reformular, traz "20h" na resposta final, e o turno termina na resposta do especialista. |

- [ ] **Step 3: Rodar** `uv run python spike/spike_confirmacao.py todos` com `GEMINI_MODELO` vazio (padrão `gemini-3.8-flash`). Esperado: todos `PASS`, exceto o 13, que pode ser `NAO REPRODUZIDO`. Se houver `429` depois das novas tentativas, repita com `GEMINI_MODELO=gemini-2.5-flash` (D8).
- [ ] **Step 4: Porta de decisão (D23).** Se algum cenário der `FAIL`, **pare a execução do plano** e leve ao usuário o cenário, os eventos e a hipótese. Não aplique plano B sem aprovação.
- [ ] **Step 5: Registrar** na seção "Resultado do spike" deste plano:
  - a tabela de resultados;
  - o formato do evento final do `AgentTool` com `skip_summarization` (esperado pelo código do ADK: `function_response` mais uma parte de texto com o resultado, em `_caller.py`);
  - a ordem dos eventos depois da recarga;
  - o número de chamadas ao modelo;
  - o modelo escolhido.
- [ ] **Step 6: Apagar** `spike/` e commitar só o plano: `git commit -am "docs: resultado do spike de confirmação"`.

---

### Task 2: Configuração e validação compartilhada

**Files:**
- Create: `src/aurora/config.py`, `src/aurora/validacao.py`, `tests/test_config.py`, `tests/test_validacao.py`
- Modify: `.env.example` (acrescenta `AURORA_DIR_VAR=`)

**Interfaces:**
- Produces, em `aurora.config`:
  - `RAIZ: Path`, a raiz do projeto, com `Path(__file__).resolve().parents[2]`;
  - `DIR_DADOS: Path`, igual a `RAIZ / "dados"`;
  - `MODELO_PADRAO = "gemini-3.8-flash"` e `MODELO_ALTERNATIVO = "gemini-2.5-flash"` (ou o que o spike registrar);
  - `dir_var() -> Path`: `Path(os.environ["AURORA_DIR_VAR"])` se a variável existir e não estiver vazia, senão `RAIZ / "var"`. É lida a cada chamada (D25);
  - `caminho_banco() -> Path`, igual a `dir_var() / "aurora.db"`;
  - `caminho_sessoes() -> Path`, igual a `dir_var() / "sessoes.db"`;
  - `carregar_ambiente() -> None`, que faz `load_dotenv(RAIZ / ".env", override=True)` e depois `os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"`;
  - `nome_modelo() -> str`, que devolve `GEMINI_MODELO` sem espaços, ou `MODELO_PADRAO` se estiver vazio.
- Produces, em `aurora.validacao`:
  - `class ErroValidacao(ValueError)`;
  - `normalizar_texto(texto: str) -> str`: minúsculas, sem acentos (NFKD), espaços colapsados, sem pontas;
  - `validar_data(valor: object) -> str`: só `str` no padrão `^\d{4}-\d{2}-\d{2}$` e válida por `date.fromisoformat`;
  - `validar_area(valor: object, areas: Mapping[str, str]) -> str`: `areas` é id → nome, e devolve o id. Casa por `normalizar_texto` contra o id (com `-` virando espaço) e contra o nome;
  - `validar_nome(valor: object) -> str`: `str` não vazia depois de tirar as pontas e colapsar espaços, com a grafia preservada;
  - `chave_nome(nome: str) -> str`: `normalizar_texto(nome).casefold()`, usada para comparar duplicatas.

- [ ] **Step 1: Escrever os testes**

```python
# tests/test_validacao.py
AREAS = {"salao-de-festas": "Salão de festas", "churrasqueira": "Churrasqueira",
         "quadra": "Quadra poliesportiva"}

def test_validar_data_aceita_iso(): assert validar_data("2030-04-20") == "2030-04-20"
@pytest.mark.parametrize("v", ["20/04/2030", "2030-4-20", "2030-02-30", 20300420, None, ""])
def test_validar_data_recusa(v):
    with pytest.raises(ErroValidacao): validar_data(v)
@pytest.mark.parametrize("v", ["salao-de-festas", "Salão de Festas", "salao de festas", " SALÃO DE FESTAS "])
def test_validar_area_aceita_nome_com_acento(v): assert validar_area(v, AREAS) == "salao-de-festas"
def test_validar_area_quadra_por_nome(): assert validar_area("quadra poliesportiva", AREAS) == "quadra"
@pytest.mark.parametrize("v", ["piscina", "", None, 3])
def test_validar_area_recusa(v):
    with pytest.raises(ErroValidacao): validar_area(v, AREAS)
def test_validar_nome_normaliza_espacos(): assert validar_nome("  Joana   Ribeiro ") == "Joana Ribeiro"
@pytest.mark.parametrize("v", ["", "   ", None, 12])
def test_validar_nome_recusa(v):
    with pytest.raises(ErroValidacao): validar_nome(v)
def test_chave_nome_ignora_caixa(): assert chave_nome("Joana Ribeiro") == chave_nome("JOANA ribeiro")
def test_normalizar_texto(): assert normalizar_texto("  Até   QUE Horas ") == "ate que horas"
```

```python
# tests/test_config.py
def test_nome_modelo_padrao(monkeypatch):
    monkeypatch.setenv("GEMINI_MODELO", " "); assert config.nome_modelo() == config.MODELO_PADRAO
def test_nome_modelo_da_variavel(monkeypatch):
    monkeypatch.setenv("GEMINI_MODELO", "gemini-2.5-flash"); assert config.nome_modelo() == "gemini-2.5-flash"
def test_carregar_ambiente_forca_ai_studio(monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "TRUE"); config.carregar_ambiente()
    assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "FALSE"
def test_caminhos_absolutos():
    assert config.caminho_banco().is_absolute() and config.caminho_banco().name == "aurora.db"
    assert config.caminho_sessoes().name == "sessoes.db"
def test_dir_var_respeita_variavel(monkeypatch, tmp_path):
    monkeypatch.setenv("AURORA_DIR_VAR", str(tmp_path)); assert config.caminho_banco() == tmp_path / "aurora.db"
    monkeypatch.setenv("AURORA_DIR_VAR", ""); assert config.dir_var() == config.RAIZ / "var"
```

- [ ] **Step 2: Rodar.** `uv run pytest tests/test_validacao.py tests/test_config.py -v`. Esperado: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implementar** `config.py` e `validacao.py` com as assinaturas acima. Acrescentar ao `.env.example` a linha `AURORA_DIR_VAR=`, com um comentário dizendo que é opcional e que vazio significa `var/`.
- [ ] **Step 4: Rodar de novo.** Esperado: todos PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: configuração e validação compartilhada"` (depois de `git add` dos 4 arquivos)

---

### Task 3: Banco, repositório e restauração

**Files:**
- Create: `src/aurora/banco.py`, `src/aurora/repositorio.py`, `src/aurora/restaurar.py`, `tests/conftest.py`, `tests/test_repositorio.py`

**Interfaces:**
- Consumes: `config.caminho_banco()`, `config.dir_var()`, `config.DIR_DADOS`.
- Produces, em `aurora.banco`:
  - `ESQUEMA_SQL: str`, igual ao esquema da spec §8.2 com `IF NOT EXISTS`;
  - `conectar() -> sqlite3.Connection`, com `timeout=10`, `isolation_level=None` (as transações são explícitas), `row_factory=sqlite3.Row`, `PRAGMA foreign_keys=ON` e `PRAGMA journal_mode=WAL`;
  - `garantir_esquema() -> None`, que cria `dir_var()` e o esquema;
  - `restaurar_dados() -> None`, que segue a spec §8.4 numa transação: apaga `reservas`, `visitantes`, `areas` e `apartamentos` e recarrega os JSON em UTF-8. As reservas iniciais entram com `status='ativa'` e `chamada_id NULL`. Os códigos iniciais vão para `codigos_emitidos` com `INSERT OR IGNORE`. Não toca em `codigos_emitidos` (fora isso) nem em `sessoes`;
  - `inicializar_se_necessario() -> None`: se `caminho_banco()` não existir, chama `garantir_esquema()` e `restaurar_dados()`. Se existir, não faz nada.
- Produces, em `aurora.repositorio`:
  - dataclasses congeladas `Area(id, nome, taxa: float)`, `Reserva(codigo, apartamento, area, data, status)` e `Visitante(apartamento, nome, data)`;
  - `class DataOcupada(Exception)` e `class ConflitoDeChamada(RuntimeError)`;
  - `CONSOANTES = "BCDFGHJKLMNPQRSTVWXZ"`;
  - `listar_areas() -> list[Area]`, `mapa_areas() -> dict[str, str]` (id → nome) e `buscar_area(area_id: str) -> Area | None`;
  - `apartamento_existe(numero: str) -> bool`;
  - `listar_reservas_ativas(apartamento: str) -> list[Reserva]`, ordenadas por data;
  - `data_disponivel(area: str, data: str) -> bool`;
  - `gerar_codigo() -> str`: `"RSV-N"` mais 8 letras de `CONSOANTES` via `secrets.choice`;
  - `criar_reserva(apartamento: str, area: str, data: str, chamada_id: str | None) -> Reserva`. Segue a spec §8.3: `BEGIN IMMEDIATE`, depois SELECT por `chamada_id`. Se existir com os mesmos dados, devolve o registro; se existir com outros dados, lança `ConflitoDeChamada`. Senão chama `gerar_codigo()`, faz INSERT em `codigos_emitidos` e INSERT em `reservas`, e dá `COMMIT`. Os erros são tratados assim:
    - `IntegrityError` com `reservas.area, reservas.data` na mensagem: `DataOcupada`;
    - `IntegrityError` com `codigos_emitidos.codigo`: novo código, até 5 tentativas.
  - `cancelar_reserva(apartamento: str, area: str, data: str) -> Reserva | None`: só a reserva ativa **do apartamento**, que passa a `status='cancelada'` com `cancelada_em`;
  - `listar_visitantes(apartamento: str) -> list[Visitante]`, ordenados por data;
  - `autorizar_visitante(apartamento: str, nome: str, data: str, chamada_id: str | None) -> Visitante`, com a mesma idempotência. Os dados "iguais" são comparados por apartamento, `chave_nome` e data;
  - `registrar_sessao(session_id: str, apartamento: str) -> None` e `apartamento_da_sessao_id(session_id: str) -> str | None`.
- Produces, em `aurora.restaurar`: `main() -> None`, que chama `garantir_esquema()` e `restaurar_dados()` e imprime um resumo.
- Produces, em `tests/conftest.py`: a fixture `banco(tmp_path, monkeypatch)`, que faz `monkeypatch.setenv("AURORA_DIR_VAR", str(tmp_path))`, chama `garantir_esquema()` e `restaurar_dados()` e faz `yield`.

- [ ] **Step 1: Escrever os testes** (`tests/test_repositorio.py`)

```python
def test_restauracao_carrega_json(banco):
    assert listar_reservas_ativas("101") == [Reserva("RSV-1377", "101", "quadra", "2030-03-09", "ativa")]
    assert listar_visitantes("302") == [Visitante("302", "Marina Duarte", "2030-03-16")]
    assert {a.id: a.taxa for a in listar_areas()} == {"salao-de-festas": 150.0, "churrasqueira": 80.0, "quadra": 0}
    assert buscar_area("salao-de-festas").nome == "Salão de festas"   # UTF-8
def test_segunda_reserva_ativa_e_recusada(banco):
    with pytest.raises(DataOcupada): criar_reserva("101", "salao-de-festas", "2030-03-16", None)
def test_concorrencia_duas_threads(banco):
    # duas threads com threading.Barrier(2) chamando criar_reserva("101"/"201", "salao-de-festas", "2030-05-11", None)
    assert sorted(resultados) == ["ocupada", "ok"]
    assert sum(r.data == "2030-05-11" for a in ("101", "201") for r in listar_reservas_ativas(a)) == 1
def test_cancelada_libera_data(banco):
    assert cancelar_reserva("101", "quadra", "2030-03-09").codigo == "RSV-1377"
    assert listar_reservas_ativas("101") == []
    assert criar_reserva("201", "quadra", "2030-03-09", None).codigo != "RSV-1377"
def test_cancelar_de_outro_apartamento_nao_encontra(banco):
    assert cancelar_reserva("101", "salao-de-festas", "2030-03-16") is None
    assert [r.codigo for r in listar_reservas_ativas("302")] == ["RSV-4821"]
def test_mesma_chamada_nao_grava_de_novo(banco):
    a = criar_reserva("101", "salao-de-festas", "2030-04-20", "s1:c1")
    b = criar_reserva("101", "salao-de-festas", "2030-04-20", "s1:c1")
    assert a.codigo == b.codigo and len(listar_reservas_ativas("101")) == 2
def test_mesma_chamada_com_outros_dados_e_conflito(banco):
    criar_reserva("101", "salao-de-festas", "2030-04-20", "s1:c1")
    with pytest.raises(ConflitoDeChamada): criar_reserva("101", "churrasqueira", "2030-04-20", "s1:c1")
def test_formato_do_codigo():
    for _ in range(50): assert re.fullmatch(r"RSV-N[BCDFGHJKLMNPQRSTVWXZ]{8}", gerar_codigo())
def test_codigo_emitido_nunca_se_repete_mesmo_apos_restaurar(banco, monkeypatch):
    usado = criar_reserva("101", "churrasqueira", "2030-06-01", None).codigo
    restaurar_dados()
    seq = iter([usado, "RSV-NBBBBBBBB"]); monkeypatch.setattr(repositorio, "gerar_codigo", lambda: next(seq))
    assert criar_reserva("101", "churrasqueira", "2030-06-01", None).codigo == "RSV-NBBBBBBBB"
def test_restauracao_preserva_sessoes_e_zera_reservas(banco):
    registrar_sessao("s1", "101"); criar_reserva("101", "churrasqueira", "2030-06-01", None)
    restaurar_dados()
    assert apartamento_da_sessao_id("s1") == "101"
    assert [r.codigo for r in listar_reservas_ativas("101")] == ["RSV-1377"]
def test_visitante_idempotente(banco):
    autorizar_visitante("101", "Joana Ribeiro", "2030-04-21", "s1:c9")
    autorizar_visitante("101", "Joana Ribeiro", "2030-04-21", "s1:c9")
    assert listar_visitantes("101") == [Visitante("101", "Joana Ribeiro", "2030-04-21")]
def test_data_disponivel(banco):
    assert not data_disponivel("salao-de-festas", "2030-03-16") and data_disponivel("salao-de-festas", "2030-04-20")
def test_inicializar_nao_apaga_banco_existente(tmp_path, monkeypatch):
    monkeypatch.setenv("AURORA_DIR_VAR", str(tmp_path))
    inicializar_se_necessario(); criar_reserva("101", "churrasqueira", "2030-06-01", None)
    inicializar_se_necessario()
    assert len(listar_reservas_ativas("101")) == 2
```

- [ ] **Step 2: Rodar.** `uv run pytest tests/test_repositorio.py -v`. Esperado: FAIL (módulos inexistentes).
- [ ] **Step 3: Implementar** `banco.py`, `repositorio.py` e `restaurar.py` com as interfaces acima.
- [ ] **Step 4: Rodar de novo.** Esperado: todos PASS. Depois rode `uv run restaurar`, que cria `var/aurora.db` e imprime o resumo, e confira com `git status` que `var/` não aparece.
- [ ] **Step 5: Commit.** `git commit -m "feat: banco SQLite, repositório e restauração"`

---

### Task 4: Regulamento: carga e busca

**Files:**
- Create: `src/aurora/regulamento.py`, `tests/test_regulamento.py`

**Interfaces:**
- Consumes: `config.DIR_DADOS`, `validacao.normalizar_texto`.
- Produces:
  - `@dataclass(frozen=True) class Capitulo: titulo: str; artigos: tuple[str, ...]`;
  - `carregar_capitulos(caminho: Path | None = None) -> list[Capitulo]`. Lê em UTF-8 e aceita `\r\n`. O título é o texto depois de `## `, por exemplo `"Capítulo IV: Piscina"`. Cada artigo começa numa linha `**Art.` e vai até o próximo artigo ou capítulo. O caminho padrão fica em cache;
  - `buscar(consulta: str, limite: int = 4) -> tuple[str, list[str]]`: devolve o título do capítulo vencedor e até `limite` artigos **desse** capítulo, pela pontuação da spec §7.5. A fórmula é livre (spec §17), desde que passe nos testes;
  - `class RegistroBuscas: __init__(self, maximo: int = 1000)` e `registrar(self, chave: str) -> bool`. Devolve `True` na primeira vez e `False` nas seguintes, com descarte das chaves mais antigas acima de `maximo` (`OrderedDict`).

- [ ] **Step 1: Escrever os testes**

```python
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
def test_registro_de_buscas():
    r = RegistroBuscas(maximo=2)
    assert r.registrar("a") and not r.registrar("a")
    r.registrar("b"); r.registrar("c")
    assert r.registrar("a")
```

- [ ] **Step 2: Rodar.** `uv run pytest tests/test_regulamento.py -v`. Esperado: FAIL.
- [ ] **Step 3: Implementar** `regulamento.py`.
- [ ] **Step 4: Rodar de novo.** Esperado: todos PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: carga e busca no regulamento por capítulo"`

---

### Task 5: Ferramentas (tools e funções de confirmação)

**Files:**
- Create: `src/aurora/ferramentas.py`, `tests/apoio.py`, `tests/test_ferramentas.py`

**Interfaces:**
- Consumes: `validacao.*`; `repositorio.*` (importado como módulo, `from aurora import repositorio`, para não colidir com os nomes das tools); `regulamento.buscar` e `regulamento.RegistroBuscas`.
- Produces, em `aurora.ferramentas`:
  - `CHAVE_PERGUNTA = "pergunta_regulamento"`;
  - `REGISTRO_BUSCAS = regulamento.RegistroBuscas()`;
  - `apartamento_da_sessao(tool_context) -> str`: lê `tool_context.state["apartamento"]` e lança `RuntimeError` se não houver;
  - `precisa_confirmar_reserva(area: object = "", data: object = "", tool_context: object = None) -> bool`: tudo dentro de `try/except Exception: return False`. Retorna `True` só se `validar_area` e `validar_data` passarem e `buscar_area(id).taxa > 0` (spec §7.1, D17);
  - `precisa_confirmar_visitante(nome: object = "", data: object = "", tool_context: object = None) -> bool`: mesmo padrão, `True` se `validar_nome` e `validar_data` passarem;
  - as tools, todas com `tool_context: ToolContext` como último parâmetro e docstring em português para o modelo:
    - `listar_minhas_reservas(tool_context) -> dict`: `{"status": "ok", "reservas": [{"codigo", "area", "data"}]}`;
    - `verificar_disponibilidade(area: str, data: str, tool_context) -> dict`: `{"status": "ok", "area", "data", "disponivel": bool}` ou `{"status": "invalida", "mensagem"}`;
    - `reservar_area(area: str, data: str, tool_context) -> dict`: segue a spec §7.1, nesta ordem: `invalida`; depois `nao_confirmada`, quando há taxa e `tool_context.tool_confirmation` é `None` ou não está `confirmed`; depois `criada` (`codigo, area, data, taxa`) ou `recusada` (`motivo: "data_ocupada"`). O `chamada_id` é `f"{tool_context.session.id}:{tool_context.function_call_id}"`;
    - `cancelar_reserva(area: str, data: str, tool_context) -> dict`: `cancelada` (`codigo, area, data`), `nao_encontrada` ou `invalida`;
    - `listar_meus_visitantes(tool_context) -> dict`: `{"status": "ok", "visitantes": [{"nome", "data"}]}`;
    - `autorizar_visitante(nome: str, data: str, tool_context) -> dict`: `invalida`, `nao_confirmada` ou `autorizado` (`nome, data`), com o mesmo `chamada_id`;
    - `buscar_no_regulamento(pergunta: str, tool_context) -> dict`. Se `REGISTRO_BUSCAS.registrar(tool_context.session.id)` for `False`, devolve `{"status": "erro", "mensagem": ...}`. Senão devolve `buscar(pergunta + " " + tool_context.state.get(CHAVE_PERGUNTA, ""))` como `{"status": "ok", "capitulo", "artigos"}`.
  - Toda resposta de escrita (`criada`, `recusada`, `cancelada`, `nao_encontrada`, `autorizado`, `nao_confirmada`, `invalida`) tem `mensagem` em português, e nenhuma cita dado de outro apartamento.
  - `FERRAMENTAS_RESERVAS: list[FunctionTool]`: as 4 tools de reserva, com `FunctionTool(reservar_area, require_confirmation=precisa_confirmar_reserva)`.
  - `FERRAMENTAS_VISITANTES: list[FunctionTool]`: com `FunctionTool(autorizar_visitante, require_confirmation=precisa_confirmar_visitante)`.
  - `FERRAMENTA_REGULAMENTO: FunctionTool`.
- Produces, em `tests/apoio.py`:
  - `class ContextoFalso`, com `__init__(self, apartamento="101", session_id="s1", function_call_id="c1", confirmacao=None, state=None)` e os atributos `state` (dict; o padrão é `{"apartamento": apartamento}`), `session` (`SimpleNamespace(id=session_id)`), `function_call_id`, `tool_confirmation`, `actions` (`SimpleNamespace(skip_summarization=False)`) e `user_content` (`None`);
  - `ferramenta(nome: str) -> FunctionTool`, que procura nas três listas por `.name`;
  - `sem_vazamento(resposta) -> bool`: `json.dumps(resposta, ensure_ascii=False)` não contém `RSV-4821`, `Marina Duarte` nem casa `(?<!\d)302(?!\d)`.

- [ ] **Step 1: Escrever os testes** (`tests/test_ferramentas.py`; `check_require_confirmation` é async, então use `asyncio.run`)

```python
def test_nenhuma_tool_recebe_apartamento():
    for t in FERRAMENTAS_RESERVAS + FERRAMENTAS_VISITANTES + [FERRAMENTA_REGULAMENTO]:
        assert "apartamento" not in inspect.signature(t.func).parameters
@pytest.mark.parametrize("args,esperado", [
    ({"area": "salao-de-festas", "data": "2030-04-20"}, True), ({"area": "Salão de festas", "data": "2030-04-20"}, True),
    ({"area": "churrasqueira", "data": "2030-04-20"}, True), ({"area": "quadra", "data": "2030-04-06"}, False),
    ({"area": "salao-de-festas", "data": "20/04/2030"}, False), ({"area": "salao-de-festas"}, False),
    ({"area": "salao-de-festas", "data": 20300420}, False), ({"area": "piscina", "data": "2030-04-20"}, False)])
def test_confirmacao_reserva_pelo_function_tool(banco, args, esperado):
    assert asyncio.run(ferramenta("reservar_area").check_require_confirmation(args, ContextoFalso())) is esperado
@pytest.mark.parametrize("args,esperado", [({"nome": "Joana Ribeiro", "data": "2030-04-21"}, True),
    ({"nome": "  ", "data": "2030-04-21"}, False), ({"nome": "Joana", "data": "amanhã"}, False), ({"data": "2030-04-21"}, False)])
def test_confirmacao_visitante_pelo_function_tool(banco, args, esperado):
    assert asyncio.run(ferramenta("autorizar_visitante").check_require_confirmation(args, ContextoFalso())) is esperado
def test_quadra_grava_sem_confirmacao(banco):
    r = reservar_area("quadra", "2030-04-06", ContextoFalso())
    assert r["status"] == "criada" and re.fullmatch(r"RSV-N[A-Z]{8}", r["codigo"])
@pytest.mark.parametrize("conf", [None, ToolConfirmation(confirmed=False)])
def test_salao_sem_aprovacao_nao_grava(banco, conf):
    assert reservar_area("salao-de-festas", "2030-04-20", ContextoFalso(confirmacao=conf))["status"] == "nao_confirmada"
    assert repositorio.data_disponivel("salao-de-festas", "2030-04-20")
def test_salao_aprovado_grava_uma_vez(banco):
    ctx = ContextoFalso(confirmacao=ToolConfirmation(confirmed=True))
    assert reservar_area("salao-de-festas", "2030-04-20", ctx)["codigo"] == reservar_area("salao-de-festas", "2030-04-20", ctx)["codigo"]
    assert sum(r.area == "salao-de-festas" for r in repositorio.listar_reservas_ativas("101")) == 1
def test_data_ocupada_sem_vazar(banco):
    r = reservar_area("salao-de-festas", "2030-03-16", ContextoFalso(confirmacao=ToolConfirmation(confirmed=True)))
    assert r["status"] == "recusada" and r["motivo"] == "data_ocupada" and sem_vazamento(r)
def test_disponibilidade_sem_dono(banco):
    r = verificar_disponibilidade("salao-de-festas", "2030-03-16", ContextoFalso())
    assert r["disponivel"] is False and sem_vazamento(r)
def test_cancelar_de_outro_apartamento(banco):
    r = cancelar_reserva("salao-de-festas", "2030-03-16", ContextoFalso())
    assert r["status"] == "nao_encontrada" and sem_vazamento(r)
def test_cancelar_propria(banco):
    assert cancelar_reserva("quadra", "2030-03-09", ContextoFalso())["codigo"] == "RSV-1377"
def test_listar_so_do_apartamento(banco):
    assert listar_minhas_reservas(ContextoFalso())["reservas"] == [{"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}]
    assert listar_meus_visitantes(ContextoFalso())["visitantes"] == []
def test_visitante_exige_aprovacao(banco):
    assert autorizar_visitante("Joana Ribeiro", "2030-04-21", ContextoFalso())["status"] == "nao_confirmada"
    assert autorizar_visitante("Joana Ribeiro", "2030-04-21", ContextoFalso(confirmacao=ToolConfirmation(confirmed=True)))["status"] == "autorizado"
    assert listar_meus_visitantes(ContextoFalso())["visitantes"] == [{"nome": "Joana Ribeiro", "data": "2030-04-21"}]
def test_data_invalida(banco):
    assert reservar_area("quadra", "20/04/2030", ContextoFalso())["status"] == "invalida"
def test_sem_apartamento_na_sessao(banco):
    with pytest.raises(RuntimeError): reservar_area("quadra", "2030-04-06", ContextoFalso(state={}))
def test_regulamento_usa_pergunta_do_morador_e_limita(banco):
    ctx = ContextoFalso(session_id="filho-1", state={"pergunta_regulamento": "Até que horas a piscina funciona aos domingos?"})
    r = buscar_no_regulamento("horário de funcionamento", ctx)
    assert r["capitulo"] == "Capítulo IV: Piscina" and "das 9h às 20h" in "\n".join(r["artigos"])
    assert buscar_no_regulamento("piscina", ctx)["status"] == "erro"
```

- [ ] **Step 2: Rodar.** `uv run pytest tests/test_ferramentas.py -v`. Esperado: FAIL.
- [ ] **Step 3: Implementar** `ferramentas.py` e `tests/apoio.py`.
- [ ] **Step 4: Rodar de novo**, com `uv run pytest -v` para a suíte toda. Esperado: todos PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: tools com confirmação condicional e apartamento da sessão"`

---

### Task 6: Agentes, callbacks e App

**Files:**
- Create: `src/aurora/agentes.py`, `tests/test_agentes.py`

**Interfaces:**
- Consumes: `ferramentas.FERRAMENTAS_RESERVAS`, `FERRAMENTAS_VISITANTES`, `FERRAMENTA_REGULAMENTO` e `CHAVE_PERGUNTA`; `config.nome_modelo()`; `repositorio.listar_areas()`; o resultado do spike.
- Produces:
  - `NOME_PRINCIPAL = "assistente_aurora"`, `NOME_RESERVAS = "especialista_reservas"`, `NOME_VISITANTES = "especialista_visitantes"`, `NOME_REGULAMENTO = "especialista_regulamento"`;
  - `CHAVE_REGULAMENTO_USADO = "temp:regulamento_consultado"` e `MENSAGEM_NEGADA = "Tudo bem, nada foi feito."`;
  - `criar_modelo() -> Gemini`: `Gemini(model=config.nome_modelo(), retry_options=types.HttpRetryOptions(attempts=5, initial_delay=2.0, http_status_codes=[429, 503]))`. O número de tentativas é livre (spec §17);
  - `antes_da_tool_principal(tool, args, tool_context) -> dict | None`. Só age se `tool.name == NOME_REGULAMENTO`:
    - se `state[CHAVE_REGULAMENTO_USADO]` já estiver marcado, devolve `{"status": "erro", "mensagem": ...}`;
    - senão marca a chave, grava `state[CHAVE_PERGUNTA]` com o texto das partes de `tool_context.user_content` e devolve `None`.
  - `depois_da_tool_especialista(tool, args, tool_context, tool_response) -> dict | None`. Se `tool_context.tool_confirmation is None`, devolve `None` sem mexer em nada. Senão marca `tool_context.actions.skip_summarization = True` e:
    - se não estiver `confirmed`, devolve `{"status": "negada", "mensagem": MENSAGEM_NEGADA}`;
    - se estiver, devolve `None`.
  - `erro_da_tool_especialista(tool, args, tool_context, error) -> dict`: `{"status": "erro", "mensagem": <texto fixo>}`, sem o texto da exceção, e registra a exceção com `logging`;
  - `instrucao_reservas(contexto) -> str`: instruction provider que lista as áreas do banco (`id`, `nome`, "com taxa" ou "sem taxa") e as orientações da spec §6.2;
  - `criar_agente_principal(modelo: BaseLlm | None = None) -> LlmAgent`:
    - especialistas com `disallow_transfer_to_parent=True`, `disallow_transfer_to_peers=True`, `after_tool_callback=depois_da_tool_especialista` e `on_tool_error_callback=erro_da_tool_especialista`;
    - `especialista_regulamento` com `tools=[FERRAMENTA_REGULAMENTO]` e as instruções da spec §6.4;
    - principal com `sub_agents=[reservas, visitantes]`, `tools=[AgentTool(regulamento, skip_summarization=True)]`, `before_tool_callback=antes_da_tool_principal` e uma instrução (`str`) com o roteamento da spec §6.1, sem nenhum trecho do regulamento;
    - todos com o mesmo modelo: o `modelo` recebido quando informado (só a suíte de integração da Task 9 informa, D24), senão `criar_modelo()`. Todos com o campo `description` preenchido.
  - `criar_app(modelo: BaseLlm | None = None) -> App`: `App(name="aurora", root_agent=criar_agente_principal(modelo))`, sem `resumability_config`.

- [ ] **Step 1: Escrever os testes** (`tests/test_agentes.py`; nenhum chama o modelo)

```python
def test_topologia():
    raiz = criar_agente_principal()
    assert raiz.name == "assistente_aurora"
    assert [a.name for a in raiz.sub_agents] == ["especialista_reservas", "especialista_visitantes"]
    assert all(e.disallow_transfer_to_parent and e.disallow_transfer_to_peers for e in raiz.sub_agents)
    [t] = raiz.tools
    assert isinstance(t, AgentTool) and t.agent.name == "especialista_regulamento" and t.skip_summarization
def test_tools_dos_especialistas():
    reservas, visitantes = criar_agente_principal().sub_agents
    assert {t.name for t in reservas.tools} == {"listar_minhas_reservas", "verificar_disponibilidade", "reservar_area", "cancelar_reserva"}
    assert {t.name for t in visitantes.tools} == {"listar_meus_visitantes", "autorizar_visitante"}
def test_principal_sem_regulamento_nas_instrucoes():
    texto = criar_agente_principal().instruction
    assert isinstance(texto, str) and "Capítulo" not in texto and "Art." not in texto
    for linha in (config.DIR_DADOS / "regulamento.md").read_text(encoding="utf-8").splitlines():
        if len(linha.strip()) > 30: assert linha.strip() not in texto
def test_app_sem_retomabilidade():
    app = criar_app(); assert app.name == "aurora" and app.resumability_config is None
def test_instrucao_reservas_lista_areas(banco):
    texto = instrucao_reservas(None); assert "salao-de-festas" in texto and "quadra" in texto
def test_antes_da_tool_principal_uma_chamada_e_copia_pergunta():
    ctx = ContextoFalso(state={})
    ctx.user_content = types.Content(role="user", parts=[types.Part(text="Até que horas a piscina funciona aos domingos?")])
    reg = SimpleNamespace(name="especialista_regulamento")
    assert antes_da_tool_principal(tool=reg, args={"request": "x"}, tool_context=ctx) is None
    assert ctx.state["pergunta_regulamento"] == "Até que horas a piscina funciona aos domingos?"
    assert antes_da_tool_principal(tool=reg, args={}, tool_context=ctx)["status"] == "erro"
    assert antes_da_tool_principal(tool=SimpleNamespace(name="transfer_to_agent"), args={}, tool_context=ctx) is None
def test_depois_da_tool_negada():
    ctx = ContextoFalso(confirmacao=ToolConfirmation(confirmed=False))
    r = depois_da_tool_especialista(tool=None, args={}, tool_context=ctx, tool_response={"error": "This tool call is rejected."})
    assert r == {"status": "negada", "mensagem": "Tudo bem, nada foi feito."} and ctx.actions.skip_summarization
def test_depois_da_tool_aprovada():
    ctx = ContextoFalso(confirmacao=ToolConfirmation(confirmed=True))
    assert depois_da_tool_especialista(tool=None, args={}, tool_context=ctx, tool_response={"status": "criada"}) is None
    assert ctx.actions.skip_summarization
def test_depois_da_tool_sem_confirmacao():
    ctx = ContextoFalso()
    assert depois_da_tool_especialista(tool=None, args={}, tool_context=ctx, tool_response={"status": "ok"}) is None
    assert not ctx.actions.skip_summarization
def test_erro_da_tool_nao_vaza_excecao():
    r = erro_da_tool_especialista(tool=None, args={}, tool_context=ContextoFalso(), error=RuntimeError("segredo interno"))
    assert r["status"] == "erro" and "segredo" not in r["mensagem"]
```

- [ ] **Step 2: Rodar.** `uv run pytest tests/test_agentes.py -v`. Esperado: FAIL.
- [ ] **Step 3: Implementar** `agentes.py`, aplicando o que o "Resultado do spike" registrou.
- [ ] **Step 4: Rodar a suíte toda.** `uv run pytest -v`. Esperado: todos PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: agentes, callbacks de confirmação e App"`

---

### Task 7: Pendências e montagem da resposta

**Files:**
- Create: `src/aurora/confirmacoes.py`, `tests/test_confirmacoes.py`
- Modify: `tests/apoio.py` (construtores de eventos)

**Interfaces:**
- Consumes: `validacao.validar_area`, `validar_data`, `validar_nome` e `chave_nome`; `google.adk.events.Event`.
- Produces, em `aurora.confirmacoes`:
  - `NOME_CONFIRMACAO = "adk_request_confirmation"`;
  - `TEXTO_APROVE = "Para concluir, aprove a confirmação pendente."`;
  - `TEXTO_AVISO_FALHA = "Seu pedido foi registrado, mas não consegui concluir a resposta. Confira suas reservas e visitantes."`;
  - `@dataclass(frozen=True) class Pendente: id: str; acao: str; detalhes: dict[str, str]; id_chamada_original: str`;
  - `listar_pendentes(eventos: Sequence[Event], areas: Mapping[str, str]) -> list[Pendente]`. Segue a spec §9.1, na ordem das candidatas (evento e depois parte). Algoritmo:

```
candidatas = cada function_call NOME_CONFIRMACAO, em ordem de evento e de parte,
             com detalhes = normalizar(originalFunctionCall.name, originalFunctionCall.args)
respondidos = ids de toda function_response, de qualquer autor
percorra as candidatas da mais nova para a mais antiga; guarde a primeira de cada
  chave (acao, detalhes com "nome" passado por chave_nome); as demais estão substituídas
pendentes = as guardadas cujo id não está em respondidos, na ordem original
```

  - A normalização de `detalhes` é: `reservar_area` → `{"area": id, "data"}`; `autorizar_visitante` → `{"nome", "data"}`. Um valor inválido fica cru, como texto.
  - `encontrar_pendente(eventos, areas, id: str) -> Pendente | None`;
  - `acao_executada(eventos_emitidos: Sequence[Event], id_chamada_original: str) -> bool`: existe `function_response` com esse id num evento de autor diferente de `"user"` (spec §9.3);
  - `houve_efeito(eventos_emitidos: Sequence[Event]) -> bool`: alguma `function_response` de autor diferente de `"user"` tem `response["status"]` em `{"criada", "cancelada", "autorizado"}`;
  - `montar_resposta(eventos_emitidos: Sequence[Event], criou_pendente: bool) -> str`. Segue a spec §9.2. Para cada evento de autor diferente de `"user"` com `is_final_response()`:
    - se tiver partes de texto sem `thought`, usa o texto. É assim que chega a resposta do `AgentTool` com `skip_summarization` (`_caller.py` acrescenta a parte de texto);
    - senão, usa o `response["mensagem"]` de cada `function_response` que tenha `mensagem`;
    - ignora respostas com `"error"` (a "requires confirmation").
    - Junta as partes com `"\n\n"`, sem repetir uma igual à anterior. Se o resultado for vazio e `criou_pendente`, usa `TEXTO_APROVE`.
- Produces, em `tests/apoio.py`:
  - as constantes usadas também pela Task 8:
    - `AREAS`, igual ao da Task 2;
    - `SALAO = {"area": "Salão de festas", "data": "2030-04-20"}`;
    - `REQ = {"error": "This tool call requires confirmation, please approve or reject."}`;
  - `ev_pedido(id_conf, acao, args, id_original, autor="especialista_reservas") -> Event`: uma parte, `long_running_tool_ids={id_conf}`, e `args={"originalFunctionCall": {"id": id_original, "name": acao, "args": args}, "toolConfirmation": {"hint": "", "confirmed": False}}`;
  - `ev_pedidos(pares: list[tuple], autor=...) -> Event`: várias partes num evento;
  - `ev_resposta_usuario(id_conf, confirmado) -> Event`;
  - `ev_resposta_tool(id_chamada, nome, resposta: dict, autor="especialista_reservas", skip=False, texto=None) -> Event`;
  - `ev_texto(autor, texto, thought=False) -> Event`.

- [ ] **Step 1: Escrever os testes** (`tests/test_confirmacoes.py`; `AREAS`, `SALAO` e `REQ` vêm de `tests/apoio.py`)

```python
def test_pendente_simples():
    assert listar_pendentes([ev_pedido("c1", "reservar_area", SALAO, "o1")], AREAS) == [
        Pendente("c1", "reservar_area", {"area": "salao-de-festas", "data": "2030-04-20"}, "o1")]
def test_respondida_pelo_usuario_some():
    assert listar_pendentes([ev_pedido("c1", "reservar_area", SALAO, "o1"), ev_resposta_usuario("c1", False)], AREAS) == []
def test_encerrada_por_outro_autor_some():
    evs = [ev_pedido("c1", "reservar_area", SALAO, "o1"), ev_resposta_tool("c1", "adk_request_confirmation", {"aborted": True})]
    assert listar_pendentes(evs, AREAS) == []
def test_substituida_por_duplicata_mais_nova():
    evs = [ev_pedido("c1", "reservar_area", SALAO, "o1"), ev_pedido("c2", "reservar_area", {"area": "salao-de-festas", "data": "2030-04-20"}, "o2")]
    assert [p.id for p in listar_pendentes(evs, AREAS)] == ["c2"] and encontrar_pendente(evs, AREAS, "c1") is None
def test_duplicata_com_nome_em_outra_caixa_e_substituida():
    evs = [ev_pedido("c1", "autorizar_visitante", {"nome": "Joana Ribeiro", "data": "2030-04-21"}, "o1", autor="especialista_visitantes"),
           ev_pedido("c2", "autorizar_visitante", {"nome": "joana  RIBEIRO", "data": "2030-04-21"}, "o2", autor="especialista_visitantes")]
    assert [p.id for p in listar_pendentes(evs, AREAS)] == ["c2"]
def test_duplicatas_no_mesmo_evento():
    ev = ev_pedidos([("c1", "reservar_area", SALAO, "o1"), ("c2", "reservar_area", SALAO, "o2")])
    assert [p.id for p in listar_pendentes([ev], AREAS)] == ["c2"]
def test_diferentes_no_mesmo_evento_continuam():
    ev = ev_pedidos([("c1", "reservar_area", SALAO, "o1"), ("c2", "reservar_area", {"area": "churrasqueira", "data": "2030-06-02"}, "o2")])
    assert [p.id for p in listar_pendentes([ev], AREAS)] == ["c1", "c2"]
def test_nova_mensagem_nao_expira():
    evs = [ev_pedido("c1", "reservar_area", SALAO, "o1"), ev_texto("user", "outra coisa")]
    assert [p.id for p in listar_pendentes(evs, AREAS)] == ["c1"]
def test_ordem_invertida_apos_recarga():
    a, b = ev_resposta_tool("o1", "reservar_area", REQ, skip=True), ev_pedido("c1", "reservar_area", SALAO, "o1")
    assert [p.id for p in listar_pendentes([a, b], AREAS)] == ["c1"] == [p.id for p in listar_pendentes([b, a], AREAS)]
def test_negada_e_repetida_lista_so_a_nova():   # passos 7 → 8
    evs = [ev_pedido("c1", "reservar_area", SALAO, "o1"), ev_resposta_usuario("c1", False), ev_pedido("c2", "reservar_area", SALAO, "o2")]
    assert [p.id for p in listar_pendentes(evs, AREAS)] == ["c2"]
def test_acao_executada():
    feito = ev_resposta_tool("o1", "reservar_area", {"status": "criada", "mensagem": "ok"}, skip=True)
    assert acao_executada([feito], "o1") and not acao_executada([], "o1")
    assert not acao_executada([ev_resposta_usuario("c1", True)], "o1")
def test_houve_efeito():
    assert houve_efeito([ev_resposta_tool("o1", "reservar_area", {"status": "criada"})])
    assert not houve_efeito([ev_resposta_tool("o1", "reservar_area", {"status": "nao_confirmada"})])
def test_montar_resposta_texto(): assert montar_resposta([ev_texto("especialista_reservas", "Reserva feita.")], False) == "Reserva feita."
def test_montar_resposta_usa_mensagem_da_tool():
    assert montar_resposta([ev_resposta_tool("o1", "reservar_area", {"status": "criada", "mensagem": "Reserva confirmada."}, skip=True)], False) == "Reserva confirmada."
def test_montar_resposta_regulamento_sem_duplicar():
    ev = ev_resposta_tool("o9", "especialista_regulamento", {"result": "Fecha às 20h."}, autor="assistente_aurora", skip=True, texto="Fecha às 20h.")
    assert montar_resposta([ev], False) == "Fecha às 20h."
def test_montar_resposta_pendente_usa_texto_fixo():
    evs = [ev_resposta_tool("o1", "reservar_area", REQ, skip=True), ev_pedido("c1", "reservar_area", SALAO, "o1")]
    assert montar_resposta(evs, True) == "Para concluir, aprove a confirmação pendente."
def test_montar_resposta_vazia_e_pensamento():
    assert montar_resposta([], False) == ""
    assert montar_resposta([ev_texto("especialista_reservas", "rascunho", thought=True)], False) == ""
```

- [ ] **Step 2: Rodar.** `uv run pytest tests/test_confirmacoes.py -v`. Esperado: FAIL.
- [ ] **Step 3: Implementar** `confirmacoes.py` e os construtores em `tests/apoio.py`. Se o "Resultado do spike" mostrar outro formato para o evento final do `AgentTool`, ajuste `test_montar_resposta_regulamento_sem_duplicar` para o formato real **antes** de implementar.
- [ ] **Step 4: Rodar a suíte toda.** Esperado: todos PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: pendências derivadas dos eventos e montagem da resposta"`

---

### Task 8: API e servidor

**Files:**
- Create: `src/aurora/api.py`, `src/aurora/servidor.py`, `tests/test_api.py`
- Modify: `tests/apoio.py` (`RunnerFalso`)

**Interfaces:**
- Consumes: todos os módulos anteriores. Do ADK: `Runner`, `SqliteSessionService` (`google.adk.sessions.sqlite_session_service`) e `InMemorySessionService` (só nos testes).
- Produces:
  - `aurora.api.criar_api(runner=None, session_service=None) -> FastAPI`:
    - chama `config.carregar_ambiente()` **logo no início**, antes de montar o Runner, porque `criar_modelo()` lê `GEMINI_MODELO` ao construir os agentes;
    - o lifespan chama `banco.inicializar_se_necessario()`;
    - sem injeção, cria `SqliteSessionService(str(config.caminho_sessoes()))` e `Runner(app=agentes.criar_app(), session_service=...)`;
    - `app_name="aurora"`;
    - um `asyncio.Lock` por `session_id`.
  - Modelos de entrada (pydantic), que dão `422` automaticamente:
    - `NovaSessao(apartamento: str)`;
    - `NovaMensagem(texto: str)`, com validador que recusa texto vazio depois do `strip`;
    - `RespostaDeConfirmacao(id: str, confirmado: bool)`.
  - Saída de mensagens e confirmações: `{"resposta": str, "confirmacoes_pendentes": [{"id", "acao", "detalhes"}]}`.
  - `aurora.servidor.main() -> None`: `uvicorn.run(criar_api(), host="127.0.0.1", port=8000)`, sem reload.
  - `tests/apoio.RunnerFalso(session_service)`, com:
    - `roteiros: list[list[Event]]`;
    - `erro_depois: int | None`, que lança `RuntimeError` depois de emitir esse número de eventos;
    - `chamadas: int`;
    - `run_async(user_id, session_id, new_message)`, que grava o evento do usuário e os eventos do próximo roteiro via `session_service.append_event`, emitindo cada um.
  - Em `tests/test_api.py`:
    - as fixtures `runner(banco)` (`RunnerFalso(InMemorySessionService())`) e `cliente(runner)` (`TestClient(criar_api(runner=runner, session_service=runner.session_service))`);
    - o helper `nova_sessao(cliente, apto="101") -> str`;
    - o helper `criar_pendencia(cliente, runner, sid)`, que roda a mensagem do salão com o roteiro `[ev_resposta_tool("o1", "reservar_area", REQ, skip=True), ev_pedido("c1", "reservar_area", SALAO, "o1")]`.

**Comportamento das rotas:** spec §9.
- `POST /sessoes`: `422` se `not repositorio.apartamento_existe`. Depois `create_session(app_name="aurora", user_id=apto, state={"apartamento": apto})`, `registrar_sessao` e `201 {"session_id"}`.
- Rotas com sessão: `apto = repositorio.apartamento_da_sessao_id(sid)`. Se for `None`, ou se `get_session` devolver `None`, responde `404`.
- `POST /mensagens`: dentro do lock, coleta os eventos emitidos. Se houver exceção:
  - com `houve_efeito(emitidos)`, `resposta = TEXTO_AVISO_FALHA` e status `200`;
  - sem efeito, `503`.
  - `criou_pendente` = algum evento emitido com `function_call` `NOME_CONFIRMACAO`.
  - Depois relê a sessão e responde com `montar_resposta` e `listar_pendentes(session.events, repositorio.mapa_areas())`.
- `POST /confirmacoes`, dentro do lock, nesta ordem:
  1. `encontrar_pendente`; se for `None`, `409` sem chamar o Runner;
  2. roda o Runner com a `FunctionResponse` da spec §9;
  3. se `not acao_executada(emitidos, pendente.id_chamada_original)`, `logging.error` e `500`;
  4. caso contrário, `200`.
- `GET /eventos`: `[e.model_dump(mode="json", by_alias=True, exclude_none=True) for e in session.events]`.
- `GET /apartamentos/{n}/reservas` e `/visitantes`: listas do repositório nos formatos do contrato.

- [ ] **Step 1: Escrever os testes** (`tests/test_api.py`: `TestClient(criar_api(runner=RunnerFalso(ss), session_service=ss))` com `ss = InMemorySessionService()` e a fixture `banco`)

```python
def test_criar_sessao_e_eventos_vazios(cliente):
    r = cliente.post("/sessoes", json={"apartamento": "101"}); assert r.status_code == 201
    assert cliente.get(f"/sessoes/{r.json()['session_id']}/eventos").json() == []
def test_entradas_malformadas(cliente, runner):
    assert cliente.post("/sessoes", json={"apartamento": "999"}).status_code == 422
    assert cliente.post("/sessoes", json={}).status_code == 422
    sid = nova_sessao(cliente)
    assert cliente.post(f"/sessoes/{sid}/mensagens", json={"texto": "   "}).status_code == 422
    assert cliente.post(f"/sessoes/{sid}/mensagens", json={}).status_code == 422
    assert runner.chamadas == 0
def test_sessao_inexistente_404(cliente):
    assert cliente.get("/sessoes/sessao-inexistente/eventos").status_code == 404
    assert cliente.post("/sessoes/x/mensagens", json={"texto": "oi"}).status_code == 404
    assert cliente.post("/sessoes/x/confirmacoes", json={"id": "a", "confirmado": True}).status_code == 404
def test_pendencia_aprovacao_e_reenvio(cliente, runner):
    sid = nova_sessao(cliente)
    runner.roteiros.append([ev_resposta_tool("o1", "reservar_area", REQ, skip=True), ev_pedido("c1", "reservar_area", SALAO, "o1")])
    r = cliente.post(f"/sessoes/{sid}/mensagens", json={"texto": "Reserve o salão de festas para 2030-04-20."}).json()
    assert r == {"resposta": "Para concluir, aprove a confirmação pendente.", "confirmacoes_pendentes": [
        {"id": "c1", "acao": "reservar_area", "detalhes": {"area": "salao-de-festas", "data": "2030-04-20"}}]}
    runner.roteiros.append([ev_resposta_tool("o1", "reservar_area", {"status": "criada", "mensagem": "Reserva confirmada."}, skip=True)])
    r = cliente.post(f"/sessoes/{sid}/confirmacoes", json={"id": "c1", "confirmado": True})
    assert r.status_code == 200 and r.json() == {"resposta": "Reserva confirmada.", "confirmacoes_pendentes": []}
    chamadas = runner.chamadas
    assert cliente.post(f"/sessoes/{sid}/confirmacoes", json={"id": "c1", "confirmado": True}).status_code == 409
    assert runner.chamadas == chamadas
def test_id_inexistente_409_sem_runner(cliente, runner):
    sid = nova_sessao(cliente)
    assert cliente.post(f"/sessoes/{sid}/confirmacoes", json={"id": "id-inexistente", "confirmado": True}).status_code == 409
    assert runner.chamadas == 0
def test_aprovacao_que_nao_executa_vira_500(cliente, runner):
    sid = nova_sessao(cliente); criar_pendencia(cliente, runner, sid)
    runner.roteiros.append([])
    assert cliente.post(f"/sessoes/{sid}/confirmacoes", json={"id": "c1", "confirmado": True}).status_code == 500
def test_falha_do_modelo_sem_efeito_503(cliente, runner):
    sid = nova_sessao(cliente)
    runner.roteiros.append([]); runner.erro_depois = 0
    assert cliente.post(f"/sessoes/{sid}/mensagens", json={"texto": "oi"}).status_code == 503
def test_falha_do_modelo_com_efeito_200(cliente, runner):
    sid = nova_sessao(cliente)
    runner.roteiros.append([ev_resposta_tool("o2", "reservar_area", {"status": "criada", "mensagem": "ok"})]); runner.erro_depois = 1
    r = cliente.post(f"/sessoes/{sid}/mensagens", json={"texto": "Reserve a quadra para 2030-04-06."})
    assert r.status_code == 200 and r.json()["resposta"] == TEXTO_AVISO_FALHA
def test_rotas_de_verificacao(cliente):
    assert cliente.get("/apartamentos/101/reservas").json() == [{"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}]
    assert cliente.get("/apartamentos/302/visitantes").json() == [{"nome": "Marina Duarte", "data": "2030-03-16"}]
```

- [ ] **Step 2: Rodar.** `uv run pytest tests/test_api.py -v`. Esperado: FAIL.
- [ ] **Step 3: Implementar** `api.py`, `servidor.py` e o `RunnerFalso`.
- [ ] **Step 4: Rodar a suíte toda.** Esperado: todos PASS.
- [ ] **Step 5: Fumaça com o modelo de verdade:**
  1. `uv run restaurar`;
  2. `uv run api` em segundo plano;
  3. `curl -s -X POST localhost:8000/sessoes -H "content-type: application/json" -d '{"apartamento":"101"}'`: esperado `201` com `session_id`;
  4. enviar "Reserve a quadra para 2030-04-06." para essa sessão: esperado `200` com `confirmacoes_pendentes: []`;
  5. parar a API.
- [ ] **Step 6: Commit.** `git commit -m "feat: API FastAPI com sessões persistidas e confirmações"`

---

### Task 9: Suíte de integração (pilha real, Gemini falso)

Implementa a D24. Requisições pela API, com o Runner, os agentes, as tools, os callbacks e os dois bancos SQLite reais, numa pasta temporária. Só o Gemini é substituído, na fronteira.

**Files:**
- Create: `tests/integracao/__init__.py`, `tests/integracao/modelo_roteirizado.py`, `tests/integracao/conftest.py`, `tests/integracao/test_fluxos.py`

**Interfaces:**
- Consumes:
  - `api.criar_api(runner=..., session_service=...)` e `agentes.criar_app(modelo=...)`;
  - `banco.garantir_esquema()` e `restaurar_dados()`; `repositorio.*`;
  - do ADK: `Runner`, `SqliteSessionService`, `BaseLlm`, `LlmRequest` e `LlmResponse`.
- Produces (só testes):
  - `ModeloRoteirizado(BaseLlm)`, em `modelo_roteirizado.py`:
    - `roteiro(*respostas: LlmResponse)` acrescenta respostas à fila;
    - `generate_content_async(llm_request, stream=False)` consome uma resposta por chamada e falha com uma mensagem clara se a fila acabar;
    - `chamadas: list[set[str]]` guarda, por chamada, os nomes das tools visíveis em `llm_request.tools_dict`. É assim que o teste descobre qual agente chamou o modelo: só o principal vê `especialista_regulamento`.
  - Helpers `chamar(nome: str, **args) -> LlmResponse` (uma parte `function_call` com id único) e `responder(texto: str) -> LlmResponse`.
  - A fixture `pilha(tmp_path, monkeypatch)`, em `conftest.py`:
    - faz `AURORA_DIR_VAR=tmp_path`, `garantir_esquema()` e `restaurar_dados()`;
    - cria um `ModeloRoteirizado` e monta `criar_api(runner=Runner(app=criar_app(modelo=m), session_service=ss), session_service=ss)`, com `ss = SqliteSessionService(str(tmp_path / "sessoes.db"))`;
    - expõe `modelo`, `nova_sessao(apto) -> str`, `mensagem(sid, texto) -> dict` (que exige `200`), `confirmar(sid, id, confirmado) -> httpx.Response` e `eventos(sid) -> list`;
    - expõe `reiniciar()`, que monta um `SqliteSessionService`, um `Runner` e uma API novos sobre os mesmos arquivos, com o mesmo modelo. É o reinício da Garantia 3.
    - Use `httpx.AsyncClient(transport=httpx.ASGITransport(app=...))` para permitir requisições paralelas.

- [ ] **Step 1: Escrever os testes** (`tests/integracao/test_fluxos.py`). O roteiro de cada mensagem segue a D14: a primeira chamada é do principal (transferência ou `AgentTool`), as seguintes são do especialista.

```python
SALAO = (chamar("transfer_to_agent", agent_name="especialista_reservas"),
         chamar("reservar_area", area="Salão de festas", data="2030-04-20"))

def test_reserva_com_taxa_aprovada_apos_reinicio(pilha):
    sid = pilha.nova_sessao("101"); pilha.modelo.roteiro(*SALAO)
    [p] = pilha.mensagem(sid, "Reserve o salão de festas para 2030-04-20.")["confirmacoes_pendentes"]
    assert p["acao"] == "reservar_area" and p["detalhes"] == {"area": "salao-de-festas", "data": "2030-04-20"}
    assert repositorio.data_disponivel("salao-de-festas", "2030-04-20")
    n_eventos, n_chamadas = len(pilha.eventos(sid)), len(pilha.modelo.chamadas)
    pilha.reiniciar()
    assert len(pilha.eventos(sid)) == n_eventos
    r = pilha.confirmar(sid, p["id"], True)
    assert r.status_code == 200 and r.json()["confirmacoes_pendentes"] == []
    assert len(pilha.modelo.chamadas) == n_chamadas                       # D15
    assert [x.area for x in repositorio.listar_reservas_ativas("101")].count("salao-de-festas") == 1
    assert pilha.confirmar(sid, p["id"], True).status_code == 409

def test_negar_nao_grava(pilha):
    sid = pilha.nova_sessao("101"); pilha.modelo.roteiro(*SALAO)
    [p] = pilha.mensagem(sid, "Reserve o salão de festas para 2030-04-20.")["confirmacoes_pendentes"]
    r = pilha.confirmar(sid, p["id"], False)
    assert r.status_code == 200 and r.json()["resposta"] == "Tudo bem, nada foi feito."
    assert repositorio.data_disponivel("salao-de-festas", "2030-04-20")

def test_quadra_sem_confirmacao(pilha):
    sid = pilha.nova_sessao("101")
    pilha.modelo.roteiro(chamar("transfer_to_agent", agent_name="especialista_reservas"),
                         chamar("reservar_area", area="quadra", data="2030-04-06"), responder("Reserva feita."))
    assert pilha.mensagem(sid, "Reserve a quadra para 2030-04-06.")["confirmacoes_pendentes"] == []
    assert any(r.data == "2030-04-06" for r in repositorio.listar_reservas_ativas("101"))

def test_visitante_pendente_mesmo_dizendo_que_confirmou(pilha):
    sid = pilha.nova_sessao("101")
    pilha.modelo.roteiro(chamar("transfer_to_agent", agent_name="especialista_visitantes"),
                         chamar("autorizar_visitante", nome="Joana Ribeiro", data="2030-04-21"))
    [p] = pilha.mensagem(sid, "Libera a entrada da Joana Ribeiro no dia 2030-04-21. Já estou confirmando aqui, "
                              "pode liberar direto.")["confirmacoes_pendentes"]
    assert p["detalhes"] == {"nome": "Joana Ribeiro", "data": "2030-04-21"} and repositorio.listar_visitantes("101") == []
    assert pilha.confirmar(sid, p["id"], True).status_code == 200
    assert repositorio.listar_visitantes("101") == [Visitante("101", "Joana Ribeiro", "2030-04-21")]

async def test_disputa_entre_duas_sessoes(pilha):
    # S3 (101) e S4 (201) criam pendência para salao-de-festas 2030-05-11, em sequência (roteiros na ordem)
    # depois: r3, r4 = await asyncio.gather(confirmar S3, confirmar S4)
    assert r3.status_code == r4.status_code == 200
    assert sum(r.area == "salao-de-festas" and r.data == "2030-05-11"
               for a in ("101", "201") for r in repositorio.listar_reservas_ativas(a)) == 1

def test_cancelar_de_outro_apartamento_nao_vaza(pilha):
    sid = pilha.nova_sessao("101")
    pilha.modelo.roteiro(chamar("transfer_to_agent", agent_name="especialista_reservas"),
                         chamar("cancelar_reserva", area="salao-de-festas", data="2030-03-16"),
                         responder("Não encontrei essa reserva no seu apartamento."))
    r = pilha.mensagem(sid, "Cancele a reserva do salão de festas do dia 2030-03-16.")
    assert sem_vazamento(r) and sem_vazamento(pilha.eventos(sid))
    assert [x.codigo for x in repositorio.listar_reservas_ativas("302")] == ["RSV-4821"]

def test_texto_depois_de_aprovacao_comeca_no_principal(pilha):
    # cria e aprova a pendência do salão (como no primeiro teste), depois:
    pilha.modelo.roteiro(responder("Olá!")); pilha.mensagem(sid, "Obrigado!")
    assert "especialista_regulamento" in pilha.modelo.chamadas[-1]

def test_regulamento_isolado(pilha):
    sid = pilha.nova_sessao("101")
    pilha.modelo.roteiro(chamar("especialista_regulamento", request="Até que horas a piscina funciona aos domingos?"),
                         chamar("buscar_no_regulamento", pergunta="horário da piscina no domingo"),
                         responder("Aos domingos e feriados, a piscina fecha às 20h."))
    r = pilha.mensagem(sid, "Até que horas a piscina funciona aos domingos?")
    assert "20h" in r["resposta"] and len(pilha.modelo.chamadas) == 3          # D21: o turno termina no especialista
    texto = json.dumps(pilha.eventos(sid), ensure_ascii=False)
    assert "no máximo quatro convidados" not in texto                         # artigo bruto da busca não vaza
```

  Os testes `async` usam `asyncio.run` dentro de um teste síncrono, ou `anyio`, que já vem com o FastAPI. `sem_vazamento` e `Visitante` vêm de `tests/apoio.py` e `aurora.repositorio`.

- [ ] **Step 2: Rodar.** `uv run pytest tests/integracao -v`. Os testes devem passar com o código das Tasks 2 a 8. Uma falha aqui é bug de integração: use `superpowers:systematic-debugging`, acrescente um teste de unidade na suíte da task dona do código e corrija lá.
- [ ] **Step 3: Rodar a suíte toda.** `uv run pytest -v`. Esperado: todos PASS.
- [ ] **Step 4: Commit.** `git commit -m "test: suíte de integração pela pilha real com Gemini falso"`

---

### Task 10: Roteiro do avaliador (ponta a ponta, com modelo)

**Files:**
- Create: `scripts/roteiro_avaliador.py`

**Interfaces:**
- Consumes: os comandos `uv run restaurar` e `uv run api` e a API em `http://localhost:8000`.
- Produces: `uv run python scripts/roteiro_avaliador.py [--so-readme]`, que imprime `PASS`/`FAIL` por verificação e sai com código 1 se alguma falhar. A opção `--so-readme` é usada na Task 11.

- [ ] **Step 1: Escrever o script.**
  - **Estrutura:**
    - roda `uv run restaurar`;
    - sobe `uv run api` como subprocesso e espera a porta responder;
    - executa os passos 2 a 14 do enunciado com `httpx`, conferindo **cada verificação** listada em `git show be87e1d:README.md`, seção "Fluxo do avaliador";
    - no passo 13, encerra o subprocesso e sobe de novo com o mesmo comando, sem restaurar;
    - no passo 14, envia as duas aprovações em paralelo (`asyncio.gather` com `httpx.AsyncClient`).
  - **Helper `enviar(sid, texto, espera_pendencia)`:** se uma pendência era esperada e não veio, responde "Sim, pode seguir." até 2 vezes, como o avaliador pode fazer.
  - **Verificações exatas:**
    - "302 isolado": `(?<!\d)302(?!\d)` no texto das respostas;
    - "trechos de outros capítulos" (passo 12): nenhuma frase com 40 caracteres ou mais, de artigos de capítulos diferentes do IV, aparece no JSON de `GET /sessoes/{S1}/eventos`;
    - "chamadas de tool" (passo 12): os eventos de S1 contêm `functionCall` de `reservar_area`, `cancelar_reserva` e `autorizar_visitante`;
    - passo 13: a contagem de eventos é igual antes e depois do reinício; os códigos novos casam `RSV-N[A-Z]{8}`, são distintos entre si e diferentes de `RSV-1377`, `RSV-4821` e `RSV-2950`.
  - **Checagens extras:**
    - `git diff --exit-code be87e1d -- dados/`;
    - `git ls-files .env` vazio;
    - `.env.example` sem nenhum valor depois de `=`.
  - **`--so-readme`:** cada referência `caminho.py::nome` no `README.md` aponta para um arquivo existente que contém `def nome` ou `nome =`.
- [ ] **Step 2: Rodar.** `uv run python scripts/roteiro_avaliador.py`. Esperado: todas as verificações PASS e código de saída 0.
- [ ] **Step 3: Se algo falhar,** use a skill `superpowers:systematic-debugging`. Para cada correção:
  - acrescente um teste que reproduza a falha na suíte da task dona do código;
  - rode `uv run pytest`;
  - rode o roteiro de novo.

  Falha de cota repetida aplica o critério de troca da D8: trocar `MODELO_PADRAO` e registrar o motivo aqui.
- [ ] **Step 4: Commit.** `git commit -m "test: roteiro automático do fluxo do avaliador"` (mais as correções, cada uma no seu próprio commit)

---

### Task 11: README da entrega

**Files:**
- Create: `docs/enunciado.md`
- Modify: `README.md` (substituído por inteiro)

**Interfaces:**
- Consumes: os nomes reais de arquivos e funções das Tasks 2 a 9.

- [ ] **Step 1: Copiar o enunciado em UTF-8.** Não use o redirecionamento do PowerShell, que muda a codificação:

```
uv run python -c "import subprocess, pathlib; pathlib.Path('docs/enunciado.md').write_bytes(subprocess.check_output(['git', 'show', 'be87e1d:README.md']))"
```

- [ ] **Step 2: Escrever o `README.md`** com exatamente estas seções:
  - **Arquitetura:** os 4 agentes, cada um com responsabilidade, forma de acionamento (transferência ou `AgentTool`) e motivo (spec §6). Inclui por que `AgentTool` e não `mode="single_turn"`, por que as transferências dos especialistas são bloqueadas e um diagrama simples.
  - **Garantias:** uma subseção por garantia, cada uma com:
    - as referências no formato `src/aurora/<arquivo>.py::<funcao>`;
    - um trecho curto do código;
    - o "por que não depende do modelo" (spec §11).
  - **Como rodar:**
    - pré-requisito `uv`;
    - `cp .env.example .env`, com `GOOGLE_API_KEY` obrigatória e `GEMINI_MODELO` opcional, explicando a troca para `gemini-2.5-flash` (ou o alternativo registrado) se a cota acabar;
    - os comandos `uv sync`, `uv run restaurar` e `uv run api`;
    - o que a restauração faz e o que não faz (não apaga sessões);
    - `uv run pytest` e `uv run python scripts/roteiro_avaliador.py`.
- [ ] **Step 3: Conferir as referências.** `uv run python scripts/roteiro_avaliador.py --so-readme`. Esperado: PASS.
- [ ] **Step 4: Commit.** `git add README.md docs/enunciado.md` e `git commit -m "docs: README da entrega e cópia do enunciado"`

---

### Task 12: Finalização

**Files:** nenhum novo.

- [ ] **Step 1: Verificação final.**
  - `uv run pytest`: tudo PASS;
  - `uv run python scripts/roteiro_avaliador.py`: código 0;
  - `git diff --exit-code be87e1d -- dados/`: sem saída;
  - `git status`: limpo.
- [ ] **Step 2: Integrar.** Use a skill `superpowers:finishing-a-development-branch` para levar `feat/assistente-aurora` à `main`. **Antes do merge e antes de qualquer `git push`, peça autorização explícita ao usuário.**

---

## Resultado do spike

_(Preenchido na Task 1, Step 5.)_
