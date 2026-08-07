---
id: T-012
title: Atualiza a lista de modelos do painel de configurações do jogo
status: ready
blockedBy: []
files: [frontend/src/components/SettingsPanel.jsx]
---

## O que fazer

No painel de configurações do jogo, o campo de modelo mostra hoje uma lista
antiga: da Anthropic aparecem Haiku 4.5, Sonnet 4.6 e Opus 4.6; da DeepSeek
aparecem `deepseek-v4-flash` e `deepseek-v4-pro`.

Depois desta tarefa, escolhendo Anthropic o jogador vê **Claude Opus 5** (opção
padrão, a primeira da lista) e **Claude Sonnet 5**; escolhendo DeepSeek ele vê
apenas **deepseek-v4-flash**, que é o único modelo DeepSeek que o projeto usa.

## Onde mexer

`frontend/src/components/SettingsPanel.jsx`, constante `PROVIDERS` (linha 6). Ela
é um array de `{ id, label, models }` e alimenta tanto o seletor de provedor
quanto o de modelo (`currentProviderModels`, linha 24). Trocar as listas de
modelos por:

```js
const PROVIDERS = [
  { id: 'deepseek', label: 'DeepSeek', models: ['deepseek-v4-flash'] },
  { id: 'anthropic', label: 'Anthropic', models: ['claude-opus-5', 'claude-sonnet-5'] },
  { id: 'openai', label: 'OpenAI', models: ['gpt-5.6-sol'] },
]
```

A ordem importa: `handleProviderChange` (linha 26) seleciona
`providerModels[0]` ao trocar de provedor, então `claude-opus-5` precisa ser o
primeiro item da Anthropic para virar o padrão quando o jogador escolher esse
provedor.

Nenhum outro arquivo do frontend precisa mudar: `frontend/src/store.js` já tem
`llmProvider: 'deepseek'` e `llmModel: 'deepseek-v4-flash'` como padrão, e
`frontend/src/api.js` já usa esses mesmos valores como fallback ao montar a
requisição — ambos continuam corretos.

As configurações do jogador ficam salvas no navegador. `frontend/src/store.js`
normaliza qualquer configuração OpenAI restaurada para `gpt-5.6-sol` e regrava
o `localStorage`, evitando que modelos removidos continuem sendo enviados.

## Fora do escopo

- Mexer no backend (defaults da API, política de modelo auxiliar).
- Mexer no proxy.
- Criar um segundo seletor para escolher o modelo das tarefas de bastidor: essa
  escolha é decidida automaticamente pelo backend.

## Pronto quando

- [ ] Com o provedor Anthropic selecionado, a lista de modelos tem exatamente
      `claude-opus-5` e `claude-sonnet-5`, nessa ordem.
- [ ] Com o provedor DeepSeek selecionado, a lista de modelos tem exatamente
      `deepseek-v4-flash`.
- [ ] Com o provedor OpenAI selecionado, a lista tem exatamente `gpt-5.6-sol`.
- [ ] `deepseek-v4-pro` e os modelos `claude-*-4-*` não aparecem mais no painel.
- [ ] `cd frontend && npx eslint src/components/SettingsPanel.jsx` não acusa erro.

## Como testar (humano)

1. Inicie o jogo e abra a tela de configurações (ícone de engrenagem).
2. No campo de provedor, escolha "Anthropic".
3. O campo de modelo tem que passar a mostrar apenas duas opções, com
   `claude-opus-5` já selecionado.
4. Troque o provedor para "DeepSeek": o campo de modelo tem que mostrar só
   `deepseek-v4-flash`.
5. Salve com DeepSeek selecionado, feche o painel e jogue um turno. A narrativa
   tem que continuar funcionando.
