---
id: T-002
title: Carregar no painel de devtools o histórico de traces salvo no servidor
status: ready
blockedBy: [T-001]
files: [frontend/src/api.js, frontend/src/store.js, frontend/src/components/GameCanvas.jsx, frontend/src/components/DevtoolsPanel.jsx]
---

## O que fazer

O painel "LLM Devtools" (ícone de terminal na barra de botões do jogo) só mostra os
turnos jogados desde o último carregamento da página. Depois desta tarefa ele passa
a mostrar também os turnos salvos no servidor: ao abrir a campanha e ao abrir o
painel, a lista de turnos vem do banco, com data/hora e o texto da ação que originou
cada turno. O botão da lixeira dentro do painel passa a apagar o histórico no
servidor, não só na tela.

## Onde mexer

Este ticket depende do T-001, que cria as rotas `GET /api/game/{campaign_id}/traces?limit=N`
(responde `{"traces": [...]}`) e `DELETE /api/game/{campaign_id}/traces` (responde
`{"deleted": n}`). Cada item de `traces` tem `key`, `label`, `action`, `created_at`,
`entries` e `summary`, em ordem cronológica crescente. `entries` é exatamente a
mesma lista que hoje chega pelo frame SSE `[TRACE]`.

**`frontend/src/api.js`.** Adicione duas funções exportadas no estilo das que já
existem no arquivo (`fetchJournal`, `fetchInventory`), usando a constante `BASE`:

- `fetchTraces(campaignId, limit = 25)` — `GET ${BASE}/game/${campaignId}/traces?limit=${limit}`;
  devolve `data.traces` quando a resposta é ok, e `[]` em qualquer falha (não lance
  erro: devtools não pode derrubar a tela do jogo).
- `deleteTraces(campaignId)` — `DELETE ${BASE}/game/${campaignId}/traces`; devolve o
  JSON quando ok, `{ deleted: 0 }` em falha.

Não mexa em `streamAction` nem no tratamento do frame `[TRACE]`, que continua
existindo.

**`frontend/src/store.js`.** O store já tem `traces`, `pushTrace` e `clearTraces`.
Adicione `setTraces: (traces) => set({ traces: Array.isArray(traces) ? traces.slice(-25) : [] })`.
Em `pushTrace`, troque a geração de `key` de `` `tr${s.traces.length + 1}` `` por algo
garantidamente único mesmo convivendo com as chaves vindas do servidor (por exemplo
`` `tr${Date.now()}-${s.traces.length + 1}` ``); mantenha o `label` e o corte em 25
como estão.

**`frontend/src/components/GameCanvas.jsx`.** O componente já desestrutura
`traces, pushTrace, clearTraces` de `useGameStore()` e já tem `activeCampaignId`,
o estado `devtoolsOpen`, o botão com `onClick={() => setDevtoolsOpen(true)}` e o
`<DevtoolsPanel ... traces={traces} onClear={clearTraces} />` no fim do JSX.

- Importe `fetchTraces` e `deleteTraces` do `../api` (o arquivo já importa outras
  funções de lá) e pegue também `setTraces` do store.
- Crie `const loadTraces = async () => { if (!activeCampaignId) return; const list =
  await fetchTraces(activeCampaignId); setTraces(list) }`.
- Chame `loadTraces()` num `useEffect` que depende de `activeCampaignId`, para o
  contador do botão já refletir o histórico salvo assim que a campanha abre.
- Troque o `onClick` do botão de devtools para abrir o painel **e** chamar
  `loadTraces()`, de modo que a lista mostrada seja sempre a do servidor (o que
  também elimina a duplicata entre o turno recém-transmitido e a linha salva).
- Passe para o painel um `onClear` novo: `async () => { await deleteTraces(activeCampaignId);
  clearTraces() }`.

**`frontend/src/components/DevtoolsPanel.jsx`.** O painel recebe `traces` (cada item
com `key`, `label`, `entries`) e renderiza a lista lateral com `t.label` e
`{t.entries.length} calls`.

- Na lista lateral, abaixo do `label`, mostre também a data/hora curta de
  `t.created_at` (quando existir) e o começo de `t.action` truncado (por exemplo, os
  primeiros 40 caracteres com reticências), com o texto completo em `title`. Itens
  sem esses campos continuam renderizando normalmente.
- No cabeçalho, troque o texto `{traces.length} turns captured` por
  `{traces.length} turns saved`.
- Proteja os acessos: `t.entries` pode vir indefinido — use `(t.entries || []).length`
  e, em `turnTotals`/no map dos cards, o mesmo cuidado que já existe hoje.

Rode `cd frontend && npm run build` e deixe passar.

## Fora do escopo

- Qualquer alteração em `backend/` (as rotas vêm prontas do T-001).
- Paginação, busca ou filtro por tipo de chamada dentro do painel.
- Exportar trace para arquivo.
- Persistir traces no `localStorage` — a fonte da verdade agora é o servidor.

## Pronto quando

- [ ] `frontend/src/api.js` exporta `fetchTraces` e `deleteTraces`, ambas devolvendo
      valor neutro em caso de erro em vez de lançar exceção.
- [ ] `frontend/src/store.js` exporta a ação `setTraces` no store, e `pushTrace` gera
      chaves que não colidem com as chaves vindas do servidor.
- [ ] Abrir uma campanha carrega os traces do servidor sem precisar jogar um turno
      (o contador no botão de devtools mostra a quantidade salva).
- [ ] Abrir o painel de devtools recarrega a lista a partir do servidor.
- [ ] A lista lateral mostra, por turno, a data/hora e um trecho da ação do jogador.
- [ ] O botão da lixeira apaga o histórico no servidor: depois de clicar nele e
      reabrir o painel, a lista continua vazia.
- [ ] `cd frontend && npm run build` termina sem erro.

## Como testar (humano)

1. Inicie o jogo e entre numa campanha onde você já jogou pelo menos um turno.
2. Recarregue a página do navegador (F5) e clique no botão de terminal na barra de
   botões. Os turnos antigos têm que aparecer na coluna da esquerda, mesmo sem você
   ter jogado nada depois de recarregar.
3. Confira que cada turno da coluna mostra a data/hora e um pedaço do que você
   escreveu naquele turno. Clique num turno antigo: a entrada e a saída de cada
   chamada aparecem à direita.
4. Feche o painel, escreva uma ação nova, espere terminar e abra o painel de novo:
   o turno novo aparece no topo da coluna.
5. Clique no ícone de lixeira. Feche o painel, recarregue a página e abra o painel:
   tem que estar vazio.
