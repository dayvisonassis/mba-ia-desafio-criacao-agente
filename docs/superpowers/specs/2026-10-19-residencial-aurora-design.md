# Design: assistente virtual do Residencial Aurora

- **Data:** 2026-10-19
- **Status:** revisão 5, aprovada pelo usuário em 2026-10-19
- **Enunciado:** `README.md` original do commit `be87e1d` (`git show be87e1d:README.md`). Os números de "passo" citados aqui são os do "Fluxo do avaliador" desse enunciado.
- **Histórico:**
  - Revisão 1: primeira versão.
  - Revisão 2: incorpora a validação feita por um revisor independente contra o enunciado e o código do ADK 2.12.0. Foram corrigidos a assinatura das funções de confirmação; a chamada ao modelo depois da aprovação; o roteamento das mensagens; a expiração das pendências; os limites da busca no regulamento; a idempotência no banco; o formato do código de reserva; e o `.env.example`.
  - Revisão 3: incorpora a segunda validação independente. A expiração das pendências foi trocada pela substituição de duplicatas (D16); qualquer plano B passou a exigir uma nova verificação completa; a busca no regulamento passou a usar também o pedido original; e foram ajustados o código de reserva, a chave de idempotência, a ordem do `409`, o carregamento do `.env` e o texto de `resposta`.
  - Revisão 4: incorpora a terceira validação independente, que não achou nada capaz de reprovar a entrega. A busca no regulamento passa a receber a mensagem do morador por uma chave de state (chaves `temp:` não chegam ao `AgentTool`). A resposta do especialista do regulamento encerra o turno (D21). O spike ganha cenários de pendência antiga, e um spike que falhar faz parar e consultar o usuário (D23). Também entram: `503` só quando nada foi executado, leitura em UTF-8, desempate e normalização na substituição de duplicatas, e o que versionar de `.claude/`.
  - Revisão 5: acrescenta a suíte de integração pela pilha real, com só o Gemini substituído na fronteira (D24), e a variável opcional `AURORA_DIR_VAR` (D25). As duas ideias vêm das regras de teste do repositório `sdd-skills`. A execução segue o plano original, com subagentes.

## 1. Intenção

O Residencial Aurora quer um assistente de chat para os moradores reservarem áreas comuns, cancelarem as próprias reservas, autorizarem visitantes e tirarem dúvidas sobre o regulamento. A síndica impôs uma condição: **nenhuma mensagem pode convencer o assistente a quebrar regra**.

Por isso, a filosofia do projeto é: **o modelo decide o caminho, o código decide o que é permitido**. Toda regra crítica fica no código (tools, callbacks, banco e API) e continua valendo independentemente do que o morador escreva ou do que o modelo decida.

A entrega é avaliada por um roteiro automático de 15 passos. Se uma verificação falhar, a entrega fica incompleta, então cada decisão abaixo é conferida contra esse roteiro (seção 15).

## 2. Objetivos, não objetivos e antiobjetivos

**Objetivos**
- API em Python em `http://localhost:8000` que segue **exatamente** o contrato do enunciado.
- Assistente em Google ADK com um agente principal e especialistas.
- As cinco garantias implementadas em código.
- Um comando para subir a API e outro para restaurar os dados iniciais.
- README final com as seções Arquitetura, Garantias e Como rodar. A seção Garantias aponta **arquivos e funções reais** do repositório.
- Tudo na branch `main` do fork público, enviado só com autorização do usuário.

**Não objetivos** (fora de escopo pelo enunciado, então não serão feitos)
- Interface visual, autenticação, pagamento e estorno.
- Regras de antecedência, datas passadas, horários de uso e capacidade das áreas.
- Deploy, evals e qualquer coisa de Google Cloud.

**Antiobjetivos** (coisas que fariam a entrega falhar mesmo "funcionando")
- Uma regra que só existe no prompt.
- Qualquer dado de outro apartamento chegando à resposta ou aos eventos da sessão.
- Uma confirmação "aceita" pela API em que a ação não executa (a armadilha citada no enunciado).
- Duas reservas ativas para a mesma área e data, mesmo por um instante.
- Uma resposta `500` ou `503` numa disputa de reserva (o passo 14 exige `200` para as duas aprovações).
- Arquivos de `dados/` alterados, chave de API versionada ou valores no `.env.example`.
- Restrições extras (por exemplo, recusar datas passadas) que façam o assistente recusar pedidos do roteiro.

## 3. Restrições do enunciado

- Python 3.12 ou superior, com o projeto gerenciado por `uv` (`pyproject.toml` e `uv.lock` versionados).
- Google ADK série 2, versão 2.2.0 ou superior, com a **versão exata** fixada.
- Modelos Gemini com chave do Google AI Studio (`GOOGLE_API_KEY`).
- `.env` fora do Git; `.env.example` versionado só com os **nomes** das variáveis, sem valores.
- Os arquivos de `dados/` não podem ser alterados.
- Se houver serviço externo, ele sobe com um comando documentado. **Não haverá serviço externo.**

## 4. Decisões

