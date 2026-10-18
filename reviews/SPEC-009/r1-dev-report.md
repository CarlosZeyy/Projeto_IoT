# SPEC-009 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-009](../../docs/specs/SPEC-009-edge-outbox-publisher.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-009-edge-outbox-publisher` |
| Commits | `afd34f2`, `10ac85d`, `4008e78`, `28b1f6a`, `6419e43`; retomada após o SPEC_ISSUE-01: `7fcee19` (`fix(edge)` do `--stub-model`) e o commit desta atualização do relatório |

## Resumo

- `qc_edge.outbox.SqliteOutbox` implementa o `InspectionSink` da SPEC-007. Usa o schema e o índice da §4.1, WAL, `synchronous=FULL`, uma conexão protegida por `threading.Lock`, `put` idempotente (`ON CONFLICT DO NOTHING`, com commit antes de retornar) e datas ISO 8601 UTC de largura fixa.
- `qc_edge.publisher.HttpPublisher` envia o `BatchCreate` em JSON para `/api/v1/inspections/batch` com `X-API-Key` e valida o `BatchResult` (mesmos ids, na mesma ordem). Mapeia 401/403, 413/422 e as falhas transitórias para as três exceções da §4.2. O `detail` da recusa é o resumo do SEC-04-04, e o corpo da resposta nunca é guardado. É o único módulo do `qc_edge` que importa `httpx`.
- `qc_edge.publish_loop.PublishLoop` (o `BackgroundService` da SPEC-007) e `ConnectivityState` implementam o ciclo da §4.3: backoff `min(60, 2^n·U(0,8; 1,2))`, bissecção até o item `dead`, pausa em `auth_error`, health check a cada 60 s sem contato, e exceção inesperada registrada no log com retry, sem derrubar a thread.
- `qc-edge` (§4.4): sem `--stub-model`, o sink é `SqliteOutbox(OUTBOX_PATH)` (padrão `EDGE_DATA_DIR/outbox.sqlite3`), e o `PublishLoop` só é registrado com `DEVICE_API_KEY` **e** `CLOUD_API_URL`. Com `--stub-model`, o sink é o `InMemorySink()`, não há laço, e `OUTBOX_PATH` não é aberto, criado nem validado. `CLOUD_API_URL` inválida, chave inválida ou outbox que não abre dão código 2, e a mensagem cita a variável, nunca o valor. O console ganhou `id`s e o código da conectividade em `data-connectivity`, e o `auth_error` mostra a ação ("confira o DEVICE_API_KEY e reinicie").
- `edge/README.md` (seção "Envio para a nuvem", com o roteiro do CA-17) e `.env.example` atualizados.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `edge/src/qc_edge/outbox.py` (`put`) | `edge/tests/test_outbox.py::test_put_three_times_keeps_one_pending_row`, `::test_put_never_changes_a_sent_row` |
| CA-02 | `publish_loop.py` (`run_once`, `_publish`), `outbox.py` (`fetch_due` por `created_at, rowid`) | `edge/tests/test_publish_loop.py::test_150_items_in_two_batches` |
| CA-03 | `publish_loop.py` (`created` e `duplicate` → `mark_sent`) | `test_publish_loop.py::test_duplicates_are_sent`; contra a API real: `edge/tests/test_publisher_real_api.py::test_batch_created_then_duplicate` |
| CA-04 | `publisher.py` (transitórios), `publish_loop.py` (`delay_s`, `_Unreachable`), `outbox.py` (`mark_retry`) | `test_publish_loop.py::test_transient_error_schedules_a_retry` (ConnectError, ReadTimeout, 503); `test_publisher.py::test_network_errors_are_transient`, `::test_other_statuses_are_transient` |
| CA-05 | `publish_loop.py` (`delay_s`) | `test_publish_loop.py::test_backoff_doubles_with_jitter_and_caps_at_60` (até `attempts=10`), `::test_delay_s_formula` |
| CA-06 | `publish_loop.py` (bissecção), `outbox.py` (`mark_dead`) | `test_publish_loop.py::test_bisection_isolates_the_rejected_item`; API real: `test_publisher_real_api.py::test_loop_isolates_the_value_the_database_refuses` |
| CA-07 | `publish_loop.py` (`auth_error`), `app.py` + `templates/console.html` (`data-connectivity`) | `test_publish_loop.py::test_auth_error_pauses_publishing[401/403]`, `::test_no_health_check_in_auth_error`; `test_pages.py::test_console_connectivity_label_and_code[auth_error]`; `test_publisher_real_api.py::test_unknown_key_is_an_auth_error` |
| CA-08 | `publish_loop.py`, `outbox.py` | `test_publish_loop.py::test_outage_and_lost_response_deliver_exactly_once` (200 itens, queda de T+30 a T+150 s, uma resposta perdida) |
| CA-09 | `outbox.py` (WAL + `synchronous=FULL` + commit no `put`) | `test_outbox.py::test_committed_puts_survive_sigkill` (processo filho com `SIGKILL`; roda `python -c`, nunca pytest) |
| CA-10 | `publisher.py` (`content=` JSON e `Content-Type: application/json`; só `BATCH_PATH` e `HEALTH_PATH`) | `test_publisher.py::test_publish_batch_request_and_results`, `::test_check_health`; `test_static_rules.py::test_no_http_client_outside_the_publisher` (já existente) |
| CA-11 | `config.py` (`check_cloud_api_url`, validador de `CLOUD_API_URL`) | `edge/tests/test_cli_cloud.py::test_invalid_cloud_url_exits_2`, `::test_loop_with_key_and_local_url`, `::test_check_cloud_api_url_accepts`, `::test_check_cloud_api_url_refuses` |
| CA-12 | `cli.py` (`_build_sink`) | `test_cli_cloud.py::test_default_outbox_path_and_disabled_without_key_or_url` (sem a flag e com modelo fictício em `MODEL_DIR`; sem chave, e com a chave sem URL: 3 capturas → 3 linhas `pending` em `EDGE_DATA_DIR/outbox.sqlite3`, `disabled`), `::test_no_loop_without_key_and_url` |
| CA-13 | `publish_loop.py` (`_maybe_check_health`) | `test_publish_loop.py::test_health_check_when_idle` (200, 503 e erro de rede), `::test_a_publish_attempt_counts_as_contact` |
| CA-14 | `publish_loop.py` (`start`/`stop`, join de 10 s) | `test_publish_loop.py::test_app_lifespan_starts_and_stops_the_thread`, `::test_thread_publishes_and_stops` (`PRAGMA integrity_check` = `ok`) |
| CA-15 | `outbox.py` (lock único) | `test_publish_loop.py::test_concurrent_puts_while_the_loop_publishes`, `test_outbox.py::test_concurrent_puts_and_publication` |
| CA-16 | — | `uv run pytest edge/tests --cov=qc_edge.outbox`: **97%** (só os testes do autor; `publisher.py` 100%, `publish_loop.py` 97%) |
| CA-17 (manual) | `edge/README.md`, seção "Demo offline" | — (roteiro para a dupla) |
| CA-19 | `cli.py` (`_build_sink`: `InMemorySink()` e `WARNING` com `--stub-model`) | `test_cli_cloud.py::test_stub_model_uses_memory_and_never_publishes` (itens 1 a 6: 2 linhas prévias intactas, 3 capturas `stub-v0` só na memória, `pending=3`, `disabled`, aviso, chave fora do log, e depois só os 2 ids originais chegam à nuvem), `::test_stub_model_never_creates_outbox_path` (pasta inexistente continua inexistente), `::test_stub_model_still_validates_url_and_key`, `::test_stub_model_ignores_an_unopenable_outbox_path` |
| CA-18 | `publisher.py` (`refusal_summary`), `publish_loop.py` (log só com status, resumo e tamanho do lote) | `test_publish_loop.py::test_rejection_logs_only_the_summary` (caso a, marcador nos `input`, `caplog` em DEBUG), `::test_bisection_isolates_the_rejected_item` (caso b); `test_publisher.py::test_refusal_summary`, `::test_refusal_summary_cuts_and_replaces_control_characters`, `::test_rejections_carry_only_the_summary` |

