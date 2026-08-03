---
id: T-001
title: Persistir o trace de cada turno num banco SQLite e expor via API
status: ready
blockedBy: []
files: [backend/app/db/trace_store.py, backend/app/api/routes_game.py, backend/tests/db/test_trace_store.py, backend/tests/api/test_routes_traces.py]
---

## O que fazer

Hoje o histórico completo das chamadas de LLM de um turno (entrada + saída de cada
call) só existe em memória: é enviado ao frontend no fim do turno pelo frame SSE
`[TRACE]` e some quando o navegador recarrega ou o backend reinicia. Depois desta
tarefa, todo turno jogado grava esse trace num banco SQLite no servidor, e existe
uma rota HTTP que devolve os traces salvos de uma campanha e outra que apaga todos
os traces daquela campanha. O comportamento visível: dá para chamar
`GET /api/game/<campaign_id>/traces` depois de jogar e receber, em JSON, o que cada
chamada de LLM daquele turno recebeu e respondeu — inclusive depois de reiniciar o
backend.

## Onde mexer

**Novo arquivo `backend/app/db/trace_store.py`.** Siga o padrão de
`backend/app/db/event_store.py` (leia antes): `sqlite3.connect(db_path,
check_same_thread=False)`, `threading.Lock()`, dicionário `_MIGRATIONS` com chave
= versão alvo e valor = lista de SQL, constante `SCHEMA_VERSION`, métodos
`_get_schema_version()` / `_migrate()` idênticos em estrutura aos de `EventStore`
(tabela `schema_version`), além de `close()`, `__enter__` e `__exit__`.

Classe `TraceStore`, `SCHEMA_VERSION = 1`, migração 1:

```sql
CREATE TABLE IF NOT EXISTS llm_traces (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    action TEXT NOT NULL DEFAULT '',
    entries TEXT NOT NULL DEFAULT '[]',
    call_count INTEGER NOT NULL DEFAULT 0,
    total_input_tokens INTEGER NOT NULL DEFAULT 0,
    total_output_tokens INTEGER NOT NULL DEFAULT 0,
    total_cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    total_cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    total_time_s REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
```
mais `CREATE INDEX IF NOT EXISTS idx_trace_campaign ON llm_traces(campaign_id, created_at)`.

Métodos públicos:

- `append(campaign_id: str, action: str, entries: list, summary: dict | None = None,
  keep: int | None = None) -> dict` — gera `id` com `uuid.uuid4()`, `created_at` com
  `datetime.utcnow().isoformat()`, `turn_index` = `(SELECT MAX(turn_index) ...
  WHERE campaign_id=?)` + 1 (1 quando não há linhas), grava `entries` com
  `json.dumps(entries, ensure_ascii=False)`, `call_count = len(entries)`. Os campos
  `total_*` vêm das chaves de mesmo nome do `summary` (que é o dict de
  `get_call_summary()` em `backend/app/engines/llm_router.py`: `call_count`,
  `total_input_tokens`, `total_output_tokens`, `total_cache_read_tokens`,
  `total_cache_creation_tokens`, `total_time_s`), com default 0 quando ausente.
  Ao final, poda: mantém apenas as `keep` linhas mais recentes daquela campanha
  (`keep` default = `int(os.environ.get("LLM_TRACE_KEEP", "100"))`), apagando as
  demais por `turn_index` crescente. Retorna o dict da linha inserida no mesmo
  formato do `get_recent`.
- `get_recent(campaign_id: str, limit: int = 25) -> list[dict]` — as `limit` linhas
  mais recentes, devolvidas em ordem **cronológica crescente** (mais antiga
  primeiro), cada uma como dict:
  `{"key": id, "label": f"turn {turn_index}", "turn_index": int, "action": str,
  "created_at": str, "entries": <lista já desserializada>, "summary": {"call_count":
  int, "total_input_tokens": int, "total_output_tokens": int,
  "total_cache_read_tokens": int, "total_cache_creation_tokens": int,
  "total_time_s": float}}`. Se o JSON de `entries` estiver corrompido, use `[]` em
  vez de estourar exceção.
- `delete_for_campaign(campaign_id: str) -> int` — apaga tudo daquela campanha e
  devolve `cursor.rowcount`.
- `list_campaigns() -> list[dict]` — `[{"campaign_id": str, "turns": int,
  "last_created_at": str}]`, ordenado por `last_created_at` decrescente. (Usado pelo
  T-003; entregue já neste ticket.)

Todo `INSERT`/`DELETE` roda dentro de `with self._lock:` seguido de
`self._conn.commit()`, como em `EventStore`.

**`backend/app/api/routes_game.py`.** Já existem no topo do módulo
`_event_store = EventStore(os.environ.get("EVENT_DB_PATH", os.path.join(_BACKEND_DIR,
"events.db")))` e o import de `get_call_trace` do `llm_router`. Adicione, no mesmo
bloco:

```python
from app.db.trace_store import TraceStore
_trace_store = TraceStore(os.environ.get("LLM_TRACE_DB_PATH", os.path.join(_BACKEND_DIR, "traces.db")))
```