| # | Decisão | De quem | Motivo |
|---|---|---|---|
| D1 | SQLite, sem Docker e sem banco externo | Usuário (aprovou a sugestão) | Zero infraestrutura para o avaliador. O enunciado relata que a confirmação funcionou com sessão persistida em SQLite. O índice único parcial resolve a Garantia 5. |
| D2 | FastAPI | Usuário (aprovou) | É o framework do curso. O ADK 2.12.0 já depende dele. |
| D3 | Três especialistas: reservas e visitantes como **subagentes**, regulamento como **tool (AgentTool)** | Usuário (aprovou a sugestão) | Ver seção 6. |
| D4 | `google-adk==2.12.0` | Minha | É a versão cujo código-fonte foi lido para este design (seção 10). Plano B: 2.9.1, testada pelos autores do enunciado. |
| D5 | Sessões com `SqliteSessionService` do próprio ADK | Minha | É o serviço que o `adk web` usa para persistir localmente em SQLite, provavelmente o mesmo que os autores testaram. |
| D6 | Dois arquivos SQLite: `var/aurora.db` (condomínio) e `var/sessoes.db` (ADK) | Minha | Separa os dados do condomínio do esquema interno do ADK e reduz disputa de trava entre as gravações das duas partes. |
| D7 | Python 3.12 (`.python-version`) | Minha | É a versão mínima exigida, e o `uv` baixa sozinho se faltar. |
| D8 | O modelo vem de `GEMINI_MODELO` (opcional), com o mesmo modelo em todos os agentes e novas tentativas automáticas para `429` e `503` (`Gemini(model=..., retry_options=HttpRetryOptions(...))`). Padrão: `gemini-3.5-flash-lite`, com `gemini-3.8-flash` como alternativa. Revisado no spike em 2026-10-20: o padrão inicial era `gemini-3.8-flash`, com `gemini-2.5-flash` como alternativa. | Minha, revisada no spike (seção 14) por delegação do usuário | A cota do plano gratuito varia por modelo. O spike mede se o padrão aguenta o roteiro. Aparecer na listagem de modelos não basta: o `gemini-2.5-flash` aparece nela e responde `404` ("no longer available to new users"). No plano gratuito, o `gemini-3.8-flash` tem 20 requisições por dia, abaixo das dezenas de chamadas do fluxo do avaliador. O `gemini-3.5-flash-lite` passou no spike sem nenhum `FAIL`, custa cerca de 6 vezes menos e responde cerca de 3,5 vezes mais rápido. Os números estão na seção "Resultado do spike" do plano. **Critério de troca:** se o spike ou o roteiro (14.3) tiver alguma falha de cota depois das novas tentativas, ou se o modelo errar chamadas de tool de forma recorrente, usar a alternativa. O padrão precisa ser um modelo estável (sem "preview"). Como o avaliador usa a própria chave, o README explica como trocar o modelo por `GEMINI_MODELO` se a cota acabar. |
| D9 | O comando de restauração **não apaga sessões** | Minha | Ele só recarrega apartamentos, áreas, reservas e visitantes. Assim não mexe no esquema interno do ADK e pode rodar com a API ligada. O enunciado deixa isso livre. |
| D10 | Código de reserva novo: `RSV-N` seguido de 8 **consoantes maiúsculas** sorteadas (ex.: `RSV-NKQWTZBM`), registrado numa tabela `codigos_emitidos` que a restauração **nunca** apaga | Minha | Sem dígitos na parte sorteada, o código nunca forma `RSV-4821` nem contém números como `302`, que o passo 10 procura isolados. A tabela garante que nenhum código se repita, nem entre restaurações (regra 5). |
| D11 | Reserva cancelada não é apagada, ela muda para `status = 'cancelada'` | Minha | Não bloqueia uma nova reserva da mesma data (o índice único só vale para reservas ativas) e preserva o histórico. |
| D12 | Antes de substituir o README, o enunciado é copiado para `docs/enunciado.md` | Minha | Mantém o enunciado à mão depois da entrega. |
| D13 | `uv run restaurar` e `uv run api` como comandos | Minha | São curtos e fáceis de documentar. |
| D14 | Os especialistas **não transferem**: `disallow_transfer_to_parent=True` e `disallow_transfer_to_peers=True`. Toda mensagem nova de texto começa no agente principal. | Minha (correção do revisor) | Roteamento determinístico: a pergunta da piscina (passo 12) nunca fica presa no especialista de visitantes. A retomada da confirmação continua indo ao especialista autor, porque essa rota não depende de o agente poder transferir (10.2). O custo é cerca de uma chamada a mais ao modelo por mensagem. **Só vale sem `ResumabilityConfig`** (10.2). Numa mensagem com dois assuntos (passo 3), só um especialista atende: ele responde à sua parte e diz que o outro assunto pode ser pedido em seguida. |
| D15 | Depois de aprovar ou negar, o turno **termina sem nova chamada ao modelo** (`skip_summarization`). A API monta `resposta` com o campo `mensagem` do resultado da tool. | Minha (correção do revisor) | O passo 14 passa a não depender da cota do Gemini depois que a reserva foi gravada. A negação também não abre espaço para o modelo chamar a tool de novo. |
| D16 | Pendências **não expiram** com novas mensagens. Quando surge uma candidata mais nova com a mesma `acao` e os mesmos `detalhes`, ela **substitui** as anteriores, que deixam de ser listadas e passam a receber `409`. | Minha (revisão 3, correção do revisor) | `confirmacoes_pendentes` lista todas as pendências reais da sessão, como diz o contrato. Uma resposta do avaliador pelo chat nunca invalida uma aprovação legítima. Duplicatas (o modelo chamando a mesma tool duas vezes) viram uma só. Uma pendência antiga continua exigindo aprovação explícita, então a Garantia 1 não muda. |
| D17 | As funções passadas a `require_confirmation` **validam os argumentos**, aceitam `tool_context` e **nunca lançam exceção**. Se o pedido for inválido, retornam `False`, e o corpo da tool recusa sem gravar. | Minha (correção do revisor) | O ADK chama essas funções com os argumentos do modelo mais `tool_context` (10.1). Validar antes evita pendências impossíveis de executar e `detalhes` malformado. O corpo de cada função fica num `try/except` geral, porque o ADK entrega os valores crus (uma data pode chegar como número). O parâmetro precisa se chamar `tool_context`, como na tool. |
| D18 | Idempotência no banco: `reservas` e `visitantes` ganham a coluna `chamada_id UNIQUE`, com a chave `"{session_id}:{function_call_id}"`. Antes de gravar, a tool procura essa chave. Se ela existir com os mesmos dados, devolve o registro existente. | Minha (correção do revisor) | "Aprovar executa uma única vez" passa a valer também no banco, independentemente do ADK. A chave composta não depende de o id da chamada ser único entre sessões. |
| D19 | Regulamento: no máximo **uma busca** por execução do especialista e **uma chamada** do especialista por turno do principal, impostas em código | Minha (correção do revisor) | A resposta do especialista entra na sessão principal. Com uma busca de um único capítulo, ela não tem como misturar capítulos (Garantia 4). Para a única busca permitida acertar o capítulo, ela usa o argumento do modelo **e** a mensagem original do morador. O `before_tool_callback` do principal copia essa mensagem para a chave de state `pergunta_regulamento`. A chave não pode ser `temp:`, porque o `AgentTool` descarta chaves `temp:` ao criar a sessão do especialista (`sessions/_session_util.py`, `extract_state_delta`). |
| D20 | `.env.example` só com nomes: `GOOGLE_API_KEY=`, `GEMINI_MODELO=` e `AURORA_DIR_VAR=` (D25). O `config.py` carrega o `.env` com `override=True` e força `GOOGLE_GENAI_USE_VERTEXAI=FALSE` no processo. | Minha (correção do revisor) | O enunciado exige variáveis sem valores. O `override=True` faz o `.env` do projeto ganhar de uma `GOOGLE_API_KEY` global, e forçar o AI Studio protege contra outra variável global do ambiente do avaliador. |
| D21 | `AgentTool(especialista_regulamento, skip_summarization=True)` | Minha (sugestão do revisor) | A resposta do especialista encerra o turno e vira `resposta` sem passar de novo pelo modelo do principal. Economiza uma chamada ao modelo e preserva o horário literal ("20h") do passo 12. |
| D22 | `.claude/skills/` e `CLAUDE.md` são versionados; `.claude/settings.local.json` entra no `.gitignore` | Minha | A skill e as regras servem a quem usar o Claude Code no repositório. As configurações locais são pessoais. Nada disso afeta a avaliação. |
| D23 | Se algum cenário do spike falhar, quem constrói **para** e volta ao usuário com o diagnóstico antes de aplicar qualquer plano B | Minha | Todo plano B muda a arquitetura aprovada (14.1), então precisa de nova aprovação. |
| D24 | Suíte de integração em `tests/integracao/`: requisições pela API real, com Runner, agentes, tools, callbacks e SQLite reais. Só o Gemini é substituído, na fronteira, por um modelo falso que segue um roteiro (subclasse de `BaseLlm`), injetado por `agentes.criar_app(modelo=...)`. | Usuário (aprovou a sugestão) | Prova de forma determinística, sem gastar cota, o que antes só o roteiro com o modelo real provaria: a aprovação depois do reinício, o `409`, a disputa entre sessões, o roteamento ao especialista autor e o isolamento do regulamento. A injeção do modelo é um parâmetro opcional, não um stub no código de produção. |
| D25 | Variável opcional `AURORA_DIR_VAR`: quando preenchida, troca a pasta `var/` dos bancos. Vazia, vale `<raiz>/var`. | Minha | Os testes apontam o banco para uma pasta temporária sem fazer `monkeypatch` em módulos do projeto. O enunciado permite variáveis novas desde que o `.env.example` traga só o nome. |

