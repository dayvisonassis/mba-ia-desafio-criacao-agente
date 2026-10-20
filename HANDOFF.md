# HANDOFF: Assistente do Residencial Aurora

> **Leia este arquivo inteiro no início de cada sessão, antes de qualquer outra ação.**
> Ao encerrar a sessão, atualize a seção 3 (Estado atual) e a seção 9 (Registro de sessões) e
> commite este arquivo.

## 1. O projeto em uma frase

Um assistente de condomínio em Google ADK 2.12.0, exposto por uma API FastAPI em
`http://localhost:8000`, com sessões e dados em SQLite. Ele precisa passar nos 15 passos do
avaliador do enunciado sem que nenhuma mensagem fure as cinco garantias. A filosofia é: **o modelo
decide o caminho, o código decide o que é permitido**.

## 2. Documentos de referência (leia nesta ordem)

| Documento | Para quê |
|---|---|
| `CLAUDE.md` | Regras fixas do projeto. Valem acima de qualquer skill. |
| `HANDOFF.md` (este) | Estado atual, procedimento de cada sessão e cuidados por tarefa. |
| `docs/superpowers/plans/2026-10-19-assistente-aurora.md` | **O plano.** Tarefas 0 a 12, com arquivos, interfaces exatas, testes e comandos. É o que se executa. |
| `docs/superpowers/specs/2026-10-19-residencial-aurora-design.md` | **O design aprovado** (revisão 5): decisões D1 a D25, garantias e o mapa dos passos do avaliador. Quando o plano não responder, vale o design. |
| `git show be87e1d:README.md` | O enunciado original. Depois da Task 11, ele também fica em `docs/enunciado.md`. |
| `.claude/skills/google-agents-cli-adk-code/` | Referência da API do ADK. Use só como referência (ver CLAUDE.md). |

Em caso de divergência, a ordem de precedência é: enunciado > CLAUDE.md > design > plano > este handoff. Se algo
parecer contradizer o enunciado, **pare e pergunte ao usuário**.

## 3. Estado atual

_Atualizado em 2026-10-20, depois da Task 1._

| Task | Descrição | Status | Commit / observação |
|---|---|---|---|
| 0 | Ambiente e esqueleto (`uv`, `pyproject`, ADK 2.12.0) | **concluída** | `32225f3` (docs) e `04ed34a` (esqueleto); revisão aprovada |
| 1 | Spike de confirmação (porta de decisão) | **concluída** | `07a11c8`; nenhum `FAIL` nos dois modelos; D8 revisada (padrão `gemini-3.5-flash-lite`) |
| 2 | Configuração e validação | pendente | |
| 3 | Banco, repositório e restauração | pendente | |
| 4 | Regulamento: carga e busca | pendente | |
| 5 | Ferramentas (tools) | pendente | |
| 6 | Agentes, callbacks e App | pendente | |
| 7 | Pendências e montagem da resposta | pendente | |
| 8 | API e servidor | pendente | |
| 9 | Suíte de integração (pilha real, Gemini falso) | pendente | |
| 10 | Roteiro do avaliador (modelo real) | pendente | |
| 11 | README da entrega | pendente | |
| 12 | Finalização (merge e push, com autorização) | pendente | |

**Estado do repositório:**
- Branch de trabalho: `feat/assistente-aurora`, criada a partir de `main` (`be87e1d`). A `main` continua intacta.
- `uv` 0.13.3 instalado em `C:\Users\dayvi\.local\bin`. Em shells abertos antes da instalação ele não está no PATH: use
  `export PATH="$HOME/.local/bin:$PATH"` (Bash) ou `$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"` (PowerShell).
- `.venv` com Python 3.12.15 e `google-adk` 2.12.0. `uv run pytest`: 1 passed.
- A chave do projeto tem faturamento ativo (Tier 1) desde 2026-10-20. O spike inteiro, nos dois modelos, custou menos de US$ 0,10.
- O resultado do spike está no fim do plano ("Resultado do spike"). A pasta `spike/` foi apagada, como manda a Task 1.
- O `.env` existe, com a `GOOGLE_API_KEY`, e é ignorado pelo Git.
- O registro de progresso da skill de execução fica em `.superpowers/sdd/2026-10-19-assistente-aurora/progress.md`, ignorado pelo Git.
  Ele guarda a varredura do plano e as decisões de execução. As que afetam tarefas futuras estão copiadas na seção 6, nas
  Tasks 2, 8 e 9, para não se perderem.