Dentro de `event_stream()` da rota `@router.post("/action")`, hoje há:

```python
yield f"data: [TRACE]{json.dumps(get_call_trace(), ensure_ascii=False)}\n\n"
```

Troque por: guardar `trace = get_call_trace()` numa variável, persistir **antes** de
emitir o frame, e só então emitir o mesmo frame usando a variável. A persistência
fica dentro de `try/except Exception` com `logger.exception(...)`: falha de banco
nunca pode quebrar o stream do turno. Só persista quando `trace` for não-vazio.
Passe `req.action` como `action` e o `summary` já calculado logo acima.

Duas rotas novas, junto das outras rotas `@router.get("/{campaign_id}/...")` do
arquivo:

- `@router.get("/{campaign_id}/traces")` com parâmetro de query `limit: int = 25`,
  retornando `{"traces": _trace_store.get_recent(campaign_id, limit)}`. Se o banco
  falhar, retorne `{"traces": []}` em vez de 500.
- `@router.delete("/{campaign_id}/traces")` retornando
  `{"deleted": _trace_store.delete_for_campaign(campaign_id)}`.

**Testes.** `backend/tests/db/test_trace_store.py` no estilo de
`backend/tests/db/test_event_store.py` (fixture com `tmp_path`, `store.close()` no
teardown), cobrindo: round-trip de `append`/`get_recent` preservando o conteúdo
aninhado de `entries` (use uma entrada realista, com `input` sendo lista de dicts
`{"title","body","truncated"}` e `output` string com acentos e quebras de linha);
`turn_index` incrementando 1, 2, 3 na mesma campanha; isolamento entre campanhas;
`get_recent` devolvendo em ordem crescente de `turn_index`; poda com `keep=2`
deixando só os 2 turnos mais recentes; `delete_for_campaign` devolvendo a
quantidade apagada; `list_campaigns` devolvendo a contagem por campanha.

`backend/tests/api/test_routes_traces.py` com fixture de `TestClient` copiada de
`backend/tests/api/test_routes_game.py` (mesmos `monkeypatch.setenv` de
`SCENARIO_DB_PATH` e `EVENT_DB_PATH`, mais `LLM_TRACE_DB_PATH` apontando para
`tmp_path`), testando que `GET /api/game/<id-inexistente>/traces` responde 200 com
`{"traces": []}` e que `DELETE /api/game/<id-inexistente>/traces` responde 200 com
a chave `deleted`. Não chame LLM real nesses testes.

Rode `cd backend && venv/Scripts/python.exe -m pytest` e deixe verde.

Armadilha: `*.db` já está no `.gitignore`, então `backend/traces.db` não vaza para
o git — não mexa no `.gitignore`.

## Fora do escopo

- Qualquer alteração no frontend (`frontend/`): o consumo da nova rota é o T-002.
- Script de linha de comando para ler os traces: é o T-003.
- Persistir chamadas de LLM disparadas fora do turno (efeitos colaterais
  fire-and-forget) — só o que `get_call_trace()` já devolve entra no banco.
- Mudar `backend/app/engines/llm_router.py`, `EventStore` ou o formato do frame SSE
  `[TRACE]` que o frontend já consome.

## Pronto quando

- [ ] `backend/app/db/trace_store.py` existe com a classe `TraceStore` e os métodos
      `append`, `get_recent`, `delete_for_campaign`, `list_campaigns`, `close`,
      `__enter__`, `__exit__`.
- [ ] A rota `POST /api/game/action` grava uma linha em `llm_traces` por turno com
      trace não-vazio, e continua emitindo o frame SSE `[TRACE]` com o mesmo
      conteúdo de antes.
- [ ] Uma exceção do banco durante a gravação não interrompe o stream do turno
      (bloco `try/except` com log).
- [ ] `GET /api/game/{campaign_id}/traces?limit=N` responde 200 com
      `{"traces": [...]}` em ordem cronológica crescente, cada item tendo as chaves
      `key`, `label`, `action`, `created_at`, `entries`, `summary`.
- [ ] `DELETE /api/game/{campaign_id}/traces` responde 200 com `{"deleted": <int>}`
      e depois dele o GET devolve lista vazia.
- [ ] `backend/tests/db/test_trace_store.py` e `backend/tests/api/test_routes_traces.py`
      existem e `cd backend && venv/Scripts/python.exe -m pytest` passa inteiro.

## Como testar (humano)

1. Inicie o jogo pelo atalho de sempre e abra uma campanha.
2. Escreva uma ação qualquer e espere a resposta terminar.
3. No navegador, abra o endereço `http://localhost:8000/api/game/ID/traces`,
   trocando `ID` pelo identificador da campanha que aparece no endereço da tela do
   jogo. Tem que aparecer um texto em JSON com o conteúdo do turno que você acabou
   de jogar.
4. Feche o jogo inteiro e abra de novo. Abra o mesmo endereço do passo 3: o
   conteúdo continua lá.