## 5. Visão geral

```
            cliente (avaliador / curl)
                      │  JSON
                      ▼
   ┌──────────────── API FastAPI (aurora/api.py) ────────────────┐
   │ POST /sessoes  POST /mensagens  POST /confirmacoes          │
   │ GET /eventos   GET /apartamentos/{n}/reservas|visitantes    │
   └───────┬─────────────────────────────────────────┬───────────┘
           │ Runner (App "aurora")                   │ leitura direta
           ▼                                         ▼ (rotas de verificação)
   assistente_aurora (principal) ───────────────► var/aurora.db
     ├─ sub_agent: especialista_reservas  ─tools─► (reservas, áreas)
     ├─ sub_agent: especialista_visitantes ─tools─► (visitantes)
     └─ tool: AgentTool(especialista_regulamento)
                 └─ tool: buscar_no_regulamento ─► dados/regulamento.md
           │
           ▼
   SqliteSessionService ──► var/sessoes.db (sessões e eventos)
```

## 6. Agentes

Todos os agentes são `LlmAgent` com o modelo da D8. Nenhuma instrução contém dados de apartamentos, moradores, reservas, visitantes ou trechos do regulamento. Os nomes dos agentes são fixos: renomear um agente invalida as pendências já gravadas (10.2).

### 6.1 `assistente_aurora` (principal)
- **Responsabilidade:** recebe toda mensagem de texto, entende o pedido e encaminha.
- **Como aciona os especialistas:**
  - `sub_agents=[especialista_reservas, especialista_visitantes]`: transfere a conversa.
  - `tools=[AgentTool(especialista_regulamento, skip_summarization=True)]`: chama como ferramenta (D21).
- **Não tem** tools de dados nem o regulamento nas instruções. Ele só sabe que dúvidas sobre regras vão para a ferramenta do regulamento.
- **`before_tool_callback`:** permite no máximo **uma** chamada a `especialista_regulamento` por turno (marca no state `temp:`, que dura só a invocação). A segunda chamada recebe um erro curto, sem executar. Na chamada permitida, copia o texto da mensagem do morador (`tool_context.user_content`, que no principal é a mensagem recebida) para a chave de state `pergunta_regulamento`. O `AgentTool` copia essa chave para a sessão do especialista (D19).
- **Mensagens com dois assuntos** (por exemplo, o passo 3, sobre reservas e visitantes): transfere para o especialista do primeiro assunto, que responde à sua parte e diz que o outro assunto pode ser pedido em seguida (D14).
- Pode usar o placeholder `{apartamento}` (vindo do state) para tratar o morador pelo apartamento, mas isso é só cortesia: nenhuma tool depende do que o modelo escreve.

### 6.2 `especialista_reservas` (subagente)
- **Responsabilidade:** consultar se uma data está livre, listar, criar e cancelar as reservas do apartamento da sessão.
- **Por que subagente:** a tool `reservar_area` pode pedir confirmação. O Runner do ADK 2.12.0 só devolve a aprovação ao agente que chamou a tool se esse agente estiver na árvore de subagentes (10.2). As chamadas de tool também ficam nos eventos da sessão, o que o passo 12 confere.
- `disallow_transfer_to_parent=True` e `disallow_transfer_to_peers=True` (D14). Ele atende o pedido recebido, e a próxima mensagem volta ao principal.
- A instrução lista as áreas válidas (`id`, `nome` e se há taxa), lidas do banco no momento de montar a instrução (instruction provider), nunca de texto fixo. Ela orienta o modelo a conferir a disponibilidade antes de reservar, a chamar `reservar_area` uma única vez por pedido e a não fazer perguntas na mesma resposta em que chama `reservar_area`, porque a aprovação acontece pela rota de confirmações. As regras não dependem disso.

### 6.3 `especialista_visitantes` (subagente)
- **Responsabilidade:** listar e autorizar visitantes do apartamento da sessão.
- **Por que subagente:** o mesmo motivo do 6.2, porque `autorizar_visitante` sempre pede confirmação. Também tem as transferências bloqueadas (D14) e a mesma orientação de não perguntar nada ao chamar `autorizar_visitante`.

### 6.4 `especialista_regulamento` (via `AgentTool`)
- **Responsabilidade:** responder dúvidas com base em `dados/regulamento.md`.
- **Por que AgentTool:** o `AgentTool` roda o especialista num Runner separado, com `InMemorySessionService` próprio (10.3). O **resultado bruto** da busca (os artigos) nunca entra nos eventos da sessão principal. O que entra é só a **resposta final** do especialista, como resultado da ferramenta.
- **Por que não `mode="single_turn"`:** a docstring do ADK desencoraja o uso direto do `AgentTool` e sugere esse modo. Mas ele roda **dentro** da sessão do pai e levaria os artigos para os eventos, o que quebraria a Garantia 4. O README registra esse motivo.
- **Fim do turno (D21):** com `skip_summarization=True`, a resposta do especialista é a resposta final do turno e vira `resposta` (9.2), sem o principal reescrevê-la.
- **Instrução:** chamar `buscar_no_regulamento` **uma vez**, responder só à pergunta com base nos artigos devolvidos, citando o artigo, sem reproduzir artigos que não respondem a ela. O limite de uma busca também é imposto em código (7, D19).

## 7. Tools

Regras comuns a todas as tools:
- **Nenhuma tool recebe apartamento como parâmetro.** O apartamento vem de `tool_context.state["apartamento"]` por meio de um único helper (`apartamento_da_sessao(tool_context)`). Se o state não tiver o apartamento, a tool falha sem gravar nada.
- **Validação compartilhada:** uma única função valida e normaliza a data (`AAAA-MM-DD`, com `date.fromisoformat`), a área (pelo `id` ou pelo `nome`, sempre normalizada para o `id`) e o nome do visitante (não vazio, sem espaços nas pontas e com espaços repetidos reduzidos a um; a grafia é preservada ao gravar). O corpo das tools, as funções de confirmação (D17) e o cálculo de `detalhes` (9.1) usam essa mesma função.
- **Retorno:** um dicionário pequeno com `status` e `mensagem` (texto curto em português, pronto para o morador), só com dados do próprio apartamento. Nenhuma mensagem cita códigos, nomes ou números de outros apartamentos.
- **`on_tool_error_callback`** nos especialistas: uma exceção inesperada vira `{status: "erro", mensagem: "..."}` sem detalhes internos, em vez de derrubar a rota.

| Tool | Agente | Pede confirmação? | Retorno (exemplos) |
|---|---|---|---|
| `listar_minhas_reservas()` | reservas | Não | `[{codigo, area, data}]`, só reservas ativas do apartamento |
| `verificar_disponibilidade(area, data)` | reservas | Não | `{area, data, disponivel: true\|false}`, **sem dizer de quem é** |
| `reservar_area(area, data)` | reservas | **Só se o pedido for válido e a área tiver taxa > 0** | `{status: "criada", codigo, area, data, taxa, mensagem}`; `{status: "recusada", motivo: "data_ocupada", mensagem}`; `{status: "invalida", mensagem}` |
| `cancelar_reserva(area, data)` | reservas | Não (regra 4) | `{status: "cancelada", codigo, area, data, mensagem}` ou `{status: "nao_encontrada", mensagem}` |
| `listar_meus_visitantes()` | visitantes | Não | `[{nome, data}]` |
| `autorizar_visitante(nome, data)` | visitantes | **Sempre que o pedido for válido** | `{status: "autorizado", nome, data, mensagem}` ou `{status: "invalida", mensagem}` |
| `buscar_no_regulamento(pergunta)` | regulamento | Não | `{capitulo, artigos: [texto, ...]}`, só artigos de **um** capítulo |

