---
id: T-006
title: Dar orçamento de raciocínio ao auditor do narrador e registrar quando ele falha
status: ready
blockedBy: []
files: [backend/app/engines/auditor_engine.py, backend/tests/engines/test_auditor_engine.py]
---

## O que fazer

O auditor é a última checagem antes de a narração aparecer para o jogador: ele
recebe o texto pronto e corta o que o narrador inventou por conta própria. Hoje
ele NUNCA audita nada. Motivo medido: o modelo pensa antes de responder, e esse
pensamento consome o mesmo orçamento de tokens da resposta. Com o teto atual
(6000 tokens no total), o modelo gastou 16 mil caracteres pensando e devolveu
resposta vazia. O log registra apenas
`Auditor returned unparseable output; releasing original prose`, e o turno segue
com o texto original — depois de queimar 37 dos 60 segundos do turno.

Este ticket dá ao auditor um orçamento que cabe raciocínio + resposta, e faz o
sistema reclamar de forma clara quando a auditoria falha, distinguindo os três
casos: resposta vazia, resposta que não é JSON válido, e erro de chamada.

## Onde mexer

`backend/app/engines/auditor_engine.py`, no método `AuditorEngine.audit`
(linha ~257).

### 1. Orçamento

Hoje a linha 300 é:

```python
api_max_tokens = max_tokens + 2000  # prose rewrite + corrections + gate headroom
```

Troque por um cálculo que some, além disso, uma folga de raciocínio configurável
por variável de ambiente, seguindo o padrão de flags que
`backend/app/services/game_session.py` já usa (funções de módulo que leem
`os.environ` com valor padrão e degradam para o padrão em valor inválido, como
`_audit_timeout_s`):

```python
def _reasoning_headroom() -> int:
    """Extra output budget for models that spend max_tokens on reasoning."""
    raw = os.environ.get("LUNAR_AUDIT_REASONING_HEADROOM", "8000") or "8000"
    try:
        v = int(raw)
    except ValueError:
        return 8000
    return v if v > 0 else 8000
```

e use `api_max_tokens = max_tokens + 2000 + _REASONING_HEADROOM` (constante de
módulo calculada uma vez no import, igual ao padrão de `_AUDIT_TIMEOUT_S`).

Com o padrão do jogo (`max_tokens=2000`) isso dá 12000 tokens de teto. FATO
VERIFICADO nesta investigação: a API DeepSeek aceita `max_tokens=12000` para
`deepseek-v4-flash` sem erro. Não passe `reasoning=False` aqui — o auditor
precisa raciocinar.

### 2. Reclamar quando falha

Ainda em `audit`, depois da chamada `raw = await self._llm.complete(...)`:

- Se `raw` for vazio ou só espaço em branco, registre
  `logger.error("Auditor returned EMPTY output (max_tokens=%d); releasing original prose", api_max_tokens)`
  e devolva `prose, {"verdict": "clean", "error": "empty_output"}`.
- Se `parse_json_dict(raw)` falhar (bloco da linha ~307), o warning existente vira
  `logger.error` e passa a incluir o tamanho de `raw` e os primeiros 300
  caracteres, para dar o que investigar.
- O bloco `except` da chamada (linha ~302) continua devolvendo a prosa original,
  mas com `logger.error` no lugar de `logger.warning`.

O contrato do método não muda: em qualquer falha ele devolve a prosa ORIGINAL
intacta e um dict de report. Um turno nunca pode quebrar por causa do auditor.

### 3. Testes

Em `backend/tests/engines/test_auditor_engine.py` (o dublê `_FakeLLM` já grava
`last_max_tokens` e já aceita `**kwargs`), acrescente:

- teto de saída: com `max_tokens=2000`, `llm.last_max_tokens == 12000`.
- variável de ambiente respeitada: não é obrigatório testar o `os.environ` (a constante é lida no import); basta testar o valor padrão.
- resposta vazia: `_FakeLLM("")` devolve a prosa original, `report["error"] == "empty_output"`, e o log em nível ERROR contém `EMPTY output` (use `caplog`).
- resposta não-JSON: `_FakeLLM("bla bla")` devolve a prosa original e loga em nível ERROR.

Rode: `cd backend && venv/Scripts/python.exe -m pytest tests/engines/test_auditor_engine.py tests/services/test_narrator_audit.py -q`
e depois a suíte inteira: `cd backend && venv/Scripts/python.exe -m pytest tests -q`.

## Fora do escopo

- Desligar o raciocínio do auditor. Ele é a única chamada do jogo que precisa raciocinar de verdade.
- Mudar o texto do prompt do auditor (as duas strings gigantes `_EN_SYSTEM` e `_PTBR_SYSTEM`).
- Mudar o tempo limite da auditoria (`LUNAR_AUDIT_TIMEOUT_S`, em `game_session.py`) ou o ponto onde ela é chamada.
- Repetir a auditoria quando ela volta vazia.
- Mexer no roteador de LLM.

## Pronto quando

- [ ] Com `max_tokens=2000`, a chamada do auditor pede 12000 tokens de saída.
- [ ] O teto extra é configurável por `LUNAR_AUDIT_REASONING_HEADROOM`, com padrão 8000 e degradação para o padrão em valor inválido.
- [ ] Resposta vazia gera log em nível ERROR com a palavra `EMPTY` e devolve a prosa original com `error == "empty_output"`.
- [ ] Resposta que não é JSON gera log em nível ERROR incluindo o começo do texto recebido.
- [ ] Em qualquer falha, o método continua devolvendo a prosa original sem exceção.
- [ ] `cd backend && venv/Scripts/python.exe -m pytest tests -q` passa.

## Como testar (humano)

1. Inicie o jogo e jogue um turno numa campanha existente.
2. Olhe a janela preta do servidor durante o turno.
3. Não pode mais aparecer a mensagem dizendo que a auditoria devolveu saída ilegível e liberou o texto original. Se ainda aparecer alguma falha, agora ela vem em vermelho e diz o motivo (resposta vazia ou resposta ilegível) junto com um pedaço do que o modelo devolveu.
4. A narração continua aparecendo normalmente na tela, sem travar nem sumir, aconteça o que acontecer com a auditoria.
