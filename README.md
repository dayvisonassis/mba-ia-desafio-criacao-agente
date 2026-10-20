# Residencial Aurora: assistente virtual do condomínio

Assistente de chat do Residencial Aurora, feito com Google ADK 2.12.0 e exposto por uma API FastAPI em `http://localhost:8000`.
O modelo conduz a conversa, e as regras do condomínio ficam no código: tools, callbacks, banco e API.

## Arquitetura

O morador fala com um agente principal, que encaminha cada pedido a um de três especialistas. Os quatro são `LlmAgent` do
ADK e usam o mesmo modelo Gemini, com novas tentativas automáticas para os erros `429` e `503`
(`src/aurora/agentes.py::criar_modelo`). A API mantém um único `Runner` sobre o App `aurora`
(`src/aurora/agentes.py::criar_app`). Sessões e dados ficam em dois arquivos SQLite.

```
                  cliente (avaliador, curl)
                             |  JSON
                             v
              API FastAPI (src/aurora/api.py)
               |                           |
               | Runner do ADK             | rotas de verificação:
               | (App "aurora")            | leem var/aurora.db direto,
               v                           | sem passar pelo modelo
  assistente_aurora (principal)
    |
    +-- subagente especialista_reservas ---> tools ---> var/aurora.db
    |
    +-- subagente especialista_visitantes -> tools ---> var/aurora.db
    |
    +-- tool AgentTool(especialista_regulamento)
          sessão própria, em memória
          |
          +-- tool buscar_no_regulamento -------------> dados/regulamento.md

  Sessões e eventos: SqliteSessionService ------------> var/sessoes.db
```

### Os agentes

#### `assistente_aurora` (principal)

- **Responsabilidade:** recebe toda mensagem de texto do morador e encaminha o pedido. Não tem tools de dados nem o
  regulamento nas instruções (`src/aurora/agentes.py::INSTRUCAO_PRINCIPAL`).
- **Como é acionado:** é o `root_agent` do App. Toda mensagem de texto nova começa nele.
- **Como aciona os especialistas:** transfere a conversa para `especialista_reservas` ou `especialista_visitantes`
  (`transfer_to_agent`) e chama `especialista_regulamento` como ferramenta.
- **Por quê:** um ponto de entrada único deixa o roteamento previsível. O principal só decide o assunto. Quem lê e grava
  dados são as tools dos especialistas.

#### `especialista_reservas` (subagente, por transferência)

- **Responsabilidade:** dizer se uma data está livre e listar, criar e cancelar as reservas do apartamento da sessão. As
  tools são `listar_minhas_reservas`, `verificar_disponibilidade`, `reservar_area` e `cancelar_reserva`
  (`src/aurora/ferramentas.py::FERRAMENTAS_RESERVAS`).
- **Como é acionado:** por transferência. Ele está em `sub_agents` do principal.
- **Por quê:** `reservar_area` pede confirmação nas áreas com taxa. O ADK só devolve a aprovação a um agente que ele
  encontra na árvore de subagentes (ver as decisões abaixo). A instrução lista as áreas válidas, lidas do banco no momento
  em que a instrução é montada (`src/aurora/agentes.py::instrucao_reservas`).

#### `especialista_visitantes` (subagente, por transferência)

- **Responsabilidade:** listar e autorizar os visitantes do apartamento da sessão. As tools são `listar_meus_visitantes`
  e `autorizar_visitante` (`src/aurora/ferramentas.py::FERRAMENTAS_VISITANTES`).
- **Como é acionado:** por transferência, como o de reservas.
- **Por quê:** `autorizar_visitante` sempre pede confirmação, então vale o mesmo motivo do especialista de reservas.

#### `especialista_regulamento` (ferramenta, via `AgentTool`)

- **Responsabilidade:** responder dúvidas com base em `dados/regulamento.md`. A tool é `buscar_no_regulamento`
  (`src/aurora/ferramentas.py::FERRAMENTA_REGULAMENTO`).