### 7.1 `reservar_area`
- É registrada como `FunctionTool(reservar_area, require_confirmation=precisa_confirmar_reserva)`.
- **`precisa_confirmar_reserva(area: str = "", data: str = "", tool_context=None) -> bool`:**
  - Recebe os mesmos argumentos que o ADK passa à tool, incluindo `tool_context` (10.1).
  - Nunca lança exceção.
  - Retorna `True` **só** se a área e a data forem válidas e a taxa da área **no banco** for maior que zero.
  - Em qualquer outro caso retorna `False`, e o corpo trata o pedido (grava se for área sem taxa, recusa se for inválido).
  - Não consulta a disponibilidade: a decisão depende só da área, que não muda entre o pedido e a aprovação.
- **Corpo, nesta ordem:**
  1. Valida os argumentos. Se forem inválidos, retorna `invalida` e não grava.
  2. **Segunda verificação:** se a área tem taxa e `tool_context.tool_confirmation` não existe ou não está `confirmed`, recusa sem gravar. Assim a Garantia 1 não depende só da configuração do `FunctionTool`.
  3. Grava conforme 8.3, com `chamada_id = "{session_id}:{function_call_id}"` (D18).

### 7.2 `cancelar_reserva(area, data)`
- Procura uma reserva **ativa do apartamento da sessão** com aquela área e data.
- Se não achar, retorna `nao_encontrada`, com a mesma resposta quer a reserva seja de outro apartamento, quer não exista (passo 4).
- Como só existe uma reserva ativa por área e data, a dupla área e data identifica a reserva sem precisar do código.

### 7.3 `autorizar_visitante`
- Usa `require_confirmation=precisa_confirmar_visitante(nome: str = "", data: str = "", tool_context=None)`, que retorna `True` sempre que o nome e a data forem válidos.
- Tem a mesma segunda verificação e a mesma idempotência por `chamada_id` de `reservar_area`.

### 7.4 Fim do turno depois de aprovar ou negar (D15)
Um `after_tool_callback` nos dois especialistas age quando `tool_context.tool_confirmation` não é `None`, ou seja, quando a tool está sendo executada por causa de uma resposta de confirmação:
- marca `tool_context.actions.skip_summarization = True`, e o ADK encerra o turno sem chamar o modelo (10.1);
- na **negação**, o ADK devolve `{"error": "This tool call is rejected."}`, e o callback troca isso por `{status: "negada", mensagem: "Tudo bem, nada foi feito."}`.

### 7.5 `buscar_no_regulamento`
- Na carga, o arquivo é lido com `encoding="utf-8"` e dividido em capítulos (`## Capítulo ...`) e artigos (`**Art. N...**` até o próximo artigo). O parser aceita quebras de linha `\r\n`.
- A consulta é o argumento `pergunta` **somado** à mensagem original do morador, lida de `tool_context.state["pergunta_regulamento"]` (6.1). Assim a busca não depende só das reformulações do principal e do especialista (D19). Observação: dentro do `AgentTool`, `tool_context.user_content` é o pedido que o **principal** escreveu, não a mensagem do morador.
- A busca normaliza a consulta (minúsculas, sem acentos, sem palavras vazias) e pontua os artigos por termos em comum, com bônus quando o termo aparece no título do capítulo.
- Escolhe o **capítulo** com maior pontuação e devolve até 4 artigos **desse capítulo**.
- **Limite em código (D19):** uma busca por execução do especialista. A chave é a sessão em memória do `AgentTool` (`tool_context.session.id`, nova a cada chamada), guardada numa estrutura do módulo. **Não usa state**, porque o `AgentTool` repassa o `state_delta` do filho para o pai (10.3). A checagem e a marcação acontecem sem `await` entre elas, e o registro tem tamanho limitado (por exemplo, guarda só as últimas mil sessões). A segunda busca recebe um erro curto.
- Exemplo esperado: "Até que horas a piscina funciona aos domingos?" leva ao Capítulo IV (Piscina), com o artigo que diz "Aos domingos e feriados, a piscina funciona das 9h às 20h" (linha 157 do regulamento).

## 8. Armazenamento

### 8.1 Arquivos
- `var/aurora.db`: dados do condomínio, gerenciados pelo nosso código.
- `var/sessoes.db`: sessões e eventos, gerenciados pelo `SqliteSessionService` do ADK.
- `var/` entra no `.gitignore`. Todos os caminhos são resolvidos a partir da raiz do projeto, não do diretório atual. A variável opcional `AURORA_DIR_VAR` troca a pasta `var/` (D25).

### 8.2 Esquema de `aurora.db`
```sql
CREATE TABLE apartamentos (numero TEXT PRIMARY KEY, morador TEXT NOT NULL);
CREATE TABLE areas (id TEXT PRIMARY KEY, nome TEXT NOT NULL, taxa REAL NOT NULL);
CREATE TABLE reservas (
  codigo       TEXT PRIMARY KEY,
  apartamento  TEXT NOT NULL REFERENCES apartamentos(numero),
  area         TEXT NOT NULL REFERENCES areas(id),
  data         TEXT NOT NULL,                       -- AAAA-MM-DD
  status       TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa','cancelada')),
  chamada_id   TEXT UNIQUE,                         -- "session_id:function_call_id" (NULL nas reservas iniciais)
  criada_em    TEXT NOT NULL,
  cancelada_em TEXT
);
-- Garantia 5: no máximo uma reserva ATIVA por área e data, valendo no instante da gravação.
CREATE UNIQUE INDEX ux_reserva_ativa_area_data ON reservas(area, data) WHERE status = 'ativa';
CREATE TABLE visitantes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  apartamento TEXT NOT NULL REFERENCES apartamentos(numero),
  nome        TEXT NOT NULL,
  data        TEXT NOT NULL,
  chamada_id  TEXT UNIQUE,
  criada_em   TEXT NOT NULL
);
-- Regra 5: todo código já usado, inclusive os iniciais. A restauração nunca apaga esta tabela.
CREATE TABLE codigos_emitidos (codigo TEXT PRIMARY KEY, emitido_em TEXT NOT NULL);
-- Liga o session_id ao apartamento (usado como user_id do ADK) para achar a sessão nas rotas.
CREATE TABLE sessoes (session_id TEXT PRIMARY KEY, apartamento TEXT NOT NULL, criada_em TEXT NOT NULL);
```

### 8.3 Acesso
- Usa o `sqlite3` da biblioteca padrão, com **uma conexão por operação** (`timeout=10`) e `PRAGMA journal_mode=WAL`.
- As transações são curtas, **sem `await` no meio**.
- **Gravação de reserva**, numa transação `BEGIN IMMEDIATE`. O lock de escrita já está tomado, então não há corrida entre os passos:
  1. Procura uma reserva com o mesmo `chamada_id`. Se existir com o mesmo apartamento, área e data, faz `COMMIT` e retorna essa reserva com `status: "criada"` (idempotente). Se existir com outros dados, é erro de programação: desfaz a transação e registra no log.
  2. Gera o código, insere em `codigos_emitidos` e insere em `reservas`.
  3. Faz `COMMIT`.