## 4. Procedimento de cada sessão

1. Leia `CLAUDE.md` e este arquivo.
2. Confira o estado real com `git branch --show-current`, `git status` e `git log --oneline -15`. Se ele divergir da
   tabela da seção 3, a tabela está desatualizada: corrija-a a partir dos commits antes de seguir.
3. Se a Task 0 já foi concluída, rode `uv sync` e `uv run pytest`. Tudo deve passar até a última task concluída.
   Se algo estiver vermelho, corrija isso primeiro.
4. Execute a próxima task pendente com a skill **`superpowers:subagent-driven-development`**, o método escolhido pelo usuário:
   - um subagente implementador por task, que recebe o texto completo da task no plano, a seção "Global Constraints" e os
     blocos "Interfaces" das tasks de que ela depende;
   - um subagente revisor por task, antes de começar a próxima;
   - ao final da Task 11, uma revisão da branch inteira.
5. A sessão principal (o coordenador) cuida dos **pontos de decisão** da seção 5. Nunca delegue a um subagente uma
   decisão que é do usuário.
6. Ao encerrar, atualize as seções 3 e 9 e faça `git add HANDOFF.md` e `git commit -m "docs: atualiza handoff"`.
   Se o plano mudou, por exemplo com o resultado do spike, commite o plano junto.

## 5. Pontos que exigem o usuário

- **Task 0:** instalar o `uv`. Peça autorização antes.
- **Task 1:** se qualquer cenário do spike der `FAIL`, **pare** (D23). Leve ao usuário o cenário, os eventos e a hipótese.
  Nenhum plano B sem aprovação, porque todo plano B muda a arquitetura (design §14.1).
- **Troca do modelo padrão (D8):** o critério está no design e pode ser aplicado, mas avise o usuário e registre o motivo no plano.
  A troca da Task 1 (padrão `gemini-3.5-flash-lite`, alternativa `gemini-3.8-flash`) foi feita por delegação do usuário. Uma nova
  troca, por exemplo no roteiro da Task 10, também precisa de aviso.
- **Qualquer mudança no contrato da API, nas garantias ou numa decisão D1 a D25:** pergunte antes.
- **Task 12:** o merge na `main` e o `git push` precisam de autorização **explícita**. Pergunte também se o
  `HANDOFF.md` fica no repositório entregue.

## 6. Cuidados por tarefa

O passo a passo, as interfaces e os testes de cada tarefa estão no plano. Aqui ficam só os cuidados que pegam quem não leu
o código do ADK. As referências de arquivos do ADK são relativas a `.venv/Lib/site-packages/google/adk/`, que existe depois
do `uv sync`. A cópia lida na sessão de planejamento ficava numa pasta temporária e não existe mais.

### Task 0: Ambiente e esqueleto
- Instale o `uv` com `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`, depois de autorizado.
  Abra um shell novo ou use `$env:USERPROFILE\.local\bin\uv.exe`. O Python padrão da máquina é o 3.11, e o `uv` baixa o 3.12.
- Crie a branch `feat/assistente-aurora` **antes** de commitar.
- No Step 3, inclua `HANDOFF.md` no `git add`, além do que o plano lista.
- O `pyproject.toml` está pronto no plano, com valores exatos. Não troque a versão do ADK.

### Task 1: Spike (porta de decisão)
- Usa o Gemini de verdade, com a chave do `.env`, e gasta cota. Rode `todos` uma vez e repita só o que falhar.
- Reproduza a **topologia final**: nomes de agentes, flags de transferência, `AgentTool` com `skip_summarization`
  e callbacks. Um spike com outra topologia não prova nada.
- Registre na seção "Resultado do spike" do plano: a tabela, o formato do evento final do `AgentTool`, a ordem dos
  eventos depois da recarga, o número de chamadas ao modelo e o modelo escolhido. Depois **apague `spike/`**, que é descartável.
- Se algo falhar, aplique a D23: pare e consulte o usuário.
- **Concluída em 2026-10-20.** Nenhum `FAIL`. Os resultados, os formatos de evento e a escolha do modelo estão na seção "Resultado do spike" do plano.

