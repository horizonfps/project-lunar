---
id: T-011
title: Cadastra Claude Opus 5 e Sonnet 5 no proxy da assinatura Claude Max
status: ready
blockedBy: []
files: [proxy/config.py]
---

## O que fazer

O jogo pode falar com a Anthropic através de um proxy local que usa a assinatura
Claude Pro/Max em vez da cobrança por API. Esse proxy tem uma lista fixa de
modelos conhecidos e um modelo padrão, e hoje ela para no Claude 4.6. Como o jogo
vai passar a pedir Claude Opus 5 e Claude Sonnet 5, o proxy precisa conhecê-los.

Depois desta tarefa, jogar com a Anthropic através do proxy funciona com os
modelos novos, e o modelo padrão do proxy passa a ser o Sonnet 5.

## Onde mexer

`proxy/config.py`:

1. `DEFAULT_MODEL` (linha ~31) é hoje `"claude-sonnet-4-6"`. Trocar para
   `"claude-sonnet-5"`.

2. O dicionário `MODELS` (linha ~34) mapeia cada modelo para
   `{"context": ..., "max_output": ...}`. Acrescentar, no topo do dicionário,
   um bloco novo antes das entradas 4.6:

   ```python
   # Claude 5 (1M context)
   "claude-sonnet-5": {"context": 1_000_000, "max_output": 64_000},
   "claude-opus-5": {"context": 1_000_000, "max_output": 64_000},
   ```

   Manter todas as entradas atuais (4.6, 4.5, 4.0/4.1) — campanhas antigas podem
   estar configuradas com elas. Ajustar também o comentário de bloco da linha
   acima do dicionário (hoje `# Available models (Claude 4.6 + older)`) para
   refletir que a lista agora inclui a geração 5.

Não mexer em `proxy/server.py`, `proxy/auth.py` nem em `ANTHROPIC_BETA`: esta
tarefa é só o cadastro de modelos.

## Fora do escopo

- Remover modelos antigos do dicionário.
- Alterar o backend do jogo ou o painel de configurações.
- Alterar cabeçalhos beta, escopos OAuth ou timeout do proxy.

## Pronto quando

- [ ] `DEFAULT_MODEL` em `proxy/config.py` é `"claude-sonnet-5"`.
- [ ] `MODELS` contém as chaves `"claude-opus-5"` e `"claude-sonnet-5"`, ambas
      com contexto de 1.000.000.
- [ ] Nenhuma chave existente foi removida do dicionário.
- [ ] `python -c "import config; assert config.DEFAULT_MODEL in config.MODELS"`
      rodado dentro da pasta `proxy` não gera erro.

## Como testar (humano)

1. No terminal, entre na pasta `proxy` do projeto.
2. Rode o comando
   `python -c "import config; print(config.DEFAULT_MODEL); print(sorted(config.MODELS))"`.
3. A primeira linha impressa tem que ser `claude-sonnet-5`, e a lista impressa
   tem que conter tanto `claude-opus-5` quanto `claude-sonnet-5`.