- Os `sqlite3.IntegrityError` são identificados pelas colunas citadas na mensagem do SQLite:
  - `reservas.area, reservas.data` (índice `ux_reserva_ativa_area_data`): retorna `recusada` / `data_ocupada`;
  - `codigos_emitidos.codigo`: gera outro código e tenta de novo.
- **Gravação de visitante:** o mesmo padrão, com a idempotência por `chamada_id`.
- As rotas de verificação leem direto daqui, sem passar pelo modelo.

### 8.4 Carga inicial e restauração
- **`uv run restaurar`:**
  - cria `var/` e o esquema se faltarem;
  - em uma única transação, apaga `apartamentos`, `areas`, `reservas` e `visitantes` e recarrega tudo dos JSON de `dados/` (as reservas iniciais entram com `status = 'ativa'` e `chamada_id` nulo);
  - registra os códigos iniciais em `codigos_emitidos` com `INSERT OR IGNORE`;
  - **não mexe** em `codigos_emitidos` (fora isso), em `sessoes` nem em `var/sessoes.db` (D9, D10).
- **Subida da API:** se `var/aurora.db` não existir, roda a mesma carga inicial. Se existir, **não altera nada**, porque o reinício não pode perder dados (Garantia 3).
- Todos os arquivos de `dados/` são lidos com `encoding="utf-8"`. No Windows, o padrão do Python seria cp1252 e corromperia os acentos ("Salão de festas").

## 9. API

O App do ADK se chama `aurora`. A API mantém um único `Runner(app=App(name="aurora", root_agent=assistente_aurora), session_service=SqliteSessionService(<raiz>/var/sessoes.db))`, com caminho absoluto (8.1) e sem `ResumabilityConfig` (10.2). Um `asyncio.Lock` por `session_id`, em memória, serializa as rotas de mensagem e de confirmação de uma mesma sessão (o que também evita o `StaleSessionError` do ADK). Sessões diferentes rodam em paralelo (passo 14).

| Rota | Comportamento |
|---|---|
| `POST /sessoes` `{"apartamento": "101"}` | Valida que o apartamento existe (se não existir, `422`, comportamento livre pelo enunciado). Cria a sessão no ADK com `user_id = apartamento` e `state = {"apartamento": "101"}`, grava `(session_id, apartamento)` em `sessoes` e responde **`201`** `{"session_id": "..."}`. |
| `POST /sessoes/{id}/mensagens` `{"texto": "..."}` | `422` se `texto` estiver vazio ou só com espaços. `404` se a sessão não existir. Roda `runner.run_async(user_id, session_id, new_message=Content(role="user", parts=[Part(text=texto)]))` e responde `200` com `resposta` (9.2) e `confirmacoes_pendentes` (9.1). |
| `POST /sessoes/{id}/confirmacoes` `{"id": "...", "confirmado": true}` | `404` se a sessão não existir. Toma o lock da sessão e, **já dentro dele**, responde **`409`** se `id` não estiver entre as pendentes desta sessão (9.1), inclusive quando já foi respondida ou substituída, e nada é executado. Essa checagem é **obrigatória**: sem ela, um id desconhecido faz o ADK lançar `ValueError` e a rota responderia `500`. Caso contrário, roda o Runner com `new_message = Content(role="user", parts=[Part(function_response=FunctionResponse(id=id, name="adk_request_confirmation", response={"confirmed": confirmado}))])`, confere a execução (9.3) e responde `200` no mesmo formato da rota de mensagens. |
| `GET /sessoes/{id}/eventos` | `404` se a sessão não existir. `200` com a lista de todos os eventos, na ordem do serviço de sessão, com o conteúdo completo (`event.model_dump(mode="json", by_alias=True, exclude_none=True)`). |
| `GET /apartamentos/{n}/reservas` | `200` com `[{"codigo", "area", "data"}]`, só reservas **ativas**, ordenadas por data. |
| `GET /apartamentos/{n}/visitantes` | `200` com `[{"nome", "data"}]`, ordenados por data. |

- A rota de mensagens aceita **só texto**. Não existe caminho pelo qual o texto do morador vire uma resposta de confirmação.
- Se o modelo falhar durante a rota de **mensagens** (por exemplo, cota esgotada depois das novas tentativas), há dois casos:
  - a execução já tinha gravado alguma resposta de tool nossa, ou seja, houve efeito colateral (como a reserva da quadra): a rota responde `200`, com um texto curto de aviso e as pendências;
  - nada foi executado: a rota responde `503` com uma mensagem curta.
- A rota de **confirmações** não chama o modelo depois de executar a tool (D15), então a disputa do passo 14 não depende da cota.

### 9.1 Como montar `confirmacoes_pendentes`
Depois de cada execução, a API relê a sessão e percorre os eventos:
1. **Candidata:** cada `function_call` com `name == "adk_request_confirmation"`. O `id` é o `id` dessa chamada, `acao` é `args.originalFunctionCall.name` (ex.: `reservar_area`) e `detalhes` é `args.originalFunctionCall.args`, normalizado pela validação compartilhada (ex.: `{"area": "salao-de-festas", "data": "2030-04-20"}` ou `{"nome": "Joana Ribeiro", "data": "2030-04-21"}`).
2. **Respondida:** existe, em qualquer evento e de **qualquer autor**, uma `function_response` com o mesmo `id`. Isso cobre a resposta do morador e o encerramento que o ADK grava quando uma invocação é abortada.
3. **Substituída (D16):** existe uma candidata **mais nova**, respondida ou não, com a mesma `acao` e os mesmos `detalhes` normalizados. "Mais nova" segue a ordem dos eventos e, dentro de um mesmo evento, a ordem das partes. Na comparação, o `nome` é comparado sem diferenciar maiúsculas de minúsculas.
4. Pendente é a candidata que não está nem respondida nem substituída. A mesma função serve para responder `confirmacoes_pendentes` e para decidir o `409`. Como tudo vem dos eventos gravados em SQLite, as pendências sobrevivem ao reinício.

### 9.2 Como montar `resposta`
- Usa **só os eventos emitidos por esta chamada** de `run_async`, e não um filtro por `invocation_id`, porque na retomada o ADK reaproveita o `invocation_id` da invocação original.
- Concatena, em ordem, o texto (ignorando `part.thought`) dos eventos de agente que são resposta final.
- Se o turno terminou na resposta de uma tool nossa com `skip_summarization` (7.4), usa o campo `mensagem` desse resultado. Se terminou na resposta do especialista do regulamento (D21), usa o texto que ele devolveu.
- A resposta "requires confirmation" que o ADK grava ao criar uma pendência **nunca** vira `resposta`, porque é um texto interno, em inglês.
- Se a chamada criou uma pendência nova e não houver texto, `resposta` recebe o texto fixo "Para concluir, aprove a confirmação pendente." Esse texto é obrigatório, para o morador saber que deve aprovar pela rota de confirmações, e não pelo chat. Fora desse caso, `resposta` pode ser `""`.