- **Como é acionado:** o principal o chama como ferramenta, com `AgentTool(regulamento, skip_summarization=True)`
  (`src/aurora/agentes.py::criar_agente_principal`).
- **Por quê:** o `AgentTool` roda o especialista num `Runner` separado, com um `InMemorySessionService` próprio. Os
  artigos devolvidos pela busca ficam nessa sessão descartável. Na sessão principal entra só a resposta final do
  especialista. Com `skip_summarization=True`, essa resposta encerra o turno sem o principal reescrevê-la. Isso economiza
  uma chamada ao modelo e mantém o horário como está escrito no regulamento ("20h").

### Decisões sobre os especialistas

- **Três especialistas, um por assunto.** Reservas, visitantes e regulamento têm dados e tools diferentes, e cada
  especialista vê só as tools do seu assunto. O regulamento fica num especialista à parte para o texto dele não entrar na
  sessão principal.
- **As tools com confirmação ficam em subagentes.** Quando o morador responde a uma confirmação, o Runner manda a resposta
  ao agente que fez a chamada original. Ele procura esse agente pelo nome, com `root_agent.find_agent`, que percorre só os
  subagentes. Um agente que existe apenas dentro de um `AgentTool` não é encontrado, e a aprovação não chegaria à tool. Pelo
  mesmo motivo, os nomes dos agentes são fixos: as pendências gravadas apontam o autor pelo nome.
- **As transferências dos especialistas são bloqueadas** (`disallow_transfer_to_parent=True` e
  `disallow_transfer_to_peers=True`). Numa mensagem de texto nova, o ADK volta ao último agente que respondeu se ele puder
  transferir. Se ele não puder, a mensagem vai ao principal. Com o bloqueio, toda mensagem de texto começa no principal, e a
  pergunta sobre a piscina nunca fica presa no especialista de visitantes. A aprovação não depende disso: ela vai ao autor
  da chamada pelo nome, mesmo que ele não possa transferir. O custo é cerca de uma chamada a mais ao modelo por mensagem.
  Numa mensagem com dois assuntos, o especialista do primeiro atende a parte dele e diz que o outro assunto pode ser pedido
  em seguida.
- **O App não usa `ResumabilityConfig`.** Com a retomada ligada, o ADK também mandaria ao especialista a mensagem de texto
  seguinte a uma aprovação, e ela deixaria de começar no principal.
- **`AgentTool`, e não `mode="single_turn"`.** A documentação do `AgentTool` no ADK desencoraja o uso direto e sugere um
  subagente com `mode="single_turn"`. Esse modo roda o especialista dentro da sessão do pai. A chamada a
  `buscar_no_regulamento` e os artigos devolvidos virariam eventos da sessão principal e acompanhariam todas as mensagens
  seguintes. Isso quebraria a Garantia 4.

### Armazenamento

- **`var/aurora.db`:** dados do condomínio (apartamentos, áreas, reservas e visitantes), os códigos de reserva já
  emitidos e a ligação entre cada sessão e o seu apartamento. O acesso usa o `sqlite3` da biblioteca padrão, com uma
  conexão por operação e transações curtas (`src/aurora/banco.py::conectar`).
- **`var/sessoes.db`:** sessões e eventos, gravados pelo `SqliteSessionService` do próprio ADK.
- **Por que SQLite:** não precisa de Docker nem de serviço externo, e o índice único parcial resolve a disputa por uma
  data no próprio banco (Garantia 5). Os dois arquivos separam os nossos dados do esquema interno do ADK e reduzem a
  disputa pela trava de escrita.
- Uma reserva cancelada não é apagada. Ela muda para `status = 'cancelada'` e libera a data.
- O código de uma reserva nova é `RSV-N` seguido de 8 consoantes sorteadas (`src/aurora/repositorio.py::gerar_codigo`)
  e fica registrado na tabela `codigos_emitidos`. Sem dígitos, ele nunca contém o número de um apartamento. A tabela
  impede repetir qualquer código já usado, inclusive o de uma reserva cancelada.
