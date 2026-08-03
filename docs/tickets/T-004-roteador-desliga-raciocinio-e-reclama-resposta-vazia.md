---
id: T-004
title: Adicionar chave "reasoning" por chamada no roteador de LLM e alarme de resposta vazia
status: ready
blockedBy: []
files: [backend/app/engines/llm_router.py, backend/tests/engines/test_llm_router.py]
---

## O que fazer

Hoje, quando o jogo usa o provedor DeepSeek, o modelo `deepseek-v4-flash` gasta o
orçamento de saída pensando em voz alta (campo `reasoning_content`) e devolve a
resposta de verdade VAZIA. Em um turno real medido, 5 de 9 chamadas do turno
voltaram vazias — e o jogo engoliu isso em silêncio, caindo em fallbacks
(poder do personagem não atualiza, diário não registra, entidades não entram no
grafo, auditor nunca audita).

Este ticket entrega duas coisas no roteador de LLM:

1. Uma chave nova por chamada, `reasoning=False`, que desliga o modo de
   raciocínio quando o provedor é DeepSeek. Quem chamar sem passar nada continua
   igual a hoje.
2. Um alarme alto no log toda vez que uma chamada volta com texto vazio,
   dizendo quem chamou, qual modelo, qual era o teto de tokens, o motivo de
   parada e quantos tokens foram para o raciocínio.

Nada muda na tela por si só; o efeito visível vem no T-005, que passa a usar a
chave nova nas chamadas mecânicas. O que muda aqui é que uma falha dessas passa
a aparecer no log do servidor em vez de sumir.

## Onde mexer

`backend/app/engines/llm_router.py`.

FATO MEDIDO nesta investigação (não precisa re-testar, mas pode): contra
`https://api.deepseek.com/chat/completions`, com litellm 1.43.0 já instalado no
venv, passar `reasoning_effort="none"` para `litellm.acompletion` com
`model="deepseek/deepseek-v4-flash"` funciona, não dá erro, e a resposta volta
SEM `reasoning_content` (usage cai de ~72 para ~7 tokens de saída na mesma
pergunta). Sem esse parâmetro e com `max_tokens=64`, o mesmo prompt devolve
`content` vazio. É exatamente o bug.

### 1. Chave `reasoning`

Em `LLMRouter.complete` (linha ~585) e `LLMRouter.stream` (linha ~641), logo
depois da linha que já existe:

```python
max_tokens = kwargs.pop("max_tokens", self.config.max_tokens)
```

acrescente:

```python
reasoning = kwargs.pop("reasoning", True)
```

O `pop` tem de vir ANTES de `call_kwargs = {**kwargs}` (e, em `complete`, antes
de `fb_kwargs = {**kwargs}` no bloco de fallback), para que a chave nunca seja
enviada à API como parâmetro solto.

Crie no módulo um helper e use-o nos dois métodos:

```python
def _reasoning_kwargs(provider: LLMProvider, reasoning: bool) -> dict:
    """DeepSeek V4 counts reasoning against max_tokens; disable it for mechanical calls."""
    if reasoning or provider != LLMProvider.DEEPSEEK:
        return {}
    return {"reasoning_effort": "none"}
```

Em `complete` e em `stream`, depois de montar `call_kwargs`, faça
`call_kwargs.update(_reasoning_kwargs(self.config.primary_provider, reasoning))`.
No bloco de fallback de `complete` (linha ~621), faça o mesmo com
`self.config.fallback_provider` sobre `fb_kwargs`.

NUNCA envie `reasoning_effort` para os provedores `anthropic` e `openai` — o
helper acima já garante isso, e é o comportamento exigido: o provedor Anthropic
passa por um proxy local que não conhece esse campo.

### 2. Alarme de resposta vazia

Em `_log_call` (linha ~252), a entrada do log já é montada num dict `entry`.
Acrescente ali:

- `finish_reason`: melhor esforço, `getattr(response.choices[0], "finish_reason", "") or ""` dentro de `try/except`, string vazia se não der.
- `reasoning_tokens`: melhor esforço, a partir de `usage`:
  `getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", 0) or 0`.

