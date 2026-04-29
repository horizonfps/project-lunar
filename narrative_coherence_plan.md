# Plano de Implementação — Coerência Narrativa do Project Lunar

**Contexto**: análise da campanha `7ce61df1` revelou 3 classes de bugs (retcon de fatos, NPCs com conhecimento ilógico, cautelosismo desproporcional) causados por 5 gaps estruturais no pipeline de contexto.

**Princípios não-negociáveis** (do CLAUDE.md / memória):
- Scenario-agnostic: nada de hardcode One Piece. Toda solução vale pra fantasy/sci-fi/modern.
- NÃO economizar tokens. Alvo é janela 1M. Truncamento blind é proibido — usar budget dinâmico.
- Mudanças incrementais, testáveis camada-por-camada.

**Ordem das camadas é estratégica**: cada camada resolve uma classe de bug e revela quanto sobra antes de partir pra próxima. Não pular pra Camada 3 sem fazer 1 e 2 — você pode descobrir que metade do problema some.

---

## Camada 1 — Parar o Sangramento (sem refatoração)

**Objetivo**: matar truncamento blind, instalar regras de coerência no narrator. Só ajuste de parâmetros + 1 bloco de regras. Esperado eliminar ~40% dos sintomas (esquecimento de fatos antigos, repetição de frases, retcon trivial).

**Esforço estimado**: 2-3h, incluindo replay de teste.

### 1.1 Soltar truncamentos blind

| Arquivo:linha | Estado atual | Mudar para | Motivo |
|---|---|---|---|
| `backend/app/engines/narrator_engine.py:340` | `MAX_HISTORY_MESSAGES = 100` | `MAX_HISTORY_MESSAGES = 600` | Em janela de 1M, 600 msgs (~300 trocas) ainda cabe folgado e elimina repetição de clichês. |
| `backend/app/services/game_session.py:1004` | `for m in minds[:10]:` | `for m in minds:` (todos) | NPCs #11+ ficam invisíveis. Em campanha longa todos os nakamas precisam estar no contexto. |
| `backend/app/services/game_session.py:1005` | `list(m.thoughts.items())[:4]` | `list(m.thoughts.items())` (todos) | NPC mind tem ~4-6 campos. Cap em 4 silenciosamente descarta `secret_plan` ou `opinion_of_player`. |
| `backend/app/services/game_session.py:1015` | `entries[-8:]` | `entries[-40:]` (manter ordem cronológica) | 8 entradas é nada. Journal com 95+ entries (caso real) só envia 8% do que existe. |
| `backend/app/services/game_session.py:1023` | `self._history[-1]["content"][:1000]` | `self._history[-1]["content"]` (sem truncar) | Truncar a narrativa anterior em 1k chars perde detalhes que estão na memória recente do player. |
| `backend/app/services/game_session.py:878, 1160` | `self._history[-1]["content"][:300]` | `self._history[-1]["content"]` (sem truncar) | Mesma violação, em outros pontos. |
| `backend/app/services/game_session.py:654` | `_STORY_CARDS_MAX_BUDGET = 40_000` | `_STORY_CARDS_MAX_BUDGET = 200_000` | Budget de 40k é setup de janela 200k. Em 1M, 200k cabe e ainda sobra metade. |
| `backend/app/services/game_session.py:655` | `_STORY_CARDS_MAX_COUNT = 50` | `_STORY_CARDS_MAX_COUNT = 300` | Hard cap de 50 estoura cenários grandes (one_piece_adventures tem 100+ cards). |

**Riscos**:
- Aumento de tokens por chamada → custo $$. Aceitável: o usuário usa DeepSeek V4 1M (cheap) e quer maximizar uso da janela.
- Latência: history maior = mais tempo pra LLM digerir. Monitorar primeira resposta após mudança.
- Provedores com janela < 1M (caso o user troque): adicionar fallback dinâmico via `_get_context_window()` que já existe no projeto. Verificar se `MAX_HISTORY_MESSAGES` deveria ser propriedade calculada, não constante.

### 1.2 Refatorar `MAX_HISTORY_MESSAGES` pra dinâmico

Constante hardcoded vai dar tiro no pé quando trocar provedor. Substituir por:

```python
# narrator_engine.py
def _max_history_for_window(context_window: int) -> int:
    if context_window >= 1_000_000:
        return 600
    if context_window >= 200_000:
        return 200
    return 100
```

E passar `context_window` no `_select_history()`.

### 1.3 Adicionar regras de coerência no NARRATOR_RULES