- A pasta `var/` fica fora do Git.

### API

A API (`src/aurora/api.py::criar_api`) segue o contrato do enunciado:

- `POST /sessoes`, `POST /sessoes/{session_id}/mensagens` e `POST /sessoes/{session_id}/confirmacoes`;
- `GET /sessoes/{session_id}/eventos`;
- as rotas de verificação `GET /apartamentos/{numero}/reservas` e `GET /apartamentos/{numero}/visitantes`, que leem o
  banco direto, sem passar pelo modelo.

Outros pontos:

- A rota de mensagens aceita só texto. Só a rota de confirmações monta a resposta que o ADK espera para uma confirmação.
- Um `asyncio.Lock` por sessão serializa as mensagens e as confirmações da mesma sessão. Sessões diferentes rodam em
  paralelo.
- `confirmacoes_pendentes` é calculada a cada resposta a partir dos eventos gravados
  (`src/aurora/confirmacoes.py::listar_pendentes`).
- Fora do contrato: `422` para apartamento inexistente na criação da sessão ou para texto vazio; `503` quando o modelo
  falha antes de qualquer efeito; `500` se uma aprovação não chegar à tool.

### Arquivos

| Arquivo | Conteúdo |
|---|---|
| `src/aurora/config.py` | Caminhos, leitura do `.env`, nome do modelo e AI Studio forçado |
| `src/aurora/validacao.py` | Validação e normalização de área, data e nome |
| `src/aurora/banco.py` | Esquema SQLite, conexão, transação e carga inicial |
| `src/aurora/repositorio.py` | Consultas e gravações de reservas, visitantes, áreas e sessões |
| `src/aurora/regulamento.py` | Divisão do regulamento em capítulos e artigos, e a busca |
| `src/aurora/ferramentas.py` | As tools e as funções que decidem se uma chamada pede confirmação |
| `src/aurora/agentes.py` | Os quatro agentes, os callbacks e o App |
| `src/aurora/confirmacoes.py` | Pendências derivadas dos eventos e montagem de `resposta` |
| `src/aurora/api.py` | A API FastAPI |
| `src/aurora/servidor.py` | O comando `uv run api` |
| `src/aurora/restaurar.py` | O comando `uv run restaurar` |
| `tests/` | Testes de unidade e a suíte de integração (`tests/integracao/`) |
| `scripts/roteiro_avaliador.py` | Reproduz o fluxo do avaliador com o modelo real |

## Garantias

Cada garantia aponta as funções que a implementam, no formato `caminho::nome`, e mostra trechos do código. Algumas
funções da API, como a rota `responder_confirmacao` e o helper `trava`, ficam dentro de `criar_api`. O comando
`uv run python scripts/roteiro_avaliador.py --so-readme` confere que todas as referências deste README existem.

### 1. Cobrança ou acesso só com confirmação

**Onde está:**

- `src/aurora/ferramentas.py::precisa_confirmar_reserva` e `src/aurora/ferramentas.py::precisa_confirmar_visitante`:
  as funções passadas a `require_confirmation` em `src/aurora/ferramentas.py::FERRAMENTAS_RESERVAS` e
  `src/aurora/ferramentas.py::FERRAMENTAS_VISITANTES`. A da reserva pede confirmação só quando a área tem taxa maior que
  zero no banco. A do visitante pede sempre que o nome e a data são válidos.
- `src/aurora/ferramentas.py::reservar_area` e `src/aurora/ferramentas.py::autorizar_visitante`: a segunda verificação,
  no corpo da tool, com `src/aurora/ferramentas.py::_aprovada`. Sem aprovação, a tool não grava.
- `src/aurora/agentes.py::depois_da_tool_especialista`: depois de aprovar ou negar, encerra o turno sem nova chamada ao
  modelo. Na negação, troca a resposta por "Tudo bem, nada foi feito."