### 9.3 Proteção contra a "armadilha silenciosa"
Depois de rodar a resposta de uma confirmação, a API confere, nos eventos emitidos, uma `function_response` de autor diferente de `user` para o `originalFunctionCall.id` daquela confirmação. Se ela não existir, a aprovação não chegou à tool: a API registra o erro no log e responde `500` com uma mensagem clara. Uma falha barulhenta é melhor que um `200` mentiroso. No funcionamento normal isso nunca acontece, e o spike prova que não acontece.

## 10. O que o código do ADK 2.12.0 mostrou

Código lido em `google_adk-2.12.0` (wheel do PyPI) e conferido por um revisor independente. Esta seção é a base técnica das decisões, e o spike (14.1) confirma tudo na prática.

### 10.1 Ciclo da confirmação
- **`require_confirmation` como função** (`tools/function_tool.py`, `check_require_confirmation` e `_prepare_invocation_args`):
  - a função recebe os argumentos do modelo filtrados pela assinatura da **tool**, mais `tool_context` se a tool o declara;
  - é chamada como `fn(**kwargs)`, **antes** da checagem de argumentos obrigatórios;
  - é chamada em até três pontos: no portão de confirmação (`flows/llm_flows/tools/_caller.py`), em `FunctionTool.run_async` e na validação da aprovação (`flows/llm_flows/tools/_confirmation.py`). Ao criar uma pendência, roda uma vez (só no portão); numa área sem taxa, duas; na aprovação, três.
  - Por isso a D17 exige `tool_context=None`, valores padrão e nenhuma exceção.
- **Quando a confirmação é exigida:**
  - o ADK responde à chamada com o erro "requires confirmation";
  - grava um evento com `function_call` `adk_request_confirmation`, cujos argumentos trazem `originalFunctionCall` (com `id`, `name` e `args`) e `toolConfirmation` (`flows/llm_flows/tools/_functions.py`, `generate_request_confirmation_event`). O autor do evento é o agente que chamou a tool;
  - marca `skip_summarization`, e o turno termina sem chamar o modelo (`_caller.py`). Por isso `resposta` pode vir vazia.
- **A resposta do cliente** é uma `function_response` do usuário com o id da chamada `adk_request_confirmation` e `{"confirmed": bool}` (`tools/tool_confirmation.py`, `extra="forbid"`).
  - Com `confirmed: false`, a tool não executa e o resultado é "This tool call is rejected." (`tools/_confirmation_utils.py`).
  - Com `true`, a tool é reexecutada.
  - Nos dois casos, **sem** `skip_summarization` o fluxo chama o modelo de novo. Com `skip_summarization`, a resposta da tool é final e o modelo não é chamado (`flows/llm_flows/base_llm_flow.py`, `_run_one_step_async`; `events/event.py`, `is_final_response`). Esta é a base da D15.
- **O processador de confirmação** só age se o agente atual for o autor da chamada original. Ele também ignora uma aprovação já consumida, com `end_invocation` (`flows/llm_flows/tools/_confirmation.py`).

### 10.2 Quem recebe a aprovação
- Com o agente raiz sendo um `LlmAgent` em modo chat e **sem subagentes `mode="task"`**, o Runner usa o seletor de agente `_agent_router.find_agent_to_run` (`runners.py`, `_uses_legacy_sub_agent_picker`) e roda o agente escolhido pelo runtime de nós (`_run_node_async`).
- **Resposta a uma chamada:** se a última mensagem é uma `function_response` do usuário, o seletor roteia para o **autor** da chamada (`flows/llm_flows/core/_resume.py`, `decide_resume_action`, retorno `ROUTE_TO_AUTHOR`). Isso independe de `ResumabilityConfig` e de o agente poder transferir.
- **Como o autor é encontrado:** pelo nome, com `root_agent.find_agent`, que percorre os **subagentes**. Um agente que só existe dentro de um `AgentTool` não é encontrado. Por isso as tools com confirmação ficam em subagentes (D3), e os nomes dos agentes não podem mudar.
- **Mensagem de texto nova:** o seletor devolve o último agente que respondeu **se ele puder transferir**. Senão, devolve o principal (`agents/_agent_router.py`, `is_transferable_across_agent_tree`). Com a D14, toda mensagem de texto começa no principal.
- **Cuidado com `ResumabilityConfig`:** com `is_resumable=True`, `decide_resume_action` também roteia para o autor quando a resposta **não** é do morador (`_resume.py`: `answer_event.author == 'user' or is_resumable`). Pela D15, o último evento depois de aprovar ou negar é a resposta da tool do especialista. Com a retomabilidade ligada, a mensagem de texto seguinte iria para o especialista, e a D14 deixaria de valer. Por isso o projeto roda sem `ResumabilityConfig`.
- **Sem pré-checagem:** um id desconhecido na resposta faz `_resolve_invocation_id_from_fr(strict=True)` lançar `ValueError` (`workflow/_node_runner_utils.py`). Daí o `409` obrigatório em 9.

### 10.3 Isolamento do AgentTool
`tools/agent_tool.py`:
- cria `Runner(..., session_service=InMemorySessionService())`;
- copia todo o state do pai para a sessão do filho;
- roda o agente;
- repassa ao pai o `state_delta` dos eventos do filho;
- devolve o texto do último evento com conteúdo, que entra na sessão pai como `function_response` do `AgentTool`.

Os eventos internos (incluindo o resultado bruto de `buscar_no_regulamento`) não vão para a sessão pai.

### 10.4 Sessões em SQLite
`sessions/sqlite_session_service.py`: `SqliteSessionService(db_path)` usa `aiosqlite` (dependência do ADK) com uma conexão por operação, espera padrão de 5 s quando o banco está travado e sem WAL. É o serviço que `cli/service_registry.py` e `cli/utils/local_storage.py` usam, ou seja, o do `adk web`.
- Os eventos são recarregados por `ORDER BY timestamp, rowid`. O evento `adk_request_confirmation` é criado depois da resposta "requires confirmation", mas gravado antes dela, então a ordem dos dois pode se inverter depois do reinício. Pela leitura de `decide_resume`, isso não muda o resultado, e o spike confirma.
- Há uma checagem de sessão desatualizada (`StaleSessionError`) que o lock por sessão evita.

## 11. As cinco garantias

