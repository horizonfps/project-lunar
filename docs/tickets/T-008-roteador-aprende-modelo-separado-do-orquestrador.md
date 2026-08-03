---
id: T-008
title: Adiciona modelo separado para o orquestrador e cadastra Claude Opus 5 / Sonnet 5 no roteador
status: ready
blockedBy: []
files: [backend/app/engines/llm_router.py, backend/tests/engines/test_llm_router.py]
---

## O que fazer

Hoje o jogo usa um único modelo de IA para tudo: a narração principal e todas as
tarefas de bastidor (auditoria do texto, memória, diário, combate, NPCs, geração
de abertura). Esta tarefa cria a possibilidade de usar **dois modelos ao mesmo
tempo**: um modelo mais caro e mais capaz para a chamada que escreve a narrativa
(o "orquestrador") e outro mais barato para todo o resto.

Nada muda na tela ainda: enquanto o segundo modelo não for configurado, o
comportamento é exatamente o de hoje. Esta tarefa entrega só a peça do roteador,
mais o cadastro dos dois modelos novos da Anthropic (Claude Opus 5 e Claude
Sonnet 5) para que o sistema saiba a janela de contexto deles e não envie
parâmetros que eles rejeitam.

## Onde mexer

`backend/app/engines/llm_router.py`:

1. **`LLMConfig`** (linha ~510): adicionar o campo
   `orchestrator_model: str | None = None`, logo abaixo de `primary_model`.
   Quando `None`, tudo continua usando `primary_model` — é esse o default que
   garante zero mudança de comportamento.

2. **`LLMConfig.get_context_window()`**: hoje monta a chave a partir de
   `self.primary_model`. Passar a usar `self.orchestrator_model or self.primary_model`,
   porque quem consome esse valor é o orçamento de histórico da narrativa
   (`game_session.py` chama `config.get_context_window()`), que roda no modelo do
   orquestrador.

3. **Novo método em `LLMRouter`**, ao lado de `_build_model_string`:

   ```python
   def _active_model(self, orchestrator: bool) -> str:
       """Orchestrator calls use the dedicated model when one is configured."""
       if orchestrator and self.config.orchestrator_model:
           return self.config.orchestrator_model
       return self.config.primary_model
   ```

4. **`LLMRouter.complete()`** (linha ~645) e **`LLMRouter.stream()`** (linha ~710):
   ambas começam com `caller = _get_caller()` seguido de
   `model = self._build_model_string(self.config.primary_provider, self.config.primary_model)`.
   Em cada uma, antes de montar `model`, extrair o novo argumento:

   ```python
   orchestrator = kwargs.pop("orchestrator", False)
   model = self._build_model_string(
       self.config.primary_provider, self._active_model(orchestrator)
   )
   ```

   O `pop` tem que acontecer **antes** de `call_kwargs = {**kwargs}`, senão
   `orchestrator=True` vaza como parâmetro para o `litellm.acompletion` e a
   chamada quebra com erro de argumento desconhecido. Repare que
   `max_tokens` e `reasoning` já usam exatamente esse padrão de `kwargs.pop`
   logo acima — seguir o mesmo estilo.

   O caminho de fallback dentro de `complete()` (que usa
   `self.config.fallback_provider` / `fallback_model`) fica como está.

5. **`_CONTEXT_WINDOWS`** (linha ~336): adicionar, no bloco da Anthropic, acima
   das entradas 4.6 já existentes:

   ```python
   # Anthropic — Claude 5 (1M context)
   "anthropic/claude-opus-5": 1_000_000,
   "anthropic/claude-sonnet-5": 1_000_000,
   ```

   Não remover nenhuma entrada existente: campanhas antigas ainda podem estar
   configuradas com um modelo 4.x.

6. **`_NO_SAMPLING_MODELS`** (linha ~380): a tupla já lista `"claude-sonnet-5"`.
   Falta `"claude-opus-5"` — adicionar. Esses modelos devolvem erro 400 se
   receberem `temperature`, e `_accepts_temperature` usa `startswith` sobre essa
   tupla para decidir se manda o parâmetro.

`backend/tests/engines/test_llm_router.py` — acrescentar testes no estilo dos que
já existem no arquivo (fixtures `config`/`router`, `patch` em
`app.engines.llm_router.litellm.acompletion` com `AsyncMock`):

- Sem `orchestrator_model` configurado, `complete(..., orchestrator=True)` chama
  o `litellm.acompletion` com o mesmo `model` de uma chamada normal.
- Com `orchestrator_model="claude-opus-5"` e `primary_model="claude-sonnet-5"` em
  provider `anthropic`, `complete(..., orchestrator=True)` usa
  `anthropic/claude-opus-5` e `complete(...)` sem o argumento usa
  `anthropic/claude-sonnet-5`.
- `orchestrator` nunca aparece entre os kwargs passados ao `litellm.acompletion`.
- `LLMConfig(primary_provider=ANTHROPIC, primary_model="claude-sonnet-5").get_context_window() == 1_000_000`
  e o mesmo com `orchestrator_model="claude-opus-5"`.
- `_accepts_temperature("anthropic/claude-opus-5")` é `False`.

## Fora do escopo

- Marcar qualquer chamada existente como sendo do orquestrador — nenhum arquivo
  de engine ou de serviço é tocado aqui. Isso é a T-009.
- Decidir qual modelo o usuário recebe por padrão, ou mexer nas rotas da API.
  Isso é a T-010.
- Mexer no proxy (`proxy/config.py`) ou no frontend.
- Remover ou depreciar modelos 4.x do catálogo.

## Pronto quando

- [ ] `LLMConfig` tem o campo `orchestrator_model` com default `None`.
- [ ] `complete()` e `stream()` aceitam o argumento nomeado `orchestrator` e não
      o repassam para `litellm.acompletion`.
- [ ] Com `orchestrator_model` preenchido, uma chamada com `orchestrator=True`
      usa esse modelo; sem o argumento, usa `primary_model`.
- [ ] Com `orchestrator_model=None`, chamadas com e sem `orchestrator=True` usam
      o mesmo modelo.
- [ ] `_CONTEXT_WINDOWS` contém `anthropic/claude-opus-5` e
      `anthropic/claude-sonnet-5`, ambos com 1.000.000.
- [ ] `_NO_SAMPLING_MODELS` contém `claude-opus-5`.
- [ ] `cd backend && python -m pytest tests/engines/test_llm_router.py` passa,
      incluindo os testes novos.

## Como testar (humano)

1. Abra o terminal na pasta do projeto e entre na pasta `backend`.
2. Rode a suíte de testes do roteador de IA com o comando
   `python -m pytest tests/engines/test_llm_router.py`.
3. Todos os testes têm que passar, sem nenhuma falha.
4. Abra o jogo normalmente e jogue um turno. A narrativa tem que aparecer
   exatamente como antes — esta etapa é só preparação interna e não deve mudar
   nada visível.