## Retomada após o SPEC_ISSUE-01

O architect corrigiu a SPEC com a opção (d) (commit `47c4223`, reaprovado pelo humano). A SPEC voltou a `In Dev`, ainda na r1. O que mudou no código:

- **`cli._build_sink` (§3.1, §4.3 e §4.4 novas):**
  - com `--stub-model`, devolve `InMemorySink()` e nenhum `BackgroundService`, com ou sem chave e URL, e nunca chama o `SqliteOutbox`: `OUTBOX_PATH` não é aberto, criado nem validado. Um `OUTBOX_PATH` que é um diretório ou cuja pasta não existe não dá erro nem cria nada;
  - a subida registra o `WARNING` `--stub-model: inspections are kept only in memory and are never written to the outbox nor sent to the cloud`, sem valor de variável. O aviso antigo do stub (`stub model enabled: ...`) continua;
  - sem a flag, nada mudou: outbox em `OUTBOX_PATH` e laço só com chave e URL.
- **Validação igual com e sem a flag (§4.4, CA-11):** `CLOUD_API_URL` já era validada pelo `EdgeSettings` em qualquer modo. A conferência de `DEVICE_API_KEY` (ASCII visível) agora roda sempre que a variável está definida, antes da escolha do sink, e não só quando chave e URL estão definidas sem a flag. Consequência: uma chave inválida também dá código 2 no modo stub e na subida sem URL.
- **Testes do autor (`edge/tests/test_cli_cloud.py`):**
  - CA-12 reescrito sem a flag, com o modelo fictício do `dummy_model` em `MODEL_DIR`;
  - `test_outbox_survives_a_restart` passou a usar o modelo fictício;
  - novos `test_stub_model_uses_memory_and_never_publishes` (CA-19, itens 1 a 6), `test_stub_model_never_creates_outbox_path` (o caso da pasta inexistente do CA-19), `test_stub_model_still_validates_url_and_key` e `test_stub_model_ignores_an_unopenable_outbox_path`;
  - o antigo `test_stub_model_never_publishes_even_with_key_and_url` foi incorporado ao teste do CA-19.