| Garantia | Onde fica | Por que não depende do modelo |
|---|---|---|
| **1. Cobrança ou acesso só com confirmação** | `require_confirmation=precisa_confirmar_reserva` e `precisa_confirmar_visitante` (7.1, 7.3); segunda verificação no corpo das tools; `after_tool_callback` do fim de turno (7.4); pendências, substituição de duplicatas e `409` na API (9.1); conferência da execução (9.3); `chamada_id UNIQUE` (8.2). | Quem decide se precisa confirmar é o código (taxa lida do banco). A aprovação só nasce na rota de confirmações, como `function_response`, e o texto do morador nunca vira aprovação. Um `id` fora das pendências recebe `409` antes de qualquer execução. O banco impede executar a mesma chamada duas vezes. |
| **2. Cada sessão pertence a um apartamento** | `POST /sessoes` grava o apartamento no state e na tabela `sessoes`; o helper `apartamento_da_sessao`; tools sem parâmetro de apartamento; consultas sempre filtradas pelo apartamento da sessão. | O modelo não tem como escolher o apartamento: nenhuma tool aceita esse parâmetro e nenhum código regrava o state depois da criação. As tools nunca devolvem dados de outro apartamento, então esses dados não chegam aos eventos. A disponibilidade só diz livre ou ocupada. |
| **3. Nada se perde no reinício** | `SqliteSessionService("var/sessoes.db")` e `var/aurora.db`; a subida não altera um banco existente (8.4). | Tudo fica em disco. As pendências são derivadas dos eventos gravados. |
| **4. O regulamento é consultado, não carregado** | O principal não tem o regulamento nas instruções; o `AgentTool(especialista_regulamento)` é isolado (10.3); `buscar_no_regulamento` devolve artigos de um único capítulo; limites de uma busca e de uma chamada por turno (D19). | O resultado bruto da busca vive numa sessão em memória descartável. Na sessão principal só entra a resposta do especialista, construída a partir de **uma** busca de **um** capítulo, com os limites impostos em código. |
| **5. Dois moradores, uma reserva** | Índice único parcial `ux_reserva_ativa_area_data` e gravação com `BEGIN IMMEDIATE` (8.3); fim de turno sem modelo (D15). | A exclusividade é do banco, no instante do `INSERT`. Quem perde recebe "data ocupada" como resultado da tool, e a API responde `200` sem precisar do modelo. |

## 12. Configuração e comandos

- **`.env.example`**, só com os nomes (D20):
  - `GOOGLE_API_KEY=`
  - `GEMINI_MODELO=` (opcional; vazio significa o padrão D8)
  - `AURORA_DIR_VAR=` (opcional; vazio significa `<raiz>/var`, D25)
- **`config.py`:** carrega o `.env` com `override=True` (o `.env` do projeto ganha de variáveis globais do ambiente) e define `GOOGLE_GENAI_USE_VERTEXAI=FALSE` no processo.
- **Pré-requisitos:** `uv` instalado. O `uv` baixa o Python 3.12 se for preciso.
- **Comandos:**
  1. `uv sync`
  2. `cp .env.example .env` e preencher `GOOGLE_API_KEY`
  3. `uv run restaurar`
  4. `uv run api`, que sobe em `127.0.0.1:8000` sem auto-reload e para com Ctrl+C. Clientes como `curl localhost:8000` e as bibliotecas HTTP do Python tentam o IPv4, então `localhost` funciona.
- **README:** explica que `GEMINI_MODELO` troca o modelo de todos os agentes e indica a alternativa da D8 para o caso de a cota do modelo padrão acabar.
- **`pyproject.toml`:**
  - `[project.scripts]` com `api = "aurora.servidor:main"` e `restaurar = "aurora.restaurar:main"`.
  - Backend de build `hatchling`, com `[tool.hatch.build.targets.wheel] packages = ["src/aurora"]`, para o `uv sync` funcionar num clone limpo qualquer que seja o nome do projeto.
  - `google-adk==2.12.0`; `fastapi`, `uvicorn` e `python-dotenv` declarados explicitamente.
  - Dependência de desenvolvimento: `pytest`.

## 13. Estrutura de pastas

```
pyproject.toml, uv.lock, .python-version, .env.example, .gitignore (+ var/ e .claude/settings.local.json)
README.md                  # entrega (substitui o enunciado no fim)
CLAUDE.md
.claude/skills/            # referência do ADK para o Claude Code (D22)
docs/enunciado.md          # cópia do enunciado (D12)
docs/superpowers/specs/    # este documento
dados/                     # intocável
src/aurora/
  config.py                # caminhos, .env, modelo, AI Studio forçado
  banco.py                 # conexão, esquema, carga inicial
  repositorio.py           # reservas, visitantes, áreas, sessões, códigos (SQL)
  validacao.py             # validação e normalização de área, data e nome
  regulamento.py           # divisão em capítulos/artigos e busca
  ferramentas.py           # tools, funções de confirmação, apartamento_da_sessao
  agentes.py               # os quatro agentes, callbacks e o App
  confirmacoes.py          # pendências, substituição de duplicatas e conferência (9.1, 9.3)
  api.py                   # FastAPI
  servidor.py              # main() do `uv run api`
  restaurar.py             # main() do `uv run restaurar`
tests/                     # pytest das partes determinísticas
tests/integracao/          # pilha real com o Gemini falso (D24)
scripts/roteiro_avaliador.py  # reproduz o fluxo do avaliador contra a API
var/                       # bancos SQLite (fora do Git)
```

## 14. Verificação

### 14.1 Spike primeiro (descartável)
Antes de construir o resto, um script com ADK 2.12.0, `SqliteSessionService` em arquivo e a **topologia final** verifica, com o Gemini de verdade. A topologia final é: principal com os dois subagentes de transferência bloqueada, o `AgentTool`, as funções de confirmação com `tool_context` e o `after_tool_callback` do fim de turno. Os cenários:
1. Um pedido para área com taxa gera `adk_request_confirmation` e o turno termina.
2. `confirmed: false`: a tool não executa, e o turno termina sem chamar o modelo.
3. Repetir o pedido e responder `confirmed: true` **em outro processo**, simulando o reinício: a tool executa **uma vez**, quem processa a aprovação é o especialista autor, e o turno termina sem chamar o modelo.
4. Reenviar a mesma aprovação: a tool não executa de novo.
5. Área sem taxa: executa sem confirmação.
6. Pendência antiga aprovada depois de outras invocações e de um reinício:
   1. pendência de reserva aberta;
   2. pergunta ao regulamento;
   3. pedido de visitante, que cria outra pendência;
   4. reinício;
   5. aprovar a pendência do item 1 e depois a do item 3;
   6. mensagem de texto.

   Cada tool executa uma vez, quem processa cada aprovação é o especialista autor, e a mensagem do item 6 começa no principal.
7. Duas sessões aprovando ao mesmo tempo a mesma área e data: uma grava, a outra recebe `data_ocupada`, e as duas terminam sem erro.
8. `AgentTool`: os eventos da sessão principal não contêm o resultado bruto da busca.
9. A ordem dos eventos relidos do SQLite depois do reinício não atrapalha a aprovação.
10. Quantas chamadas ao modelo o fluxo faz e se o modelo padrão (D8) estoura a cota.
11. O fluxo de visitantes, com outro especialista e outra tool: pedido, aprovação e reinício.
12. Uma mensagem de texto depois de uma aprovação começa no agente principal.
13. Duas chamadas iguais na mesma resposta do modelo viram uma única pendência listada.
14. Os limites da D19: a segunda busca e a segunda chamada do especialista do regulamento no mesmo turno são recusadas.
15. Duas pendências **diferentes** criadas na mesma resposta do modelo, aprovadas em sequência: cada uma executa uma vez.
16. O especialista do regulamento recebe `pergunta_regulamento` no state e a usa na busca. A pergunta da piscina traz "20h" mesmo quando o principal reformula o pedido, e essa resposta encerra o turno (D21).

Se algum cenário falhar, quem constrói **para** e volta ao usuário com o diagnóstico (D23). Os planos B possíveis, nesta ordem, são: ligar `ResumabilityConfig(is_resumable=True)`; usar a versão 2.9.1. **Qualquer plano B exige refazer a seção 10 e o spike inteiro.** Em especial, ligar a retomabilidade desfaz a D14 (10.2) e exige outra forma de mandar as mensagens de texto ao principal. O resultado do spike é registrado no plano antes de seguir.

