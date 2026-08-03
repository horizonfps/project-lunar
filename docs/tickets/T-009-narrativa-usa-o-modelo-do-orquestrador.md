---
id: T-009
title: Marca as três chamadas de narrativa como chamadas do orquestrador
status: ready
blockedBy: [T-008]
files: [backend/app/engines/narrator_engine.py, backend/tests/engines/test_narrator_engine.py]
---

## O que fazer

Define quais chamadas de IA são "o orquestrador": as três que produzem a prosa
que o jogador lê. Todo o resto (detecção de modo, auditoria, memória, diário,
combate, NPCs, enredo, abertura) continua sendo tratado como tarefa de bastidor.

Depois desta tarefa, quando existir um modelo dedicado ao orquestrador
configurado, só a narração passa a usá-lo; as demais chamadas seguem no modelo
padrão. Enquanto ninguém configurar o modelo dedicado, nada muda na tela.

## Onde mexer

`backend/app/engines/narrator_engine.py`. São exatamente três pontos, e nenhum
outro no arquivo:

1. `stream_narrative` (método em ~linha 458): a linha
   `async for chunk in self._llm.stream(messages=messages):` (~linha 494) vira
   `async for chunk in self._llm.stream(messages=messages, orchestrator=True):`.

2. `stream_narrative_cached` (método em ~linha 509): a linha
   `async for chunk in self._llm.stream(messages=messages):` (~linha 553) recebe
   o mesmo `orchestrator=True`.

3. `complete_single_call` (método em ~linha 591): a linha
   `raw = await self._llm.complete(messages=messages, max_tokens=api_max_tokens)`
   (~linha 671) vira
   `raw = await self._llm.complete(messages=messages, max_tokens=api_max_tokens, orchestrator=True)`.

**Não** marcar a chamada de `detect_mode` (~linha 68,
`self._llm.complete(messages=messages, max_tokens=256, reasoning=False)`): é uma
classificação mecânica curta e pertence ao modelo barato.

O argumento `orchestrator` é o que a T-008 adiciona em
`LLMRouter.complete()` / `LLMRouter.stream()`; ele é consumido dentro do
roteador e nunca chega ao provedor.

`backend/tests/engines/test_narrator_engine.py` — o arquivo já usa a fixture
`mock_llm` (um `AsyncMock`) e a fixture `engine`. Acrescentar:

- Um teste que chama `engine.complete_single_call(...)` com
  `mock_llm.complete` devolvendo um JSON válido com `narrative_text`, e verifica
  que `mock_llm.complete.call_args.kwargs.get("orchestrator") is True`.
- Um teste que chama `engine.detect_mode("...")` e verifica que
  `mock_llm.complete.call_args.kwargs.get("orchestrator")` é ausente ou falso.

Para os dois métodos de streaming, se montar o mock de um gerador assíncrono
ficar trabalhoso, basta cobrir `complete_single_call` e `detect_mode` nos testes
— mas as três alterações de código continuam obrigatórias.

## Fora do escopo

- Mexer em `auditor_engine.py`, `memory_engine.py`, `journal_engine.py`,
  `combat_engine.py`, `plot_generator.py`, `npc_mind_engine.py`,
  `world_reactor.py`, `opening_generator.py` ou `game_session.py`: essas chamadas
  são, por definição, as "outras partes" e ficam no modelo padrão.
- Definir qual modelo o orquestrador vai receber (isso é a T-010).
- Alterar `LLMRouter` (isso é a T-008).

## Pronto quando

- [ ] As três chamadas de narrativa (`stream_narrative`,
      `stream_narrative_cached`, `complete_single_call`) passam
      `orchestrator=True`.
- [ ] `detect_mode` continua sem `orchestrator`.
- [ ] Nenhuma outra engine do backend foi alterada.
- [ ] `cd backend && python -m pytest tests/engines/test_narrator_engine.py` passa.
- [ ] `cd backend && python -m pytest` passa inteiro.

## Como testar (humano)

1. No terminal, entre na pasta `backend` do projeto.
2. Rode `python -m pytest` e confirme que a suíte inteira passa.
3. Abra o jogo, entre numa campanha e jogue um turno.
4. A narrativa tem que ser escrita normalmente, do mesmo jeito de antes.