- `src/aurora/confirmacoes.py::listar_pendentes` e `src/aurora/confirmacoes.py::encontrar_pendente`: as pendências são
  os eventos `adk_request_confirmation` da sessão que ainda não têm resposta.
- `src/aurora/api.py::responder_confirmacao`: responde `409` antes de rodar o Runner quando o `id` não está pendente.
  Depois de rodar, confere com `src/aurora/confirmacoes.py::acao_executada` que a tool executou. Se não executou,
  responde `500` em vez de um `200` enganoso.
- `src/aurora/banco.py::ESQUEMA_SQL`: a coluna `chamada_id TEXT UNIQUE` em `reservas` e `visitantes`.
  `src/aurora/repositorio.py::criar_reserva` e `src/aurora/repositorio.py::autorizar_visitante` procuram esse id antes
  de gravar e, se ele já existir, devolvem o registro gravado.

As tools de reservas, em `src/aurora/ferramentas.py`:

```python
FERRAMENTAS_RESERVAS: list[FunctionTool] = [
    FunctionTool(listar_minhas_reservas),
    FunctionTool(verificar_disponibilidade),
    FunctionTool(reservar_area, require_confirmation=precisa_confirmar_reserva),
    FunctionTool(cancelar_reserva),
]
```

A segunda verificação, em `reservar_area`:

```python
    if dados_area.taxa > 0 and not _aprovada(tool_context):
        return {
            "status": "nao_confirmada",
            "mensagem": "A reserva exige a aprovação do morador e nada foi gravado.",
        }
```

O `409`, em `responder_confirmacao`:

```python
            pendente = encontrar_pendente(
                sessao.events, repositorio.mapa_areas(), corpo.id
            )
            if pendente is None:
                raise HTTPException(
                    status_code=409,
                    detail="Não há confirmação pendente com esse id nesta sessão.",
                )
```

**Por que não depende do modelo:**

- O modelo escolhe só a tool e os argumentos. Quem decide se a chamada precisa de confirmação é o código, com a taxa lida
  do banco.
- A aprovação só nasce na rota de confirmações, como uma resposta montada pela API. A rota de mensagens aceita só texto,
  então "já estou confirmando aqui" continua sendo texto e não aprova nada.
- Se a configuração do `FunctionTool` falhasse, o corpo da tool ainda se recusaria a gravar sem aprovação.
- Um `id` que não está pendente (desconhecido, já respondido ou substituído) recebe `409` antes de qualquer execução.
- Aprovar executa uma única vez. O reenvio recebe `409`, e o banco não grava duas vezes o mesmo `chamada_id`.
- Negar não executa a tool. O turno termina sem o modelo, que não tem como chamar a tool de novo nesse turno.
- Uma pendência não expira com mensagens novas: ela continua exigindo a aprovação pela rota. Se o modelo pedir duas vezes
  a mesma ação com os mesmos detalhes, só a pendência mais nova fica listada, e a anterior passa a receber `409`.
- Uma área sem taxa e o cancelamento não pedem confirmação, porque não geram cobrança nem liberam acesso.

### 2. Cada sessão pertence a um apartamento

**Onde está:**

- `src/aurora/api.py::criar_sessao`: a rota `POST /sessoes` grava o apartamento no state da sessão do ADK, usa o mesmo
  valor como `user_id` e registra a ligação com `src/aurora/repositorio.py::registrar_sessao`.
- `src/aurora/api.py::carregar_sessao`: nas rotas seguintes, o apartamento vem dessa ligação gravada, e não do corpo da
  requisição.
- `src/aurora/ferramentas.py::apartamento_da_sessao`: o único lugar de onde as tools tiram o apartamento. Sem apartamento
  no state, a tool falha sem gravar.
- Nenhuma tool de `src/aurora/ferramentas.py` tem o parâmetro `apartamento`. O teste `test_nenhuma_tool_recebe_apartamento`,
  em `tests/test_ferramentas.py`, inspeciona as assinaturas.