**Arquivo**: `backend/app/engines/narrator_engine.py:236` (bloco `NARRATOR_RULES`).

Adicionar regras explícitas (em PT-BR / EN conforme `language`):

```
COHERENCE RULES (CRITICAL):
- NEVER contradict facts established in INVENTORY or in MEMORY tier crystals.
- An item's "source" / origin reason in INVENTORY is canonical. NPCs may interpret or speculate, but cannot rewrite the item's documented purpose.
- If a fact appears in MEMORY tier crystals, treat it as immutable canon. If a player asks about it again, reuse the same explanation.
- An NPC may only reference information they could plausibly know: things they witnessed, things told to them on-screen, or public lore from their region. Never have an NPC mention a player detail (vehicle, item, lineage, route) that the player did not reveal in dialogue or that the NPC did not visibly observe.
- Avoid recycling sensory phrases ("the wind passes", "her brown eyes", "the compass pulses"). If a phrase appeared in the last 20 narrator responses, pick a different one.
- Tone must match TONE_INSTRUCTIONS. Do not inject solemn / mysterious framing for ordinary requests unless the lore explicitly marks the topic as sacred.
```

**Por que esse texto**:
- Linha 1: "INVENTORY/MEMORY são canon" trava o bug da bússola.
- Linha 4: "NPC só fala o que poderia saber" é a tampa provisória pro bug Rin/jangada (Camada 3 vai resolver de fato, mas isso já reduz incidência).
- Linha 5: "frases recicladas" mata repetição.
- Linha 6: "tom mistico só se lore marcar" mata o cautelosismo do cartógrafo.

### 1.4 Validação Camada 1

- Rodar uma campanha nova de teste (~30 ações).
- Verificar:
  - [ ] Frases-clichê de filler ("vento passa", etc) não repetem mais que 2x em 30 turns.
  - [ ] Mencionar um item conhecido faz NPC dar a explicação canônica, não inventar nova.
  - [ ] NPCs novos não citam detalhes que player não revelou.
- Se restar bug de "NPC esquece fato antigo" → Camada 2 atacaria.
- Se restar bug de "NPC sabe coisa que não viu" → Camada 3.
- Se restar "NPC virou robô calculista pra sempre" → Camada 4.

---

## Camada 2 — RAG em Memory Crystals  ✅ IMPLEMENTADA

**Status**: implementada. `MemoryEngine._score_crystal` + `_select_ranked_crystals` + reescrita de `build_context_window[_async]` com parâmetros opcionais (`query_text`, `active_npc_names`, `location`, `context_window`). `game_session._handle_narrative` e `_process_action_single_call` passam o player_input + última narrativa + nomes de NPCs ativos. Feature flag `LUNAR_FEATURE_RAG_CRYSTALS` (default ON). Testes: 5 novos em `tests/engines/test_memory_engine.py` cobrem ranking por keyword, NPC boost, MEMORY tier sempre incluído, fallback com flag OFF e backward-compat sem query.

**Objetivo**: garantir que fatos importantes ("Yuta é filho de Roger") apareçam no contexto **quando relevantes**, em vez de sumir conforme o player faz outras coisas.

**Esforço estimado**: 4-6h.

### 2.1 Diagnóstico

`backend/app/engines/memory_engine.py:457-566` (`build_context_window` / `_async`):
- Atualmente: retorna **TODOS os MEMORY tier** + **últimos 3 unconsumed por LONG/MEDIUM/SHORT** + **últimos 10 raw events**.
- Problema: seleção por tier+recência é cega à ação atual. Se o player faz 12 turns sobre cozinhar peixe, "filho de Roger" vira ruído de fundo enterrado.

### 2.2 Mudança proposta

**Reaproveitar a infra de scoring que já existe pra story cards** (`game_session.py:690-724`, `_score_card_relevance`).

Aplicar scoring nos crystals de tier LONG/MEDIUM/SHORT (NÃO no MEMORY tier — fatos canônicos sempre entram). Score baseado em:
- Match de keywords da ação atual (peso alto).
- Match de NPCs ativos na cena (peso alto).
- Match de localização atual.
- Recência (peso baixo, decay suave).

### 2.3 Files & changes

- `backend/app/engines/memory_engine.py`:
  - Adicionar método `_score_crystal(crystal: MemoryCrystal, query_keywords, active_npcs, location) -> float`.
  - Em `build_context_window_async`:
    - MEMORY tier: continua retornando tudo (canon).
    - LONG/MEDIUM/SHORT: ranquear por score, retornar top-K (K dimensionado pelo budget de tokens, NÃO hardcoded em 3).
