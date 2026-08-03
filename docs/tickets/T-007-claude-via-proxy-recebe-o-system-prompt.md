---
id: T-007
title: Entregar o system prompt ao Claude via proxy movendo-o para a primeira mensagem de usuário
status: ready
blockedBy: [T-004]
files: [backend/app/engines/llm_router.py, backend/tests/engines/test_llm_router.py]
---

## O que fazer

Quando o jogador escolhe Anthropic (Claude) nas configurações, o jogo hoje
manda todas as instruções — tom, regras do narrador, lore, memória, formato de
resposta em JSON — no campo `system` da requisição. Esse campo é DESCARTADO
antes de chegar ao modelo: o proxy local (CLIProxyAPI, na porta 8318) autentica
com credencial de assinatura e SUBSTITUI o `system` pelo prompt do Claude Code.
Ou seja: com Claude, o narrador do jogo nunca recebe nenhuma instrução.

Provas medidas nesta investigação, com `curl` direto no proxy, tanto no endpoint
`/v1/chat/completions` quanto no `/v1/messages` nativo (os dois descartam igual):

- `system` de 200 caracteres + "Quem é você?" → responde "Sou Claude Code, o CLI oficial da Anthropic", `prompt_tokens=1484`.
- `system` real do narrador com 20028 caracteres + a mesma pergunta → MESMA resposta, `prompt_tokens=1484` idêntico (o texto grande não chegou).
- marcadores `MARCADOR_INICIO=BANANA123` e `MARCADOR_FIM=UVA456` dentro de um `system` de 20078 caracteres → o modelo responde "NAO_RECEBI" para os dois.
- o MESMO conteúdo enviado como mensagem de papel `user` → o modelo repete os dois marcadores e `prompt_tokens=7871` (o texto chegou).

A correção: quando o provedor é Anthropic E existe proxy configurado, mover todo
o conteúdo das mensagens de sistema para dentro de uma mensagem de usuário, que
o proxy repassa intacta.

Efeito visível: jogando com Claude, a narração passa a sair no idioma da
campanha, no tom do cenário, respeitando as regras do narrador e o formato
esperado — em vez do texto genérico/fallback de hoje.

## Onde mexer

Só `backend/app/engines/llm_router.py`.

O arquivo JÁ tem metade disso pronto: `_cloak_messages_for_anthropic`
(linha ~375) faz exatamente essa mudança, mas só é aplicada às mensagens no
"formato cacheado" da FASE 2 (system cujo `content` é uma lista de blocos), via
`_prepare_cached_messages` (linha ~525). Todas as demais chamadas do jogo mandam
`{"role": "system", "content": "<string>"}` e caem direto no `litellm.acompletion`
com o system intacto — e perdido.

### 1. Função nova

Acrescente no módulo, perto de `_cloak_messages_for_anthropic`:

```python
_SYSTEM_CLOAK_TAG = "system-instructions"
_SYSTEM_CACHE_MIN_CHARS = 5000
_SYSTEM_CACHE_CONTROL = {"type": "ephemeral", "ttl": "1h"}


def _fold_system_into_user(messages: list[dict]) -> tuple[list[dict], bool]:
    """Proxy OAuth mode replaces the system field, so carry system text as a leading
    user block instead. Returns (messages, cached) — cached is True when the folded
    block got cache_control."""
```

Comportamento exigido:

- Junta o texto de TODAS as mensagens com `role == "system"`, na ordem original, separando por `\n`. O `content` pode ser string ou lista de blocos; no caso de lista, concatene o campo `text` de cada bloco.
- Se não houver nenhuma mensagem de sistema, devolve `(messages, False)` sem tocar em nada.
- Envolve o texto juntado em `<system-instructions>\n...\n</system-instructions>`.
- Monta o bloco `{"type": "text", "text": <texto envolvido>}`; se o texto juntado tiver 5000 caracteres ou mais, acrescenta `"cache_control": _SYSTEM_CACHE_CONTROL` ao bloco e devolve `cached=True`.
- Devolve `[{"role": "user", "content": [bloco]}] + [m for m in messages if m.get("role") != "system"]`.

O limite de 5000 caracteres existe porque a Anthropic só cacheia blocos a partir
de ~1024 tokens; abaixo disso o marcador seria inútil.

### 2. Aplicar nos dois caminhos

Em `LLMRouter.complete` (linha ~585) e em `LLMRouter.stream` (linha ~641), logo
DEPOIS da linha `messages = self._prepare_cached_messages(messages, call_kwargs)`
e da atribuição de `api_base`, acrescente:

```python
if api_base and self.config.primary_provider == LLMProvider.ANTHROPIC:
    messages, folded_cached = _fold_system_into_user(messages)
    if folded_cached:
        call_kwargs["extra_headers"] = {
            **_CACHE_HEADERS,
            **call_kwargs.get("extra_headers", {}),
        }
```

Nas mensagens já no formato cacheado da FASE 2, `_prepare_cached_messages` já
removeu o system, então a função nova é um no-op ali — é o comportamento
desejado, não duplique o cloaking.

Em `_complete_anthropic_sdk` (linha ~542), como defesa do segundo caminho de
código, aplique `messages, _ = _fold_system_into_user(messages)` logo no começo
do método, antes do laço de tentativas. O SDK da Anthropic não aceita papel
`system` dentro de `messages`; com isso nenhum caminho consegue mais vazar um
system para o proxy.

Não mexa nos provedores `deepseek` e `openai`: os dois usam `system` normalmente
e o `deepseek` é o padrão da campanha. A dobra é condicionada a
`api_base and provider == ANTHROPIC` — Anthropic direto pela API oficial (sem
proxy) continua mandando `system`, que lá funciona.

CONSEQUÊNCIA ESPERADA E ACEITA: o custo por turno com Claude sobe, porque esses
tokens hoje simplesmente não são enviados. É justamente por isso que o bloco
grande leva `cache_control` — sem ele, o texto inteiro seria cobrado a cada
turno. Os ~1366 tokens do prompt do Claude Code continuam vindo em toda chamada;
não há o que fazer do nosso lado.

### 3. Testes

Em `backend/tests/engines/test_llm_router.py`, com
`patch("app.engines.llm_router._ANTHROPIC_PROXY_URL", "http://localhost:8318")` e
`patch("app.engines.llm_router.litellm.acompletion", new=AsyncMock(...))`:

- provedor Anthropic com proxy: dadas `[{"role":"system","content":"MARCADOR_XYZ"},{"role":"user","content":"oi"}]`, as mensagens recebidas por `acompletion` não têm nenhuma com `role == "system"`, e `MARCADOR_XYZ` aparece dentro do conteúdo da primeira mensagem, que tem `role == "user"`.
- provedor DeepSeek: as mesmas mensagens chegam a `acompletion` inalteradas, com a mensagem de sistema no lugar.
- system com 6000 caracteres e provedor Anthropic com proxy: o bloco dobrado carrega `cache_control` e `extra_headers` inclui `anthropic-beta`.
- system curto (200 caracteres): o bloco dobrado NÃO carrega `cache_control`.
- teste direto de `_fold_system_into_user` com `content` em lista de blocos: o texto de todos os blocos aparece no resultado.

Rode: `cd backend && venv/Scripts/python.exe -m pytest tests -q`.

## Fora do escopo

- Configurar o proxy CLIProxyAPI para parar de substituir o `system` (não é possível no modo de credencial de assinatura).
- Remover os ~1366 tokens do prompt do Claude Code que vêm em toda chamada.
- Mudar o provedor padrão da campanha, que continua deepseek.
- Desligar raciocínio (T-004/T-005) ou orçamento do auditor (T-006).
- Fazer o mesmo para OpenAI.

## Pronto quando

- [ ] Com provedor Anthropic e proxy configurado, nenhuma requisição sai com mensagem de papel `system`, nem pelo caminho do litellm nem pelo caminho do SDK da Anthropic.
- [ ] O conteúdo que estava no system aparece integralmente dentro da primeira mensagem de usuário, envolvido em `<system-instructions>`.
- [ ] Blocos com 5000 caracteres ou mais levam `cache_control` de 1 hora e o cabeçalho `anthropic-beta`.
- [ ] Com provedor deepseek, as mensagens continuam exatamente como hoje.
- [ ] Com provedor Anthropic sem proxy configurado, as mensagens continuam exatamente como hoje.
- [ ] `cd backend && venv/Scripts/python.exe -m pytest tests -q` passa.

## Como testar (humano)

1. Abra o jogo e entre numa campanha existente.
2. Abra as configurações e troque o provedor para Anthropic, escolhendo o modelo Claude Sonnet.
3. Jogue um turno normal, em português.
4. A narração tem de vir em português, no clima do cenário, continuando a história daquela campanha, com os nomes certos dos personagens e lugares.
5. Antes desta correção, o mesmo teste devolvia um texto genérico, fora do tom, ignorando o cenário — ou o modelo até se apresentava como assistente de programação.
6. Volte as configurações para o provedor DeepSeek e jogue outro turno: ele tem de continuar funcionando igual a antes.