- `src/aurora/repositorio.py::listar_reservas_ativas`, `src/aurora/repositorio.py::cancelar_reserva` e
  `src/aurora/repositorio.py::listar_visitantes`: as consultas filtram pelo apartamento que a tool recebeu da sessão.
- `src/aurora/ferramentas.py::verificar_disponibilidade` e `src/aurora/repositorio.py::data_disponivel`: a
  disponibilidade diz só se a data está livre, sem dizer de quem é a reserva.

A criação da sessão, em `criar_sessao`:

```python
        sessao = await servico.create_session(
            app_name=APP_NAME,
            user_id=corpo.apartamento,
            state={"apartamento": corpo.apartamento},
        )
```

O helper das tools, em `src/aurora/ferramentas.py`:

```python
def apartamento_da_sessao(tool_context: ToolContext) -> str:
    apartamento = tool_context.state.get("apartamento")
    if not apartamento:
        raise RuntimeError("Sessão sem apartamento.")
    return str(apartamento)
```

As linhas `def` das sete tools, em `src/aurora/ferramentas.py`:

```python
def listar_minhas_reservas(tool_context: ToolContext) -> dict:
def verificar_disponibilidade(area: str, data: str, tool_context: ToolContext) -> dict:
def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict:
def cancelar_reserva(area: str, data: str, tool_context: ToolContext) -> dict:
def listar_meus_visitantes(tool_context: ToolContext) -> dict:
def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
def buscar_no_regulamento(pergunta: str, tool_context: ToolContext) -> dict:
```

**Por que não depende do modelo:**

- O apartamento é definido uma vez, pela API, a partir do corpo de `POST /sessoes`, que representa o morador autenticado.
  O modelo não tem como trocá-lo: nenhuma tool aceita um apartamento, e nenhum código regrava a chave `apartamento` do
  state.
- As tools só devolvem dados do apartamento da sessão. A disponibilidade olha a agenda da área, mas devolve só livre ou
  ocupada. Por isso, dados de outro apartamento nunca entram no resultado de uma tool nem nos eventos.
- "Cancele a reserva do 302" chega à tool só como área e data. A busca é feita no apartamento da sessão e responde
  `nao_encontrada`, a mesma resposta de uma reserva que não existe.
- A disponibilidade responde só livre ou ocupada. Uma data ocupada por outro apartamento é recusada como `data_ocupada`,
  sem código nem número do dono.
- As instruções pedem que os especialistas não repitam o apartamento que o morador diz ser o dele. Isso é só cuidado com o
  texto: a garantia está nas tools.

### 3. Nada se perde no reinício

**Onde está:**

- `src/aurora/api.py::criar_api`: as sessões e os eventos ficam no `SqliteSessionService`, num arquivo em disco
  (`src/aurora/config.py::caminho_sessoes`).
- `src/aurora/banco.py::conectar`: os dados do condomínio ficam em outro arquivo em disco
  (`src/aurora/config.py::caminho_banco`).
- `src/aurora/banco.py::inicializar_se_necessario`: na subida, carrega o banco só se ele não existir ou não tiver dados.
  Um banco com dados nunca é alterado.
- `src/aurora/confirmacoes.py::listar_pendentes`: as pendências são derivadas dos eventos gravados, e não guardadas em
  memória.

O serviço de sessões e a subida, em `criar_api`:

```python
    if runner is None:
        config.carregar_ambiente()
        session_service = SqliteSessionService(str(config.caminho_sessoes()))
        runner = Runner(app=agentes.criar_app(), session_service=session_service)
```

```python
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        banco.inicializar_se_necessario()
        yield
```

A carga só quando falta, em `src/aurora/banco.py`:

```python
def inicializar_se_necessario() -> None:
    """Carrega o banco se ele não existir ou ainda não tiver dados; nunca altera um populado."""
    if not _inicializado():
        garantir_esquema()
        restaurar_dados()
```

**Por que não depende do modelo:**