- `backend/app/services/game_session.py`:
  - Passar `player_input`, `active_npc_names`, `current_location` pro `build_context_window_async`. Já tem todos esses dados disponíveis no `_handle_narrative`.

### 2.4 Validação Camada 2

- Teste sintético: campanha onde fato A é estabelecido turn 5, depois 30 turns sobre fato B, depois player puxa A no turn 36.
- Esperado: crystal de A aparece no contexto do turn 36 com score alto (porque player_input cita A).
- Antes do fix: crystal de A está enterrado, NPC esquece.

### 2.5 Risco

`_score_card_relevance` foi feito para story cards (estruturados). Crystals têm `content` (resumo livre) + `ai_content` (JSON). Keyword extraction precisa entender ambos. Verificar `_extract_context_keywords` em `game_session.py:670` — possivelmente precisa expansão pra ler o JSON estruturado de `ai_content`.

---

## Camada 3 — Filtragem por Perspectiva (a parada grande)

**Objetivo**: NPCs só sabem o que poderiam saber. Resolve "Rin sabe da jangada", "Rin sabe que execução foi em Loguetown", e outros vazamentos de informação.

**Esforço estimado**: 8-12h. Mexe em modelos de evento + pipeline de NPC mind + scoring de crystals.

### 3.1 Modelo de dados — campo `witnessed_by`

**Adicionar** ao schema de eventos um campo opcional `witnessed_by: List[str]` (nomes de NPCs presentes na cena).

- `backend/app/db/event_store.py` (verificar nome real): adicionar coluna `witnessed_by TEXT` ao schema (JSON list). Migração via `schema_version`.
- `backend/app/engines/memory_engine.py`: `MemoryCrystal` ganha campo `witnessed_by` (herdado dos eventos consolidados — união dos witnesses).
- `backend/app/engines/journal_engine.py`: `JournalEntry` ganha campo `witnessed_by`.

### 3.2 Quem preenche `witnessed_by`?

Duas estratégias, escolher uma (recomendo B):

**A. Heurística por mention**: pós-narrative parsing — qualquer NPC mencionado com `@Nome` no texto do narrador é considerado presente.
- Pros: zero custo extra.
- Contras: NPC pode ser mencionado sem estar fisicamente presente (ex: "Rin pensou em Kai").

**B. LLM call dedicada (recomendado)**: ao processar `NARRATOR_RESPONSE`, fazer mini-call estruturada (existing `llm_router`) pedindo:
> "Quais personagens (além do player) estão fisicamente presentes nesta cena? Responda JSON: `{npcs_present: [nome1, nome2]}`."
- Já existe pipeline parecido pra `npc_mind_engine.update_npc_thoughts` e `journal_engine.evaluate_and_log`. Adicionar mais uma async side-effect.
- Custo: 1 call extra por turn, output minúsculo (~50 tokens). Aceitável.
- Pros: precisão alta, scenario-agnostic.
- Contras: latência async (não bloqueia resposta ao player).

### 3.3 Onde aplicar a filtragem

**Quando montar contexto pra `update_npc_thoughts(npc_name)`** (`npc_mind_engine.py:248-380`):
- Filtrar crystals: só passar crystals onde `npc_name in witnessed_by` OU MEMORY tier (canon mundial).
- Filtrar journal: só entries com `npc_name in witnessed_by`.
- Filtrar story cards: cards já têm `card.content` que pode conter `known_by`. Se existir, filtrar; se não, manter (lore pública).

**Quando montar contexto do narrador** (`game_session.py:_handle_narrative`):
- Aqui é mais delicado: o narrador é onisciente. NÃO filtrar o contexto principal.
- Mas adicionar bloco extra: `NPC KNOWLEDGE BOUNDARIES` — pra cada NPC ativo na cena, listar quais fatos ele realmente sabe. Esse bloco vira input para o narrador "ao escrever fala de NPC X, restrinja-se a estes fatos".

### 3.4 Story cards — campo `known_by`

Já é mencionado nos relatórios como "campo que existe mas nunca é consultado". Verificar:
- `backend/app/db/scenario_store.py` — schema do StoryCard.
- Se existir `card.content["known_by"]: List[str]`, usar no filtro.
- Se não existir, adicionar opcional. Default: card é público (todos sabem).

### 3.5 Files