Inclua os dois no dict `entry` e também no dict `usage` devolvido por
`get_call_trace` (linha ~85), como `"reasoning": ...`, para que o painel de
devtools e o `scripts/dump_traces.py` mostrem o número.

Depois, ainda em `_log_call`, quando o texto extraído por
`_extract_response_text(response)` for vazio ou só espaço, emita:

```python
logger.error(
    "🚨 LLM EMPTY OUTPUT [%s] model=%s max_tokens=%d finish_reason=%s "
    "output_tokens=%d reasoning_tokens=%d — model spent the budget before writing an answer",
    caller, model, max_tokens, finish_reason, output_tokens, reasoning_tokens,
)
```

Faça o mesmo no caminho de streaming real (final de `stream`, linha ~726 em
diante, onde a variável `accumulated` é fechada): se `accumulated` ficou vazio,
emita o mesmo `logger.error` (ali não há `finish_reason`; passe string vazia).

Chame `_extract_response_text` uma única vez por chamada e reaproveite o
resultado — hoje ele é chamado duas vezes em `_log_call`; consolidar numa
variável local é bem-vindo, desde que o que vai para `entry["output"]` e para
`_dump_call` continue sendo o mesmo texto.

### 3. Testes

Em `backend/tests/engines/test_llm_router.py`, seguindo o estilo que já está lá
(`patch("app.engines.llm_router.litellm.acompletion", new=AsyncMock(...))` e
`MagicMock` para a resposta), acrescente:

- `complete(messages, reasoning=False)` com config DeepSeek: os kwargs recebidos por `acompletion` contêm `reasoning_effort == "none"` e NÃO contêm a chave `reasoning`.
- `complete(messages)` sem a chave: os kwargs NÃO contêm `reasoning_effort`.
- `complete(messages, reasoning=False)` com `primary_provider=LLMProvider.ANTHROPIC`: os kwargs NÃO contêm `reasoning_effort`.
- resposta com `content=""`: usando `caplog` em nível ERROR, o log contém `EMPTY OUTPUT` e o nome do chamador.

Rode: `cd backend && venv/Scripts/python.exe -m pytest tests/engines/test_llm_router.py -q`.
A suíte inteira também tem de continuar verde:
`cd backend && venv/Scripts/python.exe -m pytest tests -q`.

## Fora do escopo

- Passar `reasoning=False` nas chamadas dos motores do jogo: isso é o T-005.
- Aumentar o orçamento do auditor: isso é o T-006.
- Consertar o system prompt descartado pelo proxy do Claude: isso é o T-007.
- Repetir a chamada automaticamente quando ela volta vazia. Aqui só se registra o erro.
- Mexer no painel de devtools do frontend.

## Pronto quando

- [ ] `LLMRouter.complete` e `LLMRouter.stream` aceitam `reasoning=False` e nunca repassam a chave `reasoning` para a API.
- [ ] Com provedor DeepSeek e `reasoning=False`, a chamada à API leva `reasoning_effort="none"`.
- [ ] Com provedor Anthropic ou OpenAI, `reasoning_effort` nunca é enviado.
- [ ] Sem a chave, o comportamento é idêntico ao de hoje (nenhum parâmetro novo).
- [ ] Toda chamada que volta com texto vazio gera um `logger.error` contendo `EMPTY OUTPUT`, o chamador, o modelo, o teto de tokens e os tokens de raciocínio.
- [ ] `get_call_trace` devolve `reasoning` dentro de `usage`.
- [ ] `cd backend && venv/Scripts/python.exe -m pytest tests -q` passa.

## Como testar (humano)

1. Inicie o jogo normalmente e jogue um turno qualquer numa campanha existente.
2. Olhe a janela preta do servidor (o terminal do backend) enquanto o turno roda.
3. O turno tem de sair igual ao de antes, sem nenhuma mudança na história nem na velocidade.
4. Se em algum momento uma resposta do modelo voltar vazia, agora aparece uma linha vermelha de erro no terminal com as palavras EMPTY OUTPUT e o nome da etapa que falhou. Antes essa falha não aparecia em lugar nenhum.
