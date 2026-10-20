---
name: google-agents-cli-adk-code
description: >
  This skill should be used when the user wants to "write agent code",
  "build an agent with ADK", "add a tool", "create a callback", "define an agent",
  "use state management" — in a project that needs ADK (Agent Development Kit) API
  patterns and code examples in Python.
  It provides a quick reference for agent types, tool definitions, tool confirmation,
  human-in-the-loop, orchestration patterns, callbacks, state and sessions.
metadata:
  author: Google
  license: Apache-2.0
  version: 1.10.0
  source: https://github.com/google/agents-cli/tree/main/skills/google-agents-cli-adk-code
---

# ADK Code Reference (Python)

> **Adaptada para este projeto.** Cópia reduzida da skill `google-agents-cli-adk-code`
> do repositório `google/agents-cli` (Apache-2.0). Foram removidos: as referências de Go,
> de agentes de voz (Live) e da Workflow API em grafo; o catálogo de receitas (`samples.md`);
> e as instruções do processo `agents-cli` (scaffold, workflow, eval, deploy), que não se
> aplicam aqui. Se `references/adk-python.md` citar algum desses arquivos ou o `agents-cli`,
> ignore a citação. As regras do projeto estão no `CLAUDE.md`.

## Referências

| Referência | Quando ler |
|------|-------------|
| `references/adk-python.md` | API principal do ADK em Python: `Agent`, tools, confirmação de tools, human-in-the-loop, callbacks, plugins, estado, sessões, multiagentes (`sub_agents`, `AgentTool`) e Runner. |
| Código-fonte do ADK instalado | Assinaturas e comportamento exatos da versão fixada no projeto. Veja "Inspecting ADK Source Code" em `references/adk-python.md`. **Em caso de divergência, vale o código-fonte.** |
| `curl https://adk.dev/llms.txt` | Índice da documentação oficial (título e URL de cada página). Depois, buscar a página específica. |