### Task 2: Configuração e validação
- `date.fromisoformat` no Python 3.11 ou superior aceita "20300420". Por isso valide o regex `^\d{4}-\d{2}-\d{2}$` antes.
- `dir_var()` lê `AURORA_DIR_VAR` a cada chamada (D25). Os testes usam `monkeypatch.setenv`.
- Acrescente `AURORA_DIR_VAR=` ao `.env.example`, sem valor.
- `MODELO_PADRAO = "gemini-3.5-flash-lite"` e `MODELO_ALTERNATIVO = "gemini-3.8-flash"`. O plano já traz esses valores.
- O ambiente do usuário tem uma `GEMINI_API_KEY` global. O google-genai avisa "Both GOOGLE_API_KEY and GEMINI_API_KEY are set" e usa a
  `GOOGLE_API_KEY` do `.env`, o que está certo. O plano não pede nada a respeito.
- **Decisão de execução (Ruling 3), que complementa o plano:**
  - `carregar_ambiente(caminho: Path | None = None)` lê o `.env` (padrão `RAIZ/.env`) com `dotenv_values`;
  - aplica cada chave sobrescrevendo o ambiente, **exceto** `AURORA_DIR_VAR` quando ela já existe no processo;
  - depois força `GOOGLE_GENAI_USE_VERTEXAI=FALSE`.

  Sem isso, um `.env` copiado do exemplo (com `AURORA_DIR_VAR=` vazio) faria os testes gravarem no `var/` real.
  Acrescente um teste com um `.env` temporário contendo `AURORA_DIR_VAR=` e `GOOGLE_API_KEY=x`. Ele deve confirmar que
  um `AURORA_DIR_VAR` já definido não muda e que a chave é aplicada. Use `monkeypatch.setenv` antes, para o ambiente ser restaurado.

### Task 3: Banco, repositório e restauração
- Use `sqlite3` com `isolation_level=None` e transações explícitas (`BEGIN IMMEDIATE` … `COMMIT`), sem `await` no meio.
- O `IntegrityError` é identificado pelas colunas na mensagem: `reservas.area, reservas.data` é data ocupada, e
  `codigos_emitidos.codigo` pede um novo código.
- A restauração apaga e recarrega `reservas`, `visitantes`, `areas` e `apartamentos`, nessa ordem por causa das FKs, mas
  **nunca** `codigos_emitidos` nem `sessoes`. Os JSON são lidos com `encoding="utf-8"`.

### Task 4: Regulamento
- O arquivo tem 14 capítulos e 96 artigos. A frase da piscina está na linha 157: "Aos domingos e feriados, a piscina funciona das 9h às 20h."
- A busca devolve artigos de **um único** capítulo.
- O spike confirmou a chave do limite da D19: o `tool_context.session.id` da sessão filha é o mesmo em toda a execução do
  especialista e muda a cada chamada do `AgentTool`.

### Task 5: Ferramentas
- Em todas as tools, `tool_context` é o último parâmetro. Nenhuma tool tem o parâmetro `apartamento`.
- As funções de `require_confirmation` têm a assinatura `(area: object = "", data: object = "", tool_context: object = None)` (ou `nome`, `data`).
  O ADK as chama com `**kwargs` antes de validar os argumentos obrigatórios (`tools/function_tool.py`). Elas
  **nunca lançam exceção**: o corpo inteiro fica num `try/except`.
- O `chamada_id` é `f"{tool_context.session.id}:{tool_context.function_call_id}"`.
- Para os testes: a função original fica em `FunctionTool.func`, e `check_require_confirmation` é async (use `asyncio.run`).
- O spike contou as chamadas à função de `require_confirmation`: 1 ao criar a pendência, 2 numa área sem taxa, 2 na negação e 3 na aprovação.
- **Ruling 9:** o spike provou a via por função só em `reservar_area` (o visitante usou `require_confirmation=True`). Os testes desta
  task precisam passar `precisa_confirmar_visitante` pelo `FunctionTool`, e a Task 9 pela pilha completa.

### Task 6: Agentes, callbacks e App
- **O ADK chama os callbacks pelo nome dos parâmetros** (`flows/llm_flows/tools/_caller.py` e `_error_handler.py`):
  - `before_tool_callback(tool, args, tool_context)`;
  - `after_tool_callback(tool, args, tool_context, tool_response)`;
  - `on_tool_error_callback(tool, args, tool_context, error)`.

  Nunca renomeie esses parâmetros, nem para `_args`, mesmo que um lint reclame.
- Os nomes dos agentes são fixos, porque as pendências gravadas apontam para o autor pelo nome. Não use `ResumabilityConfig`:
  ele desfaz o roteamento pelo principal (design §10.2).
- Chaves `temp:` **não chegam** à sessão do `AgentTool` (`sessions/_session_util.py`, `extract_state_delta`). Por isso a
  pergunta do morador vai na chave normal `pergunta_regulamento`.
