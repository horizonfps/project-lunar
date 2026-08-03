---
id: T-005
title: Passar reasoning=False em todas as chamadas mecânicas de LLM do jogo
status: ready
blockedBy: [T-004]
files: [backend/app/engines/narrator_engine.py, backend/app/engines/combat_engine.py, backend/app/engines/journal_engine.py, backend/app/engines/npc_mind_engine.py, backend/app/engines/plot_generator.py, backend/app/engines/memory_engine.py, backend/app/services/game_session.py, backend/app/services/scenario_service.py, backend/tests/engines/test_journal_engine.py, backend/tests/engines/test_combat_engine.py]
---

## O que fazer

O modelo padrão da campanha (`deepseek-v4-flash`) é um modelo que "pensa antes de
responder", e esse pensamento consome o mesmo orçamento de tokens da resposta.
As chamadas mecânicas do jogo (classificar a ação, marcar o nível de poder,
extrair nomes, decidir se o turno vira entrada de diário, extrair entidades)
pedem JSON curto com um teto baixo de tokens — o modelo gasta tudo pensando e
devolve nada. Resultado medido num turno real: 5 chamadas de 9 voltaram vazias,
e cada uma delas caiu num fallback silencioso.

Este ticket desliga o modo de raciocínio exatamente nessas chamadas mecânicas,
usando a chave `reasoning=False` entregue pelo T-004. Efeito visível: o nível de
poder do personagem volta a ser atualizado, o diário volta a registrar
acontecimentos, os personagens e lugares voltam a entrar no mapa de relações, e
o turno fica mais rápido.

## Onde mexer

Em cada chamada listada abaixo, acrescente `reasoning=False` aos argumentos de
`complete(...)`. As linhas são as do estado atual do repositório; confira o
contexto ao redor antes de editar.

- `backend/app/engines/narrator_engine.py:68` — `detect_mode`, classifica a ação em NARRATIVE/COMBAT/META.
- `backend/app/engines/combat_engine.py:52` — checagem anti-griefing (JSON de 3 campos).
- `backend/app/engines/combat_engine.py:98` — `evaluate_action`, nota de 0-10 em 3 eixos.
- `backend/app/engines/journal_engine.py:69` — `evaluate_and_log`, decide se o turno vira entrada de diário.
- `backend/app/engines/npc_mind_engine.py:210` — comparação de nomes, responde só YES/NO com teto de 16 tokens.
- `backend/app/engines/plot_generator.py:162`, `:230`, `:280`, `:332` — geração de NPC/evento/plot em JSON.
- `backend/app/engines/memory_engine.py:523` — dentro de `_compress_with_llm`, a compressão de memória em JSON (é o único ponto: as chamadas das linhas 282 e 349 passam por aqui).
- `backend/app/services/game_session.py:611` — `_ensure_player_power`.
- `backend/app/services/game_session.py:697` — `_evaluate_power_update`.
- `backend/app/services/game_session.py:2031` — `_extract_witnesses`.
- `backend/app/services/game_session.py:2780` — `_extract_entities_to_graph`.
- `backend/app/services/scenario_service.py:53` — extração de entidades do lore do cenário.

Exemplo da edição, em `journal_engine.py`:

```python
raw = await self._llm.complete(messages=messages, max_tokens=256, reasoning=False)
```

ARMADILHA CONHECIDA: vários testes usam dublês de LLM com assinatura fixa, do
tipo `async def complete(self, messages, max_tokens=None)`. Passar a chave nova
quebra esses dublês com `TypeError`. Ajuste cada dublê afetado para aceitar
`**kwargs` (é o que o dublê de `backend/tests/engines/test_auditor_engine.py` já
faz: `async def complete(self, messages, max_tokens=None, **kwargs)`). Rode a
suíte inteira e corrija todos os que quebrarem, mesmo que estejam em arquivos de
teste não listados no cabeçalho deste ticket.

Acrescente pelo menos um teste novo que prove o comportamento: em
`backend/tests/engines/test_journal_engine.py`, um dublê que grava os kwargs
recebidos e uma asserção de que `evaluate_and_log` chamou `complete` com
`reasoning=False`. Faça o equivalente em
`backend/tests/engines/test_combat_engine.py` para a checagem anti-griefing.

Rode: `cd backend && venv/Scripts/python.exe -m pytest tests -q`.

## Fora do escopo

- A narração em si (`stream_narrative`, `stream_narrative_cached`, `complete_single_call` em `narrator_engine.py`) — o narrador precisa raciocinar e já tem folga de orçamento.
- `backend/app/engines/opening_generator.py` (abertura da campanha, texto criativo).
- `backend/app/engines/world_reactor.py:93` (gera prosa de mudança do mundo).
- `backend/app/engines/npc_mind_engine.py:504` (pensamentos dos NPCs; tem teto de 4096 e foi medido funcionando).
- `backend/app/engines/auditor_engine.py` — o auditor PRECISA raciocinar; é o T-006.
- Mexer no roteador de LLM: a chave `reasoning` já vem pronta do T-004.

## Pronto quando

- [ ] Todas as 14 chamadas listadas acima passam `reasoning=False`.
- [ ] Nenhuma chamada do narrador, do auditor, do gerador de abertura, do reator de mundo ou dos pensamentos de NPC passa `reasoning=False`.
- [ ] Existe teste automatizado que falha se `evaluate_and_log` parar de passar `reasoning=False`.
- [ ] Existe teste automatizado que falha se a checagem anti-griefing parar de passar `reasoning=False`.
- [ ] `cd backend && venv/Scripts/python.exe -m pytest tests -q` passa.

## Como testar (humano)

1. Abra o jogo e entre numa campanha que já tenha história (por exemplo, a de teste de Valencrest).
2. Jogue um turno que claramente aconteça alguma coisa: converse com alguém novo ou entre num lugar novo.
3. Espere a narração terminar.
4. Abra o diário da campanha: o acontecimento do turno tem de estar registrado lá. Antes ficava sem registro nenhum.
5. Abra a ficha do personagem: o nível de poder tem de estar preenchido e coerente, não zerado.
6. O turno deve terminar visivelmente mais rápido do que antes.