- `backend/app/db/event_store.py` — schema migration.
- `backend/app/engines/memory_engine.py` — propagar `witnessed_by` em crystals consolidados.
- `backend/app/engines/journal_engine.py` — campo + filtro.
- `backend/app/engines/npc_mind_engine.py` — filtros na `update_npc_thoughts`.
- `backend/app/services/game_session.py` — novo async side-effect `_extract_witnesses`, novo bloco `NPC KNOWLEDGE BOUNDARIES` no contexto.
- `backend/app/db/scenario_store.py` — `known_by` em story cards (opcional, fallback público).

### 3.6 Validação Camada 3

- Teste replay: campanha com player chegando sozinho a uma cidade, encontrando NPC X num beco. NPC X não pode mencionar:
  - Veículo do player (a menos que cena de chegada tenha incluído NPC X).
  - Localização anterior do player.
  - NPCs que player conheceu antes em outra cena.
- Verificar logs: cada turno deve produzir um `WITNESS_EXTRACTED` event com lista correta.
- Edge case: cena com 0 NPCs (player sozinho falando consigo) → `witnessed_by: []`. Crystals desse turn só entram em context "global", não em context filtrado de NPC.

### 3.7 Riscos

- **Schema change**: nova coluna `witnessed_by` na tabela `events`. **Decidido**: campanhas antigas serão descartadas (`rm backend/events.db` antes do deploy). Sem necessidade de migração com fallback `NULL → "todos sabem"`. Schema novo nasce limpo via `schema_version` bump.
- **LLM hallucination no extractor**: se o extractor errar ("X estava presente" mas não estava), filtragem fica errada. Mitigar com temperature baixa + JSON schema strict.
- **Performance**: +1 LLM call por turn. Async, não bloqueante. Mas custos somam. Adicionar feature flag `WITNESS_EXTRACTION_ENABLED` pra desligar em scenarios pequenos.

---

## Camada 4 — Quebrar o Feedback Loop NPC_THOUGHT

**Objetivo**: erros do narrador não viram canon do NPC. NPC mantém personalidade estável.

**Esforço estimado**: 3-5h.

### 4.1 Diagnóstico

`backend/app/engines/npc_mind_engine.py:248-380` — `update_npc_thoughts` recebe `narrative_text` (o texto cru do narrador) e `world_context`. Se narrador escreveu "Rin vigia cada esquina", isso vira `feeling="paranoica"` permanente. Próximo turn: contexto inclui `Rin: feeling=paranoica`. Narrador ancora nisso. Loop.

### 4.2 Mudança proposta — Contexto Factual vs Narrativo

`update_npc_thoughts` deve receber **dois** inputs separados:
1. **Factual context** (imutável): MEMORY tier crystals + INVENTORY + character_setup do NPC (do story card). Isso é a "verdade do mundo".
2. **Narrative context** (mutável): narrative_text recente. Isso é "o que aconteceu nesta cena específica".

E a regra do prompt do extractor de thoughts muda:
> "Atualize as thoughts do NPC com base no que aconteceu na NARRATIVE. Mas a personalidade base e fatos canônicos vêm do FACTUAL CONTEXT — não os reescreva, só ajuste reações."

### 4.3 Personality Anchor no Story Card

Story card de NPC já tem `card.content` com descrição. Adicionar (ou usar) campo `card.content["personality_anchors"]: dict` — traços imutáveis. Ex:
```json
{
  "personality_anchors": {
    "core_trait": "loyal but pragmatic",
    "speech_pattern": "direct, occasional sarcasm",
    "do_not_drift_to": "paranoid stalker"
  }
}
```

Esse bloco entra no FACTUAL CONTEXT do extractor e do narrador, prevenindo drift.

### 4.4 Decay de thoughts emocionais

Thoughts atuais sobrevivem indefinidamente. Adicionar:
- Cada thought tem `created_at` e `decay_after_turns` (ex: `feeling` decai em 5 turns, `goal` em 20, `secret_plan` nunca).
- No `build_context`, thoughts expirados são omitidos (mas `opinion_of_player` agrega: virou history pra próximo update).

Evita "Rin ficou ansiosa no turn 12 → ainda ansiosa no turn 80".

### 4.5 Files

- `backend/app/engines/npc_mind_engine.py`:
  - `NpcThought` dataclass: adicionar `created_at`, `decay_after_turns`.
  - `update_npc_thoughts`: split de input em factual + narrative; injetar personality_anchors do story card.
  - Novo método `_apply_decay(mind, current_turn)`.
