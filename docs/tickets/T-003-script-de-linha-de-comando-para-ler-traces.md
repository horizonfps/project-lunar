---
id: T-003
title: Criar script de linha de comando que imprime os traces salvos no banco
status: ready
blockedBy: [T-001]
files: [backend/scripts/dump_traces.py]
---

## O que fazer

Com os traces gravados no banco (T-001), falta um jeito de ler tudo fora do
navegador — que é como o histórico vira material de depuração. Esta tarefa entrega
um script de linha de comando que lista as campanhas com traces salvos e imprime,
para uma campanha escolhida, os últimos turnos: cada chamada de LLM com o modelo,
os tokens, o tempo, a resposta e, opcionalmente, o texto integral enviado.

## Onde mexer

Arquivo novo `backend/scripts/dump_traces.py`. Depende do T-001, que entrega
`backend/app/db/trace_store.py` com a classe `TraceStore` e os métodos
`list_campaigns() -> [{"campaign_id", "turns", "last_created_at"}]`,
`get_recent(campaign_id, limit) -> list[dict]` (ordem cronológica crescente, cada
item com `key`, `label`, `turn_index`, `action`, `created_at`, `entries`, `summary`)
e `close()` / uso como context manager. Cada item de `entries` tem as chaves `seq`,
`tag`, `label`, `model`, `instructions_chars`, `elapsed_s`,
`usage` (`{"input","output","cache_read","cache_creation"}`), `input` (lista de
seções `{"title","body","truncated"}`) e `output` (string) — é o formato produzido
por `get_call_trace()` em `backend/app/engines/llm_router.py`.

Siga o padrão dos scripts que já existem em `backend/scripts/` (veja
`backend/scripts/validate_fase2_cache.py`): docstring curta no topo com a linha de
uso, e
`sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
antes de importar de `app.`.

Interface, com `argparse`:

- `--db PATH` — caminho do banco; default = `os.environ.get("LLM_TRACE_DB_PATH")` ou
  `traces.db` dentro da pasta `backend` (mesmo default usado em
  `backend/app/api/routes_game.py`).
- `--campaign ID` — campanha a inspecionar. Quando omitido, o script imprime a lista
  de campanhas (`campaign_id`, quantidade de turnos, data do último) e encerra com
  código 0.
- `--limit N` — quantos turnos mais recentes imprimir (default 3).
- `--turn N` — imprime só o turno de `turn_index` igual a N (filtre o resultado de
  `get_recent` com um `limit` alto).
- `--full` — além da saída de cada chamada, imprime todas as seções de `input`
  (título + corpo). Sem essa flag, imprime apenas o título de cada seção e o tamanho
  em caracteres do corpo.
- `--json` — imprime o resultado bruto com `json.dumps(..., ensure_ascii=False,
  indent=2)` e ignora a formatação legível.

Formato legível: por turno, uma linha de cabeçalho com `turn_index`, `created_at`,
número de chamadas, os totais de `summary` e a ação do jogador; depois, por chamada,
uma linha com `seq`, `tag`, `label`, `model`, tokens de entrada/saída, cache e
`elapsed_s`, seguida do `output`. Use separadores de texto simples (linhas de `=` e
`-`); nada de dependência nova.

Robustez: se o arquivo do banco não existir, imprima uma mensagem clara e saia com
código 1. Se a campanha não tiver traces, imprima aviso e saia com código 0. Escreva
tudo com `print` (sem `logging`).

Nada mais no repositório deve mudar. Não crie testes automatizados para este script.

## Fora do escopo

- Alterar `backend/app/db/trace_store.py`, as rotas ou o frontend.
- Apagar ou editar traces pelo script (só leitura).
- Exportar para CSV/HTML ou qualquer formato além de texto e JSON.

## Pronto quando

- [ ] `backend/scripts/dump_traces.py` existe e roda com
      `cd backend && venv/Scripts/python.exe scripts/dump_traces.py` sem argumentos,
      listando as campanhas com traces (ou avisando que não há nenhuma).
- [ ] Com `--campaign <id>` imprime os últimos turnos e, por chamada, modelo,
      tokens, tempo e a resposta.
- [ ] `--full` imprime o corpo integral de cada seção de entrada; sem `--full`,
      imprime só título e tamanho.
- [ ] `--turn N` imprime apenas o turno pedido.
- [ ] `--json` imprime JSON válido.
- [ ] Banco inexistente encerra com mensagem clara e código de saída 1.

## Como testar (humano)

1. Jogue pelo menos um turno numa campanha, para haver algo salvo.
2. Abra o terminal na pasta do projeto e rode o comando que lista as campanhas
   salvas (o desenvolvedor deixou o comando na primeira linha do arquivo do script).
   Tem que aparecer pelo menos uma campanha com a contagem de turnos.
3. Rode o mesmo comando informando o identificador dessa campanha. Tem que aparecer
   o resumo dos últimos turnos com o texto que a IA respondeu em cada chamada.
4. Repita o comando acrescentando a opção de saída completa: agora aparece também
   todo o texto que foi enviado para a IA.