- O `Gemini` está em `google.adk.models.google_llm`, e as novas tentativas usam `google.genai.types.HttpRetryOptions`.
- `criar_app(modelo=None)`: a injeção do modelo existe só para a suíte de integração (D24).
- Com o `gemini-3.5-flash-lite`, o pedido de duas reservas numa mensagem gerou uma só chamada, sem avisar da segunda. A instrução do
  especialista de reservas deve pedir que ele diga quando deixa parte do pedido para depois (como a D14 já pede para dois assuntos).

### Task 7: Pendências e resposta
- O evento de confirmação é um `function_call` `adk_request_confirmation` com `args.originalFunctionCall` (`id`, `name`, `args`).
- Com `skip_summarization`, o `AgentTool` acrescenta uma **parte de texto** ao próprio evento de resposta (`_caller.py`).
  Por isso `montar_resposta` prefere o texto e, quando não há texto, usa o `mensagem` da tool.
- Confira o formato real na seção "Resultado do spike" antes de implementar.

### Task 8: API e servidor
- Na rota de confirmações, o `404` vem primeiro. Depois, **dentro do lock da sessão**, vem o `409`, ainda **antes** de chamar o Runner.
  Um id desconhecido faz o ADK lançar `ValueError`, que viraria `500`.
- `criar_api` chama `config.carregar_ambiente()` logo no início, antes de montar os agentes.
- Use só os eventos **emitidos nesta chamada** para montar `resposta` e para a conferência de 9.3, porque o ADK reaproveita o `invocation_id`.
- Reenviar uma aprovação já consumida não lança exceção e não emite eventos (spike, cenário 4). Sem o `409`, a rota daria um `200` vazio.
- O `429` sai de `run_async` como `google.adk.models.google_llm._ResourceExhaustedError`, subclasse de `google.genai.errors.ClientError`,
  com `.code == 429`. Os eventos emitidos antes do erro ficam na sessão, o que importa para a regra 200/503 da §9.
- **Decisão de execução (Ruling 4):** o `RunnerFalso` guarda o serviço de sessão em `self.session_service`, porque a fixture `cliente` do plano usa esse nome.

### Task 9: Suíte de integração
- O modelo falso é uma subclasse de `BaseLlm`, injetada por `criar_app(modelo=...)`. Não faça `monkeypatch` em módulos do projeto.
- `transfer_to_agent` recebe `agent_name`, e o `AgentTool` recebe `request`.
- Para saber qual agente chamou o modelo, olhe as tools visíveis: só o principal vê `especialista_regulamento`.
- O reinício é simulado montando um `SqliteSessionService`, um `Runner` e uma API novos sobre os mesmos arquivos.
- **Decisão de execução (Ruling 5):** a fixture `pilha` usa **um único** `asyncio.Runner` por teste para todas as chamadas,
  inclusive o `gather` da disputa e o `reiniciar()`. Locks e conexões assíncronas não podem atravessar loops diferentes.
- O `httpx.ASGITransport` não roda o lifespan da API, então a fixture cria o esquema e os dados ela mesma.

### Task 10: Roteiro do avaliador
- Usa o modelo real, com algumas dezenas de chamadas. Rode com a API em subprocesso e, no Windows, encerre com `terminate()`.
- O roteiro reproduz **cada verificação** do "Fluxo do avaliador" do enunciado. "302 isolado" usa o regex `(?<!\d)302(?!\d)`.
- Uma falha aqui pede `superpowers:systematic-debugging` e um teste que reproduza a falha na task dona do código.
- Latência medida no spike, com faturamento: `gemini-3.5-flash-lite` com mediana de 0,9 s e máximo de 1,5 s; `gemini-3.8-flash` com mediana
  de 3,2 s e chamadas de 9 a 44 s. No plano gratuito, os `503` e as novas tentativas levavam cada chamada do 3.8-flash a 50–150 s.
  Dê folga aos timeouts do cliente HTTP, e mais ainda se o roteiro usar a alternativa.
- As contagens de chamadas do spike vêm das tools mínimas dele e não servem de estimativa de cota.
- Se o `gemini-3.5-flash-lite` errar chamadas de tool de forma recorrente, o critério da D8 manda usar o `gemini-3.8-flash`. Avise o usuário.

