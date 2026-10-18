# SPEC-009 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-009](../../docs/specs/SPEC-009-edge-outbox-publisher.md) |
| Rodada | r1 (retomada após o SPEC_ISSUE-01; SPEC com o CA-12 ajustado e o CA-19 novo) |
| Tester | tester |
| Commit testado | `333277c` |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir da SPEC (caixa-preta) antes da leitura da implementação. Depois, li `outbox.py`, `publisher.py`, `publish_loop.py`, `cli.py` e `config.py` para os testes exploratórios. Arquivo: `edge/tests/acceptance/test_spec_009.py`, com **94 testes** (28 de CA e 66 extras, contando os casos parametrizados).

Fronteiras substituídas, só as que a SPEC cita:

- a rede da nuvem: `httpx.MockTransport` com uma nuvem falsa que implementa a idempotência da SPEC-004 (um `dict` por `inspection_id`, `created`/`duplicate`, lote recusado inteiro, sem gravar nada). Onde a SPEC põe `CLOUD_API_URL=http://127.0.0.1:<porta>` (CA-12, CA-19), um servidor HTTP local de verdade registra toda requisição que chega;
- o relógio (`ManualClock`) e o RNG (`random.Random(0)`);
- `uvicorn.run`, por um espião que roda o cenário com o lifespan do app (`TestClient`) e devolve as exceções do cenário depois que o `main` retorna;
- o socket da LAN (`detect_lan_ips`).

O SQLite é real, em `tmp_path`. As chaves e tokens são gerados em tempo de execução, e o modelo ONNX fictício (CA-12 e um extra) é montado no próprio arquivo com `onnx.helper`. Nenhum teste usa o banco nem a internet. O CA-09 roda um script `python` curto, e o CA-16 roda o pytest em dois arquivos explícitos, sem si mesmo (`-k "not test_ca16"`, `architecture.md` §10).

## Cobertura dos critérios de aceite

Arquivo: `edge/tests/acceptance/test_spec_009.py`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_put_is_idempotent_by_inspection_id` | ✅ |
| CA-02 | `test_ca02_150_items_go_in_two_batches_in_created_at_order` (`created_at` embaralhado em relação à ordem de inserção) | ✅ |
| CA-03 | `test_ca03_duplicate_answers_also_mark_items_sent` | ✅ |
| CA-04 | `test_ca04_transient_failure_schedules_a_retry[connect, timeout, 503]` | ✅ |
| CA-05 | `test_ca05_backoff_doubles_with_20_percent_jitter_capped_at_60` (até `attempts=10`) | ✅ |
| CA-06 | `test_ca06_bisection_isolates_the_rejected_item` | ✅ |
| CA-07 | `test_ca07_auth_error_pauses_publishing[401, 403]` (`/api/status`, console, chave fora do log e de `last_error`, um único log de erro com `DEVICE_API_KEY`) | ✅ |
| CA-08 | `test_ca08_outage_and_lost_response_deliver_exactly_once` | ✅ |
| CA-09 | `test_ca09_committed_puts_survive_sigkill` | ✅ |
| CA-10 | `test_ca10_only_contract_json_goes_to_the_two_cloud_routes` | ✅ |
| CA-11 | `test_ca11_plain_http_cloud_url_is_refused`, `test_ca11_loopback_http_cloud_url_starts` | ✅ |
| CA-12 | `test_ca12_without_key_or_url_the_outbox_fills_and_nothing_is_sent[DEVICE_API_KEY, CLOUD_API_URL]` | ✅ |
| CA-13 | `test_ca13_idle_health_check_after_61_seconds[200, 503, connect, timeout]` | ✅ |
| CA-14 | `test_ca14_lifespan_stops_the_thread_and_keeps_sqlite_consistent` | ✅ |
| CA-15 | `test_ca15_concurrent_puts_while_run_once` | ✅ |
| CA-16 | `test_ca16_outbox_coverage_is_at_least_80_percent` | ✅ |
| CA-17 (manual) | — roteiro em `edge/README.md` ("Demo offline"); a dupla executa e registra | ⏳ manual, pendente da dupla |
| CA-18 | `test_ca18_refusal_body_never_reaches_logs_or_last_error[fastapi-default, string-detail]` | ✅ |
| CA-19 | `test_ca19_stub_model_keeps_inspections_in_memory_only` (itens 1 a 6), `test_ca19_stub_model_never_creates_outbox_path` (pasta inexistente) | ✅ |

Notas sobre a forma dos testes:

- **CA-07:** o "console mostra `auth_error`" foi conferido pelo texto `auth_error` no HTML do console (requisição de loopback com `Host` `127.0.0.1:8000`). O rótulo visível é em PT-BR (ADR-012), e o código aparece no atributo `data-connectivity`.
- **CA-08:** 200 `put` (1 por segundo de relógio), `run_once` a cada 2 s, queda de conexão em [T+30 s, T+150 s) e uma resposta perdida na primeira requisição de lote depois da volta. O teste confere que a queda recusou requisições, que a resposta perdida aconteceu (houve `duplicate`), que a nuvem tem 200 ids únicos e 200 gravações e que nenhum item ficou `dead`. Tempo real: menos de 0,5 s (limite do CA: 30 s).
- **CA-12 e CA-19:** a ausência de requisições é conferida de dois jeitos: o servidor local apontado por `CLOUD_API_URL` não recebeu nada, e nenhum `PublishLoop` foi construído (espião no construtor, que continua chamando o original).
- **CA-16:** `pytest --cov=qc_edge.outbox` em `edge/tests/test_outbox.py` e neste arquivo dá **99%** (total do módulo). Só com os testes de aceite: `outbox.py` 93%, `publisher.py` 96%, `publish_loop.py` 91%.

## Suíte completa

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
SKIPPED [1] edge/tests/acceptance/test_spec_008.py:765: QC_REAL_MODEL_DIR not set (manual CA-16, real model of SPEC-012)
4427 passed, 1 skipped, 1 warning in 268.29s (0:04:28)

$ uv run pytest -q edge/tests/acceptance/test_spec_009.py
94 passed, 1 warning in 17.50s (inclui o subprocesso de cobertura do CA-16)

$ pytest --cov=qc_edge.outbox edge/tests/test_outbox.py edge/tests/acceptance/test_spec_009.py -k "not test_ca16"   (CA-16)
TOTAL 133 statements, 1 missed, 99%
só os testes de aceite: outbox.py 93%, publisher.py 96%, publish_loop.py 91%

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
166 files already formatted
```