- Tudo que precisa sobreviver está em disco: os eventos em `var/sessoes.db` e os dados em `var/aurora.db`. Na memória da
  API ficam só coisas que podem se perder: as travas por sessão, o registro de buscas do regulamento e o texto do
  regulamento já lido.
- A subida nunca recarrega um banco que já tem dados.
- As pendências são recalculadas dos eventos a cada requisição. Assim, uma confirmação criada antes do reinício pode ser
  aprovada depois dele, e a aprovação chega ao especialista autor pelo nome, que é fixo.
- A suíte de integração aprova uma reserva depois de um reinício simulado. O roteiro do avaliador reinicia a API de
  verdade no passo 13.

### 4. O regulamento é consultado, não carregado

**Onde está:**

- `src/aurora/agentes.py::INSTRUCAO_PRINCIPAL`: a instrução do principal não traz o regulamento. Ela só diz que dúvidas
  sobre regras vão para a ferramenta `especialista_regulamento`.
- `src/aurora/agentes.py::criar_agente_principal`: o especialista entra como `AgentTool`, que o roda numa sessão própria,
  em memória.
- `src/aurora/regulamento.py::buscar`: devolve até 4 artigos de um único capítulo.
- `src/aurora/ferramentas.py::buscar_no_regulamento`, com `src/aurora/ferramentas.py::REGISTRO_BUSCAS`: uma busca por
  execução do especialista. A segunda recebe um erro curto.
- `src/aurora/agentes.py::antes_da_tool_principal`: uma chamada ao especialista por turno do principal, marcada na chave
  `src/aurora/agentes.py::CHAVE_REGULAMENTO_USADO`. O callback também copia a mensagem do morador para a chave de state
  `pergunta_regulamento`, que a busca soma à pergunta do modelo.

Os especialistas do principal, em `criar_agente_principal`:

```python
        sub_agents=[reservas, visitantes],
        tools=[AgentTool(regulamento, skip_summarization=True)],
        before_tool_callback=antes_da_tool_principal,
```

Uma busca por execução, em `buscar_no_regulamento`:

```python
    if not REGISTRO_BUSCAS.registrar(tool_context.session.id):
        return {
            "status": "erro",
            "mensagem": "Só é possível uma busca no regulamento por consulta.",
        }
```

Uma chamada por turno, em `antes_da_tool_principal`:

```python
    if tool_context.state.get(CHAVE_REGULAMENTO_USADO):
        return {
            "status": "erro",
            "mensagem": "O regulamento já foi consultado neste turno.",
        }
    tool_context.state[CHAVE_REGULAMENTO_USADO] = True
```

**Por que não depende do modelo:**

- O texto do regulamento só é lido por `src/aurora/regulamento.py`, dentro da tool de busca. Nenhuma instrução o contém.
- Os artigos devolvidos pela busca ficam na sessão em memória do `AgentTool`, que é descartada no fim da chamada. Na
  sessão principal entram só a chamada a `especialista_regulamento` e a resposta final dele.
- Essa resposta é escrita a partir de uma única busca, que devolve artigos de um único capítulo. Os limites de uma busca e
  de uma chamada por turno estão no código: se o modelo tentar de novo, recebe um erro em vez de outro capítulo.
- Limite conhecido: a busca compara palavras, então o capítulo escolhido depende do vocabulário da pergunta. Por isso ela
  usa também a mensagem original do morador, e a instrução do especialista pede que ele reescreva a pergunta com as
  palavras do regulamento.

### 5. Dois moradores, uma reserva

**Onde está:**

- `src/aurora/banco.py::ESQUEMA_SQL`: o índice único parcial `ux_reserva_ativa_area_data`, que só permite uma reserva
  ativa por área e data.
- `src/aurora/banco.py::transacao`: toda gravação roda numa transação `BEGIN IMMEDIATE`.
- `src/aurora/repositorio.py::criar_reserva`: grava dentro dessa transação e transforma a violação do índice em
  `DataOcupada`.
