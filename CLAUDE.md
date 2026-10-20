# Residencial Aurora — desafio de criação de agente (MBA IA)

## Início de cada sessão (obrigatório)
Antes de qualquer outra ação, leia o `HANDOFF.md` na raiz do projeto. Ele traz o estado atual,
o procedimento da sessão, os pontos que exigem o usuário e os cuidados de cada tarefa. Ao
encerrar a sessão, atualize nele o "Estado atual" e o "Registro de sessões" e commite o arquivo.

Assistente de condomínio feito com Google ADK, exposto por uma API em `http://localhost:8000`.
O enunciado completo é o `README.md` original do commit `be87e1d`. Ele será substituído pelo
README da entrega, então consulte o enunciado com `git show be87e1d:README.md`.

## Regras fixas do enunciado
- Nunca alterar os arquivos de `dados/`: eles precisam ficar idênticos aos do repositório base.
- Nunca versionar o `.env` nem colocar chaves em código ou documentação. Variáveis novas vão para o `.env.example`, sem valor.
- Python 3.12+, projeto gerenciado com `uv` (`pyproject.toml` e `uv.lock` versionados).
- Google ADK série 2, versão 2.2.0 ou superior, com a versão exata fixada.
- Modelos Gemini com chave do Google AI Studio (`GOOGLE_API_KEY`), não Vertex AI.

## Decisões já tomadas
- Armazenamento em SQLite, sem Docker e sem serviço externo.
- API com FastAPI.
- Design aprovado: `docs/superpowers/specs/2026-10-19-residencial-aurora-design.md` (decisões D1 a D25).
- Plano: `docs/superpowers/plans/2026-10-19-assistente-aurora.md`, executado com
  `superpowers:subagent-driven-development`, uma task de cada vez, na branch `feat/assistente-aurora`.
- Merge na `main` e `git push` só com autorização explícita do usuário.

## Skill `google-agents-cli-adk-code`
Use essa skill **só como referência da API do ADK** (agentes, tools, confirmação, retomada,
estado, sessões, Runner). Ignore as instruções dela que levam ao processo do `agents-cli`:
- não ative a skill `google-agents-cli-workflow` nem instale outras skills do `agents-cli`;
- não instale nem rode o `agents-cli` (`scaffold`, `info`, `run`, `eval`, `deploy`, `playground`);
- não use Vertex AI, Gemini Enterprise, Secret Manager nem Google Cloud.

A estrutura do projeto, a API e o contrato vêm do enunciado, não da skill. Quando a skill e o
comportamento real divergirem, vale o código-fonte do ADK na versão fixada no projeto.