O skip é o CA-16 manual da SPEC-008 (sem `QC_REAL_MODEL_DIR`), o mesmo do dev-report. O aviso é a `StarletteDeprecationWarning` do `TestClient`, que já existia. A suíte do autor tinha 4333 testes; 4333 + 94 = 4427.

## Ajustes em testes de aceite de SPECs anteriores

Nenhum. Os testes de aceite das SPECs 007, 008, 010 e 025 passam sem mudança.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | baixa | fora dos CAs (relacionado ao CA-14 e à RNF-10) | 1. Servidor em `127.0.0.1:<porta>` que responde ao `POST` do lote com `HTTP/1.1 200`, `Content-Length: 100000` e envia 1 byte do corpo a cada 3 s. 2. `SqliteOutbox` com 1 item, `PublishLoop(..., HttpPublisher("http://127.0.0.1:<porta>", chave), interval_s=0.1)`, `start()`, espera 1 s. 3. `stop()`. | A thread do publisher encerra em ≤ 10 s, e uma requisição nunca dura muito mais que o `timeout_s` de 5 s. | `stop()` volta depois de 10,0 s com o aviso `publisher thread did not stop within 10 s`, e a thread `qc-edge-publisher` continua viva. O `timeout_s=5.0` do `httpx` vale por operação de leitura, e não para a requisição inteira, então um servidor que goteja bytes prende a requisição sem limite. Enquanto isso, nada mais é publicado. A thread é daemon e o processo termina mesmo assim. Só acontece com uma nuvem quebrada ou hostil atrás de `CLOUD_API_URL`, que é `https://` para a nossa API: por isso a severidade é baixa. Com um servidor que não responde nada, o timeout de leitura de 5 s funciona, e o `stop()` termina antes de 10 s. |

Nenhum bug nos critérios de aceite.

## Testes exploratórios (além dos critérios)

Todos automatizados em `test_spec_009.py` (`test_extra_*`) e passando, salvo indicação.

**Segurança: chave, corpo do 422 e logs**

- A chave nunca chega a `last_error` nem ao log, mesmo quando a mensagem de erro do transporte a contém (`ConnectError` com `X-API-Key=<chave>` e 900 caracteres a mais). O `last_error` fica com ≤ 500 caracteres.
- `PublishRejectedError` do 422 padrão do FastAPI: o marcador que vem nos `input` não aparece em `str`, `repr`, `args`, `__dict__`, `__cause__` nem `__context__` da exceção.
- Resumo da recusa: 413 com `detail` em texto, 413 com HTML, 422 com corpo que não é JSON, JSON sem `detail`, `detail` numérico, `detail: []` e corpo JSON que é uma lista. Todos seguem a §4.2.
- O `detail` é cortado em 200 caracteres, e os caracteres de controle (`\x00`, `\x1b`, `\n`, `\r`, `\t`, `\x7f` e o C1 `\x85`) viram `?`. Unicode comum (`á`, `✓`) é mantido.
- Um redirecionamento 307 para outro host não é seguido (isso levaria o `X-API-Key` para lá): há uma única requisição, ao host original, e ela conta como falha transitória.
- O `GET /api/v1/health` sai **sem** o `X-API-Key`. O `POST` do lote sai com ele.

