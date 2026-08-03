---
id: T-010
title: Faz a API mandar Opus 5 para a narrativa e Sonnet 5 para as demais tarefas
status: ready
blockedBy: [T-008]
files: [backend/app/api/routes_game.py, backend/app/main.py, backend/tests/api/test_routes_game_features.py]
---

## O que fazer

Liga de fato a divisão de modelos. Quando o jogador escolher a Anthropic nas
configurações, a narrativa passa a ser escrita pelo modelo que ele selecionou
(que passará a ser o Claude Opus 5) e todas as tarefas de bastidor — auditoria do
texto, memória, diário, combate, NPCs, enredo, abertura — passam a rodar no
Claude Sonnet 5, que é mais barato e mais rápido.

Quando o jogador escolher a DeepSeek, tudo — narrativa e bastidor — roda no
`deepseek-v4-flash`, que já é o padrão do projeto.

## Onde mexer

`backend/app/api/routes_game.py`:

1. Criar, perto do topo do arquivo (logo depois de
   `_llm = LLMRouter(LLMConfig())`, ~linha 45), uma função e uma tabela de
   política:

   ```python
   # Secondary calls (audit, memory, journal, combat, NPCs, plot, opening) run on a
   # cheaper model than the narrative call.
   _AUXILIARY_MODELS = {
       LLMProvider.ANTHROPIC: "claude-sonnet-5",
       LLMProvider.DEEPSEEK: "deepseek-v4-flash",
   }


   def apply_model_policy(provider: LLMProvider, model: str) -> None:
       """Narrative runs on `model`; everything else on the provider's auxiliary model."""
       _llm.config.primary_provider = provider
       _llm.config.primary_model = _AUXILIARY_MODELS.get(provider, model)
       _llm.config.orchestrator_model = model
   ```

   `orchestrator_model` é o campo que a T-008 adiciona em `LLMConfig`;
   `primary_model` continua sendo o modelo usado por todas as chamadas que não
   passam `orchestrator=True`. Para a OpenAI, que não está na tabela, os dois
   ficam iguais ao modelo escolhido — comportamento idêntico ao de hoje.

2. Em `player_action` (~linha 320), substituir o bloco atual

   ```python
   try:
       _llm.config.primary_provider = LLMProvider(req.provider)
   except ValueError:
       pass
   _llm.config.primary_model = req.model
   ```

   por uma resolução do provider com o mesmo `try/except ValueError` (mantendo o
   provider anterior quando o valor for inválido) seguida de
   `apply_model_policy(provider, req.model)`. As linhas de `temperature` e
   `max_tokens` logo abaixo ficam como estão.

3. Trocar os defaults de `PlayerActionRequest` e `SettingsRequest` (~linhas
   251–261): eles já são `provider="deepseek"` e `model="deepseek-v4-flash"` —
   confirmar e deixar como está.

4. Em `_maybe_generate_ai_opening` (~linha 453) existe um
   `router_ = LLMRouter(LLMConfig())` criado do zero, que hoje sempre nasce em
   DeepSeek. Isso está correto para esta tarefa (abertura é bastidor) e não deve
   ser alterado.

`backend/app/main.py`:

5. O endpoint `POST /api/settings` (~linha 62) recria `_llm.config` do zero com
   `LLMConfig(...)`. Trocar para: resolver o provider como já faz (com fallback
   para `LLMProvider.DEEPSEEK` em valor inválido), atribuir
   `_llm.config.temperature = req.temperature` e
   `_llm.config.max_tokens = req.max_tokens`, e então chamar
   `apply_model_policy(provider, req.model)` importado de
   `app.api.routes_game` — o arquivo já importa `_llm` dessa mesma origem
   (`from app.api.routes_game import router as game_router, _llm`), então basta
   estender esse import.

   O retorno do endpoint continua `{"status": "ok", "provider": ..., "model": req.model}`.

6. O endpoint `GET /api/settings` (~linha 77) devolve `_llm.config.primary_model`
   como `"model"`. Trocar para `_llm.config.orchestrator_model or _llm.config.primary_model`,
   para que o valor lido de volta seja o mesmo que foi enviado. Acrescentar
   também a chave `"auxiliary_model": _llm.config.primary_model` na resposta.

`backend/tests/api/test_routes_game_features.py` — o arquivo já testa
`POST /api/settings` e `GET /api/settings` (fixture `client`). Acrescentar:

- `POST /api/settings` com `provider="anthropic"`, `model="claude-opus-5"`
  devolve 200; o `GET /api/settings` seguinte devolve
  `model == "claude-opus-5"` e `auxiliary_model == "claude-sonnet-5"`.
- `POST /api/settings` com `provider="deepseek"`, `model="deepseek-v4-flash"`
  resulta em `model` e `auxiliary_model` ambos `"deepseek-v4-flash"`.
- O teste existente `test_update_settings_invalid_provider_falls_back` continua
  passando.

Armadilha: os testes desse arquivo compartilham o `_llm` global do módulo, então
a ordem importa. Se um teste novo deixar o roteador em Anthropic e quebrar outro,
restaurar o estado ao final do teste chamando
`POST /api/settings` com `provider="deepseek"` e `model="deepseek-v4-flash"`.

## Fora do escopo

- Mexer em `llm_router.py` (a T-008 já entrega o campo `orchestrator_model`).
- Mexer em qualquer engine (`narrator_engine.py` e companhia).
- Mudar a lista de modelos que aparece no painel de configurações do jogo
  (isso é a T-012).
- Persistir a escolha de modelo por campanha no banco.

## Pronto quando

- [ ] Existe uma função em `routes_game.py` que aplica provider, modelo do
      orquestrador e modelo auxiliar de uma vez só.
- [ ] Com provider `anthropic`, o modelo auxiliar resultante é
      `claude-sonnet-5`, seja qual for o modelo escolhido.
- [ ] Com provider `deepseek`, o modelo auxiliar resultante é
      `deepseek-v4-flash`.
- [ ] `POST /api/game/action` e `POST /api/settings` usam essa mesma função.
- [ ] `GET /api/settings` devolve as chaves `model` e `auxiliary_model`.
- [ ] `cd backend && python -m pytest tests/api` passa.
- [ ] `cd backend && python -m pytest` passa inteiro.

## Como testar (humano)

1. Inicie o jogo normalmente (backend e frontend).
2. Abra as configurações e escolha o provedor DeepSeek. Salve.
3. Jogue um turno: a narrativa tem que aparecer normalmente.
4. No terminal, entre na pasta `backend` e rode `python -m pytest`. Tudo tem que
   passar.
