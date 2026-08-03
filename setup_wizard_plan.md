# First-Play Setup Wizard — Plano de Implementação

> Feature inspirada no character creation do AI Dungeon. Quando o jogador inicia
> uma campanha pela primeira vez num cenário que define `setup_questions`, ele
> passa por um wizard step-by-step. As respostas viram um "Character Setup"
> permanente injetado no system prompt do LLM.

## 1. Modelo de dados

### Scenario (novo campo)
```
setup_questions: list[Question]
```
```
Question = {
  id: str,                          # uuid, estável p/ reorder
  var_name: str,                    # ex: "race" — usado em interpolação {race}
  prompt: str,                      # suporta "{var_name}" — ex: "{name}, what's your race?"
  type: "text" | "choice",
  options: list[Option],            # só para choice
  allow_custom: bool,               # só para choice
  required: bool
}
Option = { label: str, description: str }
```

### Campaign (novo campo)
```
setup_answers: dict[var_name -> Answer]
Answer = {
  var_name: str,
  resolved_prompt: str,             # prompt já com interpolação aplicada
  type: "text" | "choice",
  value: str,                       # texto livre, label, ou custom
  description: str                  # description da option escolhida (vai pro LLM)
}
```

## 2. Backend

### 2.1 Migração v2 — `backend/app/db/scenario_store.py`
- Bump `SCHEMA_VERSION = 2`
- Novo bloco em `_MIGRATIONS[2]`:
  - `ALTER TABLE scenarios ADD COLUMN setup_questions TEXT NOT NULL DEFAULT '[]'`
  - `ALTER TABLE campaigns ADD COLUMN setup_answers TEXT NOT NULL DEFAULT '{}'`
- Atualizar dataclasses `Scenario` e `Campaign` com os campos novos
- Atualizar `create_scenario`, `get_scenario`, `list_scenarios`, `create_campaign`,
  `get_campaigns` pra serializar/deserializar JSON
- Novo método `update_setup_answers(campaign_id, answers: dict)`

### 2.2 Routes — `backend/app/api/routes_scenarios.py`
- `CreateScenarioRequest` ganha `setup_questions: list[Question] = []` (Pydantic model novo)
- `ImportScenarioRequest` mesma coisa
- `export_scenario` inclui `setup_questions` no payload e `setup_answers` por campaign

### 2.3 Routes — `backend/app/api/routes_game.py`
- `POST /game/{campaign_id}/setup-answers` — recebe `{answers: {var_name: Answer}}` e
  chama `update_setup_answers`
- `GET /game/{campaign_id}/setup-state` — retorna `{questions, answers, needs_setup: bool}`,
  usado pelo frontend pra decidir se renderiza o wizard

### 2.4 Injeção no prompt — `backend/app/engines/npc_mind_engine.py` ou `services/stream_narrative.py`
- Localizar onde `tone_instructions` é injetado no system prompt
- Antes do `tone_instructions`, prepender bloco:
  ```
  CHARACTER SETUP (locked from session start):
  - {var_name}: {value}
    {description}     ← se existir
  ...
  ```
- Buscar `setup_answers` da campaign no início de `stream_action`

## 3. Frontend — Builder

### 3.1 `frontend/src/components/ScenarioBuilder.jsx` (estende)
Nova seção "First-Play Setup" depois de Story Cards. Mesma estética (bordered cards,
dark, monocromática).

**Por question:**
- Header: select de tipo (Text / Choice) + input de var_name (validação: só `[a-z_]+`,
  único no scenario) + checkbox Required + botão Purge
- Textarea do prompt — com tooltip `?` explicando interpolação `{var_name}` mostrando exemplo
- Se `type === "choice"`:
  - Lista de options: input label + textarea description (pequeno)
  - Botão "+ Add Option"
  - Checkbox "Allow custom answer"

**Footer da seção:** botão "+ Add Question"

**Import payload:** se JSON tem `setup_questions`, popular o estado (similar ao já feito p/ story_cards)

**Submit:** se houver questions OR cards OR importPayload, usa `/scenarios/import` (já fazemos)

### 3.2 `frontend/src/api.js`
- `saveSetupAnswers(campaignId, answers)` → POST `/game/:id/setup-answers`
- `fetchSetupState(campaignId)` → GET `/game/:id/setup-state`

## 4. Frontend — Player Wizard

### 4.1 Novo `frontend/src/components/SetupWizard.jsx`
Props: `{ scenario, campaignId, onComplete }`