- `src/aurora/ferramentas.py::reservar_area`: devolve `data_ocupada` como resultado normal da tool.
- `src/aurora/agentes.py::depois_da_tool_especialista`: depois da aprovação, o turno termina sem chamar o modelo.
- `src/aurora/api.py::trava`: a trava é por sessão, então duas sessões podem aprovar ao mesmo tempo.

O índice, em `ESQUEMA_SQL`:

```sql
-- Garantia 5: no máximo uma reserva ATIVA por área e data, valendo no instante da gravação.
CREATE UNIQUE INDEX IF NOT EXISTS ux_reserva_ativa_area_data ON reservas(area, data) WHERE status = 'ativa';
```

A transação, em `transacao`:

```python
    with closing(conectar()) as conexao:
        conexao.execute("BEGIN IMMEDIATE")
        try:
            yield conexao
        except BaseException:
            conexao.execute("ROLLBACK")
            raise
        conexao.execute("COMMIT")
```

A recusa, em `criar_reserva` e em `reservar_area`:

```python
            except sqlite3.IntegrityError as erro:
                mensagem = str(erro)
                if "reservas.area, reservas.data" in mensagem:
                    raise DataOcupada(f"{area} já está reservada em {data}.") from erro
```

```python
    except repositorio.DataOcupada:
        return {
            "status": "recusada",
            "motivo": "data_ocupada",
            "mensagem": f"{dados_area.nome} não está disponível em {data}.",
        }
```

**Por que não depende do modelo:**

- A exclusividade é do banco, no instante do `INSERT`. Conferir a disponibilidade antes ajuda a conversa, mas não é a
  garantia.
- `BEGIN IMMEDIATE` toma a trava de escrita no início da transação. A segunda gravação espera a primeira terminar (até
  10 s) e, quando roda, o índice recusa o `INSERT`.
- Quem perde recebe "data ocupada" como resultado da tool, e a rota responde `200` com uma mensagem normal.
- Depois da aprovação, o turno termina na resposta da tool, sem chamar o modelo. As duas respostas não dependem da cota do
  Gemini.

## Como rodar

### Pré-requisitos