- **`edge/README.md` e `.env.example` (§7):** saiu a orientação de usar outro `OUTBOX_PATH` com o stub. Agora está dito que, com a flag, nada vai para o outbox nem para a nuvem. O README inclui a tabela da §4.4 e a nota para apagar um `outbox.sqlite3` criado com `--stub-model` pelo build anterior da r1.
- Nenhum teste de aceite de SPEC anterior foi afetado: os da SPEC-007 e da SPEC-025 que sobem `qc-edge --stub-model` voltam a ter o `InMemorySink` da SPEC-007.

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest -q edge/tests --cov=qc_edge.outbox          # CA-16
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Resultado nesta rodada:

- `ruff check` e `ruff format --check`: limpos.
- Suíte inteira com `CI=true` e `TEST_DATABASE_URL` (contêiner `partqc-pg`), depois da retomada após o SPEC_ISSUE-01: **4333 passed, 1 skipped** em 4 min 04 s. O skip é o CA-16 manual da SPEC-008, sem `QC_REAL_MODEL_DIR`. Antes da retomada: 4329 passed, 1 skipped.
- Nenhum teste de aceite de SPEC anterior falhou.

## Decisões tomadas dentro do escopo da SPEC

- **`OutboxItem`** (a SPEC não lista os campos): `inspection_id`, `payload`, `created_at`, `attempts`, `next_attempt_at` e `to_inspection()`, que valida o payload de novo pelo contrato. Um payload que não valida mais vira `dead` com `invalid payload (<n> validation errors)`, porque a API o recusaria com 422 do mesmo jeito.
- **Desempate do `fetch_due`:** `ORDER BY created_at, rowid`, o que garante a ordem de inserção quando o relógio não avança (CA-02 com relógio parado).
- **"Último contato" para o health check:** é qualquer requisição à nuvem, inclusive um envio que falhou. Na construção, o laço toma o instante atual como último contato: com o relógio falso, a primeira consulta de saúde só sai depois de 60 s (CA-13). `start()` zera esse instante, então a thread real consulta a nuvem logo no primeiro ciclo ocioso e o console sai do estado inicial sem esperar 60 s.
- **Estado inicial com laço:** se o `ConnectivityState` recebido estiver em `disabled`, o `PublishLoop` o muda para `offline` (já existe um laço, e `online` só depois de um contato bem-sucedido). Sem laço, continua `disabled` (CA-12).
- **Falha transitória no meio da bissecção:** a outra metade não é tentada no mesmo ciclo, e todos os itens ainda não resolvidos do ciclo recebem `mark_retry`. Com a nuvem fora, isso evita uma sequência de timeouts de 5 s. Um 401/403 no meio deixa os itens restantes como estavam (sem incrementar `attempts`), e `stop()` no meio também.
- **`last_error` sem a chave (§4.1):** o outbox não conhece a chave e a assinatura da SPEC não a recebe. A garantia vem de quem escreve: o `HttpPublisher` troca a chave por `***` em toda mensagem que vem do `httpx`; a recusa usa só o resumo; o 401/403 usa só `HTTP <status>`; a exceção inesperada vai para `last_error` só pelo nome da classe (`unexpected error: RuntimeError`). Os testes conferem que a chave não aparece no log nem nas linhas.
- **Validação extra da configuração** (as duas dão código 2 e a mensagem cita só o nome da variável):
  - `CLOUD_API_URL` com usuário/senha, query, fragmento, porta inválida ou espaço é recusada. Credencial na URL seria segredo numa variável que não é tratada como segredo, e query ou fragmento impediriam montar a rota. A barra final é removida;
  - `DEVICE_API_KEY` precisa ser ASCII visível (`0x21` a `0x7E`). Um valor diferente nunca autentica, e o erro de codificação do header poderia citar a chave. As chaves do `register_device.py` (`token_urlsafe`) passam.