- Estado: `currentStep` (0..N-1), `answers` (dict acumulando)
- Header: nome do cenário à esquerda, "Step X of Y" à direita (estética igual AI Dungeon, monocromática)
- Render por tipo:
  - `text`: textarea grande centralizada + botão Next
  - `choice`: cards verticais com radio à direita; label como heading, description como
    corpo (truncado com "Show more" se > X chars)
  - `choice + allow_custom`: card extra com input de texto livre
- Interpolação: ao renderizar `prompt`, substituir `{var_name}` pelos valores em `answers`.
  Var não respondida ainda → mantém literal (mas ordem natural impede isso).
- Navegação: Back / Next; último step → "Start" (com ícone play)
- On Start: chama `saveSetupAnswers`, depois `onComplete()`

### 4.2 `frontend/src/App.jsx` — gate de entrada
- Ao abrir campaign: chamar `fetchSetupState`
- Se `needs_setup === true`: renderizar `<SetupWizard>` no lugar do `<GameCanvas>`
- Após `onComplete`: renderizar `<GameCanvas>` normalmente
- Cenários sem `setup_questions` → `needs_setup === false` → fluxo atual inalterado

## 5. Arquivos modificados/criados

**Modificados:**
- `backend/app/db/scenario_store.py`
- `backend/app/api/routes_scenarios.py`
- `backend/app/api/routes_game.py`
- `backend/app/engines/npc_mind_engine.py` (ou onde o system prompt é montado — checar antes)
- `frontend/src/api.js`
- `frontend/src/components/ScenarioBuilder.jsx`
- `frontend/src/App.jsx`

**Criados:**
- `frontend/src/components/SetupWizard.jsx`

## 6. Ordem de execução

1. **Backend foundation** — migração v2 + dataclasses + serialização. Validar via SQLite direto.
2. **Backend routes** — Create/Import com `setup_questions`, save/get setup_answers. Validar via curl.
3. **Builder UI** — seção "First-Play Setup" no ScenarioBuilder. Criar cenário de teste com
   2-3 questions, exportar, ver JSON.
4. **Wizard player** — `SetupWizard.jsx` + integração no `App.jsx`. Criar campanha, passar
   pelo wizard, salvar.
5. **Prompt injection** — adicionar bloco "CHARACTER SETUP" no system prompt. Criar campanha,
   jogar primeira ação, verificar logs do LLM/output.
6. **Polish** — preview de interpolação no builder, validação de var_name, drag-to-reorder (opcional).

## 7. Edge cases já mapeados

- **Cenários antigos** (sem setup_questions) → migração default `[]`, `needs_setup === false`, fluxo intacto
- **Campanhas antigas** (sem setup_answers) → migração default `{}`, mas `needs_setup` retorna `false`
  se scenario não tem questions
- **Var_name duplicado** → validação no builder (frontend) e Pydantic (backend)
- **Interpolação fora de ordem** → `{var}` literal preservado; ordem natural das questions evita o caso
- **Custom answer** → `value` = texto do usuário, `description` = ""
- **Tokens** — bloco CHARACTER SETUP é incluso integralmente no system prompt
  (CLAUDE.md: não economizar tokens, alvo é 1M context)
- **Cenário-agnóstico** — nada hardcoded; tudo derivado das questions definidas pelo criador

## 8. Referência de comportamento (AI Dungeon)

Observado durante research session:
- 14 perguntas por cenário (varia)
- Tipos vistos: text livre (nome), choice radio (gender + Custom), choice com cards
  (race/class/location com label + descrição)
- Interpolação: `Selene, what is your gender?` (usa nome anterior)
- Step counter "Step X of Y" no canto superior direito
- Botão final muda de "Next" pra "Start" no último step
- Primeira mensagem gerada usa TODAS as escolhas em prosa narrativa, com character
  card sublinhado como "memória permanente". As descrições das options escolhidas
  enriquecem o contexto do LLM.

Exemplo gerado pelo AI Dungeon (referência de qualidade alvo):
> "You are Selene, a three-eyed pirate of the Davy Family and member of the
> Straw Hat Grand Fleet. Your bounty of 80 million berries reflects your
> reputation as a cunning and formidable warrior, having mastered the
> Dog-Dog Fruit, Model: Nine Tailed Fox, and honed your skills in
> Observation Haki. Your large, predatory eyes scan the horizon from
> Karakuri Island, where you've made your temporary base of operations."