### Task 11: README da entrega
- Copie o enunciado para `docs/enunciado.md` **com Python** (o plano traz o comando). O redirecionamento do PowerShell muda a codificação.
- O README avisa que o fluxo do avaliador faz algumas dezenas de chamadas, que o `gemini-3.8-flash` gratuito tem 20 requisições por dia
  e como trocar o modelo por `GEMINI_MODELO`.
- O README tem exatamente as seções Arquitetura, Garantias e Como rodar. As referências seguem o formato `src/aurora/x.py::funcao`, conferidas com `--so-readme`.

### Task 12: Finalização
- Rode `uv run pytest`, o roteiro completo, `git diff --exit-code be87e1d -- dados/` e `git status` (limpo).
- Use a skill `superpowers:finishing-a-development-branch`. Antes de merge e push, peça autorização ao usuário. O remote
  `origin` é `https://github.com/dayvisonassis/mba-ia-desafio-criacao-agente`.

## 7. Sugestão de divisão em sessões

| Sessão | Tasks | Termina em |
|---|---|---|
| 1 | 0 e 1 | Spike aprovado (ou parada para decisão do usuário) |
| 2 | 2 a 5 | Camada de dados, regulamento e tools prontos e testados |
| 3 | 6 a 9 | Agentes, API e suíte de integração verdes |
| 4 | 10 a 12 | Roteiro verde, README e entrega |

## 8. Ambiente

- Windows 11. O shell principal é o PowerShell 5.1, e o Git Bash também está disponível.
- O Python padrão é o 3.11 (o 3.14 também está instalado). O projeto usa o 3.12 via `uv`.
- Modelos (2026-10-20): `gemini-3.5-flash-lite` (padrão da D8) e `gemini-3.8-flash` (alternativa), os dois estáveis.
  O `gemini-2.5-flash` aparece na listagem de modelos, mas responde `404` ("no longer available to new users").
- **Nunca** imprima, copie ou commite a chave do `.env`.

## 9. Registro de sessões

- **2026-10-19, sessão de planejamento.**
  - O clone incompleto foi recuperado e o `.env` foi criado.
  - O design passou por três validações independentes e está na revisão 5, aprovada pelo usuário.
  - O plano foi escrito com 13 tarefas e a execução escolhida foi com subagentes (`superpowers:subagent-driven-development`).
  - A skill `google-agents-cli-adk-code` foi instalada como referência.
  - As skills do repositório `sdd-skills` foram avaliadas, e o usuário decidiu não usá-las neste projeto.
  - Nada foi implementado nem commitado.
- **2026-10-19, Task 0** (execução com `superpowers:subagent-driven-development`; o escopo autorizado era só a Task 0).
  - O coordenador instalou o `uv` com autorização do usuário, criou a branch `feat/assistente-aurora` e commitou os documentos (`32225f3`).
  - O implementador fez os Steps 4 a 8 (`04ed34a`), e o revisor aprovou sem achados críticos ou importantes.
  - A varredura do plano gerou as Rulings 1 a 5. As de impacto futuro estão na seção 6 (Tasks 2, 8 e 9).
  - Próximo passo: **Task 1 (spike)**, que usa o Gemini real e é porta de decisão (D23).
- **2026-10-20, Task 1** (execução com `superpowers:subagent-driven-development`; o escopo autorizado era só a Task 1).
  - A primeira rodada, no plano gratuito, parou por cota: 20 requisições por dia no `gemini-3.8-flash`, e o `gemini-2.5-flash` deu `404`.
    Os cenários 1 a 6, 8 e 9 já tinham passado.
  - O usuário ligou o faturamento e delegou a escolha do modelo: manter o atual se fosse o mais indicado, ou escolher um indicado e barato.
  - O coordenador comparou preço, latência e chamadas de tool de quatro modelos (Ruling 8). O spike rodou inteiro no `gemini-3.8-flash` e
    no `gemini-3.5-flash-lite`, sem nenhum `FAIL`. Os não reproduzidos foram 13 e 14b no 3.8; 13, 14 e 15 no lite.
  - D8 revisada: padrão `gemini-3.5-flash-lite`, alternativa `gemini-3.8-flash`. O design e as Tasks 2 e 11 do plano foram atualizados (Ruling 10).
  - A revisão da task aprovou a fidelidade ao design e pediu só ajustes de texto, feitos numa rodada. Um achado mandado pelo plano virou a
    Ruling 9 (cobertura da função de confirmação de visitante nas Tasks 5 e 9). Commit `07a11c8`, e `spike/` apagado.
  - Próximo passo: **Task 2 (configuração e validação)**, início da sessão 2 da seção 7 (Tasks 2 a 5).