- `backend/app/services/game_session.py:1000-1007`: ao montar npc_ctx, chamar `_apply_decay` antes de iterar.
- `backend/app/db/scenario_store.py`: documentar campo `personality_anchors` (opcional). Update do scenario builder pode preencher automaticamente via LLM no `step` do setup wizard.

### 4.6 Validação Camada 4

- Teste: campanha onde NPC X reage emocionalmente a evento (ex: chora). Após 10 turns sem novo gatilho, `feeling` não deve mais ser "triste".
- Teste: criar NPC com `personality_anchors.core_trait: "alegre, otimista"`. Forçar narrador a colocar NPC em situação tensa. Verificar que NPC volta ao baseline depois, não fica permanentemente sombrio.

### 4.7 Risco

- Personality anchors podem ser percebidos como "personagem chato e estático". Balance: anchor dá direção, narrative pode modular tom da cena. Pra isso, anchor é "core_trait" (alma), não "every behavior" (cada gesto).
- Decay de goals: se NPC tinha `goal="encontrar irmão"` e isso decai, fica feio. Solução: distinguir `transient_emotion` (decai) de `persistent_goal` (não decai). Já é a divisão por chave (`feeling/goal/opinion_of_player/secret_plan`), basta tabela de defaults:

| Chave | Decay default |
|---|---|
| `feeling` | 5 turns |
| `mood` | 5 turns |
| `goal` | nunca |
| `opinion_of_player` | nunca (mas pode ser sobrescrito) |
| `secret_plan` | nunca |

---

## Cronograma e Decisão

| Camada | Esforço | Risco | Resolve |
|---|---|---|---|
| 1 — Truncamento + rules | 2-3h | Baixo (parametros) | Esquecimento de history + frases-clichê + retcon trivial |
| 2 — RAG crystals | 4-6h | Médio (scoring quality) | Esquecimento de fatos antigos quando relevantes |
| 3 — Filtro perspectiva | 6-9h | Médio (LLM extractor accuracy) | NPC sabendo coisa que não viu |
| 4 — Feedback loop fix | 3-5h | Médio (personality anchors podem engessar) | NPC virando paranoico/calculista pra sempre |

**Total**: 15-23h.

**Nota sobre dados existentes**: campanhas antigas (`events.db`, `scenarios.db`) serão descartadas antes de cada camada que mexe em schema. Sem suporte a backwards-compat — é projeto pessoal, não tem usuário pagante esperando migração.

**Recomendação de execução**:
1. Camada 1 hoje. Replay de 30 turns. Mede o restante.
2. Decidir: se restar mais bug de "esquecimento de fatos relevantes" → Camada 2. Se restar mais bug de "NPC sabendo demais" → Camada 3. Se restar mais bug de "NPC robotizado" → Camada 4.
3. Não tentar tudo de uma vez. Camada 3 sozinha é uma feature grande, merece branch própria.

**Princípio de testes**: cada camada precisa de pelo menos uma campanha de replay (30+ turns) antes de marcar como done. Métricas qualitativas (frases repetem? NPC esqueceu? NPC sabe demais?) > métricas quantitativas (testes unitários só pegam regression de schema/code, não de qualidade narrativa).

**Feature flags**: cada camada atrás de flag em `.env` (ex: `LUNAR_FEATURE_RAG_CRYSTALS=true`, `LUNAR_FEATURE_PERSPECTIVE_FILTER=true`). Permite toggle se algum fix piorar mais que melhorar.

---

## Apêndice — Arquivos verificados

Todas as referências `arquivo:linha` neste plano foram conferidas em `master @ e6dfa04`:

- `backend/app/engines/narrator_engine.py:340` — `MAX_HISTORY_MESSAGES = 100` ✓
- `backend/app/services/game_session.py:654-655` — `_STORY_CARDS_MAX_BUDGET = 40_000`, `_STORY_CARDS_MAX_COUNT = 50` ✓
- `backend/app/services/game_session.py:1004-1005` — caps de `[:10]` NPCs e `[:4]` thoughts ✓
- `backend/app/services/game_session.py:1015` — `entries[-8:]` ✓
- `backend/app/services/game_session.py:1023, 878, 1160` — `[:1000]` / `[:300]` truncations ✓
- `backend/app/engines/memory_engine.py:457-566` — `build_context_window[_async]` ✓
- `backend/app/engines/npc_mind_engine.py:248-380` — `update_npc_thoughts` (precisa re-verificar antes de editar)
- `backend/app/engines/journal_engine.py` — schema (precisa re-verificar antes de editar)

Antes de implementar cada camada, abrir os arquivos e confirmar que o code não mudou desde esta análise (a base é live).