### 14.2 Testes automatizados (pytest, sem modelo)
- **Repositório:**
  - o índice único barra a segunda reserva ativa, inclusive com duas threads gravando ao mesmo tempo;
  - uma reserva cancelada libera a data;
  - a mesma `chamada_id` não grava de novo e devolve o registro existente, inclusive quando a reserva original continua ativa;
  - os códigos seguem o formato `RSV-N` + 8 consoantes, não têm dígitos e nunca repetem, inclusive depois de restaurar;
  - a restauração volta ao estado dos JSON.
- **`confirmacoes.py`**, com eventos sintéticos: pendente, respondida pelo usuário, encerrada por outro autor, substituída por uma duplicata mais nova, pendente com uma mensagem de texto depois, e inexistente.
- **`regulamento.py`:** a pergunta da piscina e reformulações prováveis dela (ex.: "horário da piscina no domingo") levam ao Capítulo IV, inclusive somadas a um pedido típico do principal (ex.: "O morador quer saber o horário de funcionamento da piscina aos domingos"); o arquivo é lido corretamente em UTF-8; a busca nunca devolve artigos de dois capítulos; a segunda busca na mesma sessão é recusada.
- **`ferramentas.py`:**
  - nenhuma tool tem parâmetro `apartamento` (inspeção das assinaturas);
  - as funções de confirmação são testadas **através de** `FunctionTool(...).check_require_confirmation(args, tool_context)`, com argumentos válidos, inválidos e faltando;
  - segunda verificação de confirmação;
  - validação compartilhada.
- **API com um Runner falso:** `201`, `404`, `409` (inclusive para pendência substituída), `422` para texto vazio, o texto fixo de 9.2 e a conferência de 9.3.
- **Integração (`tests/integracao/`, D24):** requisições pela API com o Runner, os agentes, as tools e os bancos SQLite reais, numa pasta temporária. O Gemini é substituído por um modelo falso com roteiro. Os casos cobertos:
  - reserva com taxa: pendência com `detalhes` normalizados; mesma contagem de eventos depois do reinício; aprovação depois do reinício executa uma vez, sem nova chamada ao modelo; o reenvio recebe `409`;
  - negação não grava;
  - quadra sem confirmação;
  - visitante pendente mesmo com "já estou confirmando";
  - disputa entre duas sessões: as duas respostas `200` e uma única reserva;
  - cancelamento da reserva de outro apartamento: nada vaza nos eventos nem na resposta;
  - a mensagem de texto depois de uma aprovação começa no principal;
  - regulamento: o resultado bruto da busca não entra nos eventos, e o turno termina na resposta do especialista.

### 14.3 Roteiro do avaliador (com modelo)
`scripts/roteiro_avaliador.py` executa os passos 1 a 14 contra a API real e confere cada verificação. No passo 13, o script para e sobe o servidor de novo. Ele é rodado antes de declarar a entrega pronta. Ele também confere que `dados/` é idêntico ao do commit `be87e1d` (`git diff --exit-code be87e1d -- dados/`) e que os arquivos e funções citados na seção Garantias do README existem.

## 15. Passos do avaliador e o que garante cada um

| Passo | O que garante |
|---|---|
| 1 | `uv sync` (com `packages` do hatch), `uv run restaurar` e `uv run api`; as rotas de verificação leem o banco recarregado dos JSON. |
| 2 | `POST /sessoes` responde `201`. |
| 3 | As tools só devolvem dados do apartamento da sessão, então `RSV-4821` e `Marina Duarte` nunca entram nos eventos nem na resposta. |
| 4 | `cancelar_reserva` filtra pelo apartamento da sessão e devolve `nao_encontrada`, sem código. |
| 5 | `cancelar_reserva` não pede confirmação; a reserva vira `cancelada` e some da rota de verificação. |
| 6 | A quadra tem taxa 0, então `precisa_confirmar_reserva` retorna `False` e a reserva grava direto. |
| 7 | O salão tem taxa, então a confirmação fica pendente com `detalhes` de área e data normalizados. `false` não grava e encerra o turno sem o modelo. |
| 8 | Uma eventual duplicata da pendência é substituída pela mais nova. `true` grava uma vez; o reenvio recebe `409`; `chamada_id` e o ADK são barreiras extras. |
| 9 | `id-inexistente` recebe `409`; uma sessão inexistente recebe `404`. |
| 10 | O índice único (ou a disponibilidade) recusa; as tools nunca revelam código nem apartamento do dono; os códigos novos não têm dígitos, então não contêm `RSV-4821` nem `302`. |
| 11 | `autorizar_visitante` pede confirmação sempre que o pedido é válido; o texto "já estou confirmando" não tem efeito. |
| 12 | A mensagem vai ao principal (D14), que chama o especialista do regulamento uma vez. A busca usa a mensagem do morador e traz o capítulo da piscina com "20h", e a resposta do especialista vira `resposta` sem reescrita (D21); os eventos mostram as chamadas de tool dos especialistas. |
| 13 | Tudo em SQLite; a subida não reinicia dados; as pendências e os eventos são relidos do disco; os códigos novos começam com `RSV-N`. |
| 14 | Lock só por sessão, então as duas sessões rodam em paralelo. O índice único deixa uma vencer, a outra recebe `data_ocupada`, e as duas respondem `200` sem chamar o modelo depois da aprovação (D15). |
| 15 | Versão exata fixada, `dados/` intocado, `.env` ignorado e `.env.example` sem valores, quatro agentes, tools sem parâmetro de apartamento, principal sem regulamento, índice único e README apontando arquivos reais. |

## 16. Riscos

| Risco | Mitigação |
|---|---|
| A retomada da confirmação não funcionar na prática (a armadilha do enunciado) | Spike com a topologia final e reinício entre o pedido e a aprovação (14.1); conferência barulhenta em 9.3; plano B definido. |
| Cota do plano gratuito estourar no roteiro | Novas tentativas automáticas, modelo configurável, nenhuma chamada ao modelo depois de aprovar ou negar, e medição no spike. |
| O modelo não chamar a tool certa ou fazer perguntas | O avaliador pode responder perguntas, e o principal recebe toda mensagem (D14). As regras não dependem do modelo. |
| "database is locked" no passo 14 | Dois arquivos SQLite, WAL, `timeout=10`, transações curtas e espera de 5 s no ADK. |
| Detalhe de API do ADK diferente do lido no código | O código-fonte da versão fixada é a referência (CLAUDE.md), e o spike valida. |
| Acentos corrompidos no Windows (cp1252) | `encoding="utf-8"` em toda leitura de `dados/` e parser tolerante a `\r\n` (7.5, 8.4). |
| README da entrega apontar trechos que mudaram | O README é a última tarefa do plano, e o roteiro confere os arquivos e funções citados. |

## 17. O que fica para quem construir

- Redação exata das instruções dos agentes e das `mensagem` das tools, respeitando as regras deste documento.
- Fórmula exata de pontuação da busca no regulamento, desde que devolva um único capítulo e passe no teste da piscina.
- Nomes internos de funções e módulos dentro de `src/aurora/`, desde que o README aponte os nomes reais.
- Formato dos erros fora do contrato (`422`, `500`, `503`).
- Número de novas tentativas e espera entre elas.
- Detalhes do script do roteiro e dos testes.