- **`uv`.** Ele baixa o Python 3.12 se a máquina não tiver (a versão está em `.python-version`). Para instalar:
  - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - Linux e macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`

  Depois de instalar, abra um terminal novo para o `uv` entrar no PATH.
- **Uma chave do Google AI Studio**, criada em https://aistudio.google.com/apikey. O projeto usa o AI Studio, não a
  Vertex AI.
- Não há Docker nem serviço externo: os dois bancos são arquivos SQLite.

Em resumo, a ordem é: `uv sync`, copiar o `.env.example` para `.env`, preencher a chave, `uv run restaurar` e
`uv run api`. Cada passo está detalhado abaixo.

### Instalação

```
uv sync
```

Instala as dependências fixadas no `uv.lock`, entre elas o `google-adk==2.12.0`.

### Variáveis do `.env`

Copie o exemplo. No Linux e no macOS:

```
cp .env.example .env
```

No Windows (cmd ou PowerShell):

```
copy .env.example .env
```

Depois preencha `GOOGLE_API_KEY` no `.env`. Sem essa chave, a API sobe e as rotas de verificação respondem, mas o modelo
não pode ser chamado, e a rota de mensagens responde `503`.

O `.env.example` traz só os nomes:

```
GOOGLE_API_KEY=
GEMINI_MODELO=
AURORA_DIR_VAR=
```

| Variável | Obrigatória | Para que serve |
|---|---|---|
| `GOOGLE_API_KEY` | Sim | Chave do Google AI Studio. |
| `GEMINI_MODELO` | Não | Modelo Gemini dos quatro agentes. Vazia, vale `gemini-3.5-flash-lite`. |
| `AURORA_DIR_VAR` | Não | Pasta dos bancos SQLite. Vazia, vale `<raiz>/var`. |

- Os valores do `.env` substituem variáveis de mesmo nome do ambiente. A exceção é `AURORA_DIR_VAR` quando ela já está
  definida no processo, o que os testes usam. O projeto também força o AI Studio com `GOOGLE_GENAI_USE_VERTEXAI=FALSE`.
- **Modelo e cota.** O fluxo do avaliador faz algumas dezenas de chamadas ao modelo. Confira os limites do seu projeto no
  Google AI Studio.
  - O padrão é o `gemini-3.5-flash-lite`. Nos testes do projeto, ele não teve falhas e custou menos e respondeu mais
    rápido que o `gemini-3.8-flash`.
  - Se uma mensagem responder `503` por cota ou sobrecarga do modelo, espere um minuto e envie de novo.
  - Se a cota acabar (erro `429` mesmo depois das novas tentativas) ou se o modelo padrão errar chamadas de tool com
    frequência, preencha `GEMINI_MODELO` com `gemini-3.8-flash`, a alternativa. Reinicie a API depois de mudar o `.env`.
  - Atenção: no plano gratuito, o `gemini-3.8-flash` tem só 20 requisições por dia, menos do que o fluxo do avaliador usa.
  - O `gemini-2.5-flash` aparece na listagem de modelos, mas respondeu `404` ("no longer available to new users") para a
    chave usada no projeto.

### Restaurar os dados

```
uv run restaurar
```

- Cria a pasta `var/` e as tabelas, se faltarem.
- Numa única transação, apaga e recarrega dos arquivos de `dados/` os apartamentos, as áreas, as reservas e os visitantes.
- **Não apaga** as sessões (`var/sessoes.db` e a ligação entre sessão e apartamento) nem o registro dos códigos de reserva
  já emitidos. Assim, um código novo nunca repete o de uma reserva anterior à restauração.
- Pode rodar com a API ligada. As sessões continuam válidas, com os mesmos eventos.
- Só lê os arquivos de `dados/`, nunca os altera.

### Subir a API

```
uv run api
```

- Serve em `http://localhost:8000`, escutando em `127.0.0.1:8000`, sem recarga automática. Para parar, use Ctrl+C.
- Na primeira subida, se `var/aurora.db` não existir ou estiver vazio, a API carrega os dados de `dados/`. Se o banco já
  tiver dados, ela não muda nada. Reiniciar com o mesmo comando não perde sessões nem dados.
- Para conferir, `curl http://localhost:8000/apartamentos/101/reservas` deve listar a `RSV-1377`. No PowerShell 5.1, use
  `curl.exe` no lugar de `curl`.

### Testes

```
uv run pytest
```

- Roda os testes de unidade e a suíte de integração (`tests/integracao/`). A suíte faz requisições pela API real, com o
  Runner, os agentes, as tools, os callbacks e os bancos SQLite de verdade, numa pasta temporária. Só o Gemini é trocado
  por um modelo falso que segue um roteiro.
- Não chama o Gemini, não precisa de chave e não mexe em `var/`.

### Roteiro do avaliador (modelo real)

```
uv run python scripts/roteiro_avaliador.py
```

- Reproduz os passos 1 a 14 do fluxo do avaliador contra a API, com o modelo real, e confere cada verificação. Também faz
  as checagens de repositório do passo 15: `dados/` igual ao do commit `be87e1d`, `.env` fora do Git, `.env.example` sem
  valores, versão do ADK fixada, nenhuma chave versionada e as referências da seção Garantias.
- Pare a sua API antes. O roteiro roda `uv run restaurar`, sobe a própria API na porta 8000 e a reinicia no passo 13. A
  restauração desfaz as reservas e os visitantes criados antes.
- Gasta algumas dezenas de chamadas ao modelo, com a chave do `.env`.
- Imprime PASS ou FAIL em cada verificação e sai com código 1 se alguma falhar. A transcrição e o log da API ficam em
  `var/roteiro/`.
- `uv run python scripts/roteiro_avaliador.py --so-readme` confere só este README (as três seções e as referências
  `caminho::nome`), sem API e sem modelo.

O enunciado original do desafio está em `docs/enunciado.md`.