- **Arquivo do outbox:** pastas que faltam são criadas com `0700` e o arquivo novo com `0600`, pelos utilitários do `fsutil` (SPEC-025). O SQLite dá aos arquivos `-wal`/`-shm` o mesmo modo do banco.
- **Outbox não é fechado no desligamento do app.** Testes de aceite já existentes (ex.: `test_spec_008.py::test_ca18_console_and_status_show_model_and_thresholds`) usam o app depois do fim do lifespan, e um `close()` ali derrubava o console com 500. O laço para no lifespan (CA-14). A conexão fica aberta até o processo terminar, e nada se perde, porque cada `put` já foi confirmado.
- **Resposta 2xx:** qualquer 2xx com `BatchResult` válido conta como sucesso (a API responde 200; a nuvem falsa dos testes pode responder 201). Um 3xx não é seguido (`follow_redirects=False`) e conta como transitório.
- **Teste contra a API real** (`edge/tests/test_publisher_real_api.py`, marcador `db`): o app `qc_api` roda no processo, pelo transporte do `TestClient`, sobre o banco de teste. O teste confere `created`/`duplicate`, o 401 e a bissecção isolando um 422 real `Value cannot be stored` (underflow de coluna `real` com `type_confidence=1e-50`). Ele nunca usa o Supabase. Sem `TEST_DATABASE_URL`, é pulado.
- **Console:** o rótulo continua em PT-BR (ADR-012). O código (`online`, `offline`, `auth_error`, `disabled`) fica em `data-connectivity`, e os campos ganharam `id`s (`sink-dead`, `sink-connectivity`, `sink-last-success`).

## SPEC_ISSUE (se houver)

**SPEC_ISSUE-01 — resolvido** pelo architect com a opção (d) (commit `47c4223`, SPEC reaprovada pelo humano). A implementação foi ajustada (seção "Retomada após o SPEC_ISSUE-01"). O registro original fica abaixo, para histórico.

> `--stub-model` gravava no mesmo outbox durável da operação, e os resultados falsos (`stub-v0`, `source=live`) podiam subir como `live` numa subida seguinte com chave e URL (R-06). A r1 original seguia literalmente a §3.1 da época (`sink = SqliteOutbox(OUTBOX_PATH)` sempre) e o CA-12 ("o outbox tem 3 pendentes" também com `--stub-model`). As opções propostas foram: (a) arquivo próprio para o stub, (b) recusar a subida, (c) descartar `stub-v0` no laço, (d) `InMemorySink` no modo stub.

Nenhum SPEC_ISSUE aberto.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando: 151 novos em `edge/tests/` (`test_outbox.py`, `test_publisher.py`, `test_publish_loop.py`, `test_cli_cloud.py`, `test_publisher_real_api.py` e 4 casos em `test_pages.py`)
- [x] `.env.example` atualizado: comentários de `DEVICE_API_KEY`, `CLOUD_API_URL` e `OUTBOX_PATH`. Nenhuma variável nova, nenhum valor secreto
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim; nada em `ml/**`
- [x] Sem dependência nova (`httpx` já era dependência do `qc-edge`; `sqlite3` é da biblioteca padrão); `uv.lock` intacto
- [x] Nenhuma credencial literal: as chaves dos testes são geradas em tempo de execução (`secrets.token_urlsafe`), e nenhuma URL ou header leva credencial fixa
- [x] Nenhum teste roda o pytest em subprocesso (o CA-09 usa `python -c` com um script de 15 linhas)
- [x] Só o JSON do contrato sai da borda; nenhum caminho de imagem chega ao outbox ou ao publisher (R-02)