**Validação de `CLOUD_API_URL`**

- Aceitas: `https://api.exemplo.org`, `https://…/` (a barra final é removida, e as rotas saem sem `//`), `http://localhost:9000` e `http://127.0.0.1`.
- Recusadas com código 2 citando `CLOUD_API_URL`, **com e sem** `--stub-model` (§4.4): `http://localhost.exemplo.org`, `http://127.0.0.1.exemplo.org`, `http://exemplo.org/127.0.0.1`, `http://192.168.0.10:8001`, `http://127.0.0.2:9000`, `ftp://…`, URL sem esquema, `https://` sem host, URL com usuário e senha e URL com query.
- A senha de uma URL com credencial nunca é repetida no log nem no stderr.
- `CLOUD_API_URL` vazia equivale a não definida: o `qc-edge` sobe sem laço, como diz o `.env.example`.
- Lidos no código: `@`, `\`, `;`, `#`, `?`, espaço e caracteres de controle no `netloc` caem na recusa de credencial, query/fragmento ou controle. Não achei uma URL em que o host visto pelo `urlsplit` seja de loopback e o host usado pelo `httpx` não seja.

**Idempotência (R-05) e R-06**

- Um `put` repetido com o mesmo `inspection_id` e payload diferente não altera a linha, nem antes nem depois de `sent`. Um item `sent` nunca é reenviado.
- Uma resposta 200 que não bate com o lote (ids invertidos, faltando ou trocados, status desconhecido, corpo que não é JSON, `{}`) é transitória: nenhum item vira `sent`.
- O `source` sai como foi gravado (`live` e `simulated`). A borda não o altera.
- `--stub-model` sem chave e sem URL também não cria `EDGE_DATA_DIR/outbox.sqlite3`. Com chave e URL, nem o `OUTBOX_PATH` nem o padrão são criados (CA-19).

**Laço e outbox**

- Schema, PK, índice `outbox_due (status, next_attempt_at, created_at)`, `journal_mode=wal`, datas de largura fixa com `+00:00` e `payload = model_dump_json()`: tudo conforme a §4.1.
- Dois itens recusados num lote de 100: 98 `sent` e 2 `dead`, com ≤ 40 requisições de lote.
- O estado `auth_error` mantém os itens novos em `pending` com `attempts=0` e não faz mais nenhuma requisição.
- Uma exceção inesperada do publisher não sai de `run_once`: o item recebe retry com `last_error`, e o log tem stack trace. Uma exceção no health check também não sai.
- O health check muda `offline` → `online`. `check_health` só é `True` com 200 (204 e 503 dão `False`).
- Status inesperados (400, 404, 405, 429, 500, 502 e 504) são transitórios.
- `put` depois de `close()` levanta `SinkError`.
- `/api/status` mostra `online`, `pending=0` e `last_success_at` depois de uma publicação.
- Um `OUTBOX_PATH` corrompido (arquivo que não é SQLite) impede a subida com código diferente de 0, sem chamar o `uvicorn`.

**Ponta a ponta (§4.4, primeira linha da tabela)**

- `qc-edge` sem a flag, com o modelo fictício, a chave e `CLOUD_API_URL` apontando para um servidor HTTP local real (com `/` no fim).
- As 3 capturas chegam ao servidor em até 8 s: só `POST` do lote com `X-API-Key` e `application/json`, itens com exatamente as chaves do contrato e `source=live`, e `GET` de health.
- O status fica `online` com `pending=0`, e as 3 linhas do outbox ficam `sent`. A chave não aparece no log.

**Observações (não são bugs; comportamento previsto pela SPEC)**

- **Recusa geral:** se a API recusar **todo** item com 422 (por exemplo, uma divergência de versão do contrato com `extra="forbid"`), a bissecção faz 199 requisições num único ciclo, e os 100 itens viram `dead`. Medido com a nuvem falsa. Como o reenvio de `dead` está fora do escopo (§3.2), esses itens só voltam a subir com uma SPEC futura. Fica registrado para o reviewer e para o security-devops.
- **Thread viva no T-01:** o `stop()` devolve o controle ao lifespan em 10 s mesmo com a thread presa, então o desligamento não trava.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
