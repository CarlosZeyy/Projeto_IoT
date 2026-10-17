# SPEC-005 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-005](../../docs/specs/SPEC-005-api-leitura-metricas.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `efff370` (código de produção do developer; testes do tester em `0fec76e` e no commit deste relatório) |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir da SPEC (caixa-preta) antes da leitura da implementação. Depois a implementação foi lida para guiar os testes exploratórios.

## Ajuste autorizado em `test_spec_004.py` (§3.1, SPEC_ISSUE-01)

Commit próprio `0fec76e` (`test: use PUT and DELETE for the 405 check in the SPEC-004 extra test`). Em `api/tests/acceptance/test_spec_004.py::test_extra_wrong_methods_and_unknown_route`, a 1ª asserção (`GET` com a chave do dispositivo → 405) foi trocada por duas: `PUT` e `DELETE` em `/api/v1/inspections`, com os mesmos headers, cada uma → 405. Nenhuma outra linha do arquivo mudou (`git show --stat 0fec76e`: 2 inserções, 1 remoção). O 401 do `GET` com a chave de dispositivo fica coberto pelo CA-01 de `test_spec_005.py`.

## Cobertura dos critérios de aceite

Arquivo: `api/tests/acceptance/test_spec_005.py`. Os CAs são marcados `db`, exceto o CA-17 (app sem banco), o CA-19 e o CA-21.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_read_routes_reject_missing_wrong_and_device_keys` | ✅ |
| CA-02 | `test_ca02_first_page_order_and_items` | ✅ |
| CA-03 | `test_ca03_offset_pages_and_offset_past_total` | ✅ |
| CA-04 | `test_ca04_invalid_parameters_are_422` | ✅ |
| CA-05 | `test_ca05_listing_filters` | ✅ |
| CA-06 | `test_ca06_summary_without_filters` | ✅ |
| CA-07 | `test_ca07_summary_filtered_by_source_and_lot` | ✅ |
| CA-08 | `test_ca08_summary_without_rows` | ✅ |
| CA-09 | `test_ca09_summary_only_unknown_has_null_rate` | ✅ |
| CA-10 | `test_ca10_timeseries_hour_day_minute` | ✅ |
| CA-11 | `test_ca11_day_bucket_is_utc_not_local` (+ `test_extra_buckets_are_utc_whatever_the_session_timezone`) | ✅ |
| CA-12 | `test_ca12_invalid_bucket_and_injection_attempt` | ✅ |
| CA-13 | `test_ca13_more_than_5000_buckets_is_422` | ✅ |
| CA-14 | `test_ca14_lots_listing` | ✅ |
| CA-15 | `test_ca15_lot_with_two_sources` | ✅ |
| CA-16 | `test_ca16_lots_pagination` | ✅ |
| CA-17 | `test_ca17_database_unavailable_is_503` | ✅ |
| CA-18 | `test_ca18_unknown_query_parameters_are_ignored` | ✅ |
| CA-19 | `test_ca19_sql_is_never_formatted_as_a_python_string` | ✅ |
| CA-20 | `test_ca20_integrity_error_is_422_without_values_in_log` | ✅ |
| CA-21 | `test_ca21_generic_500_hides_database_messages` | ✅ |

Notas sobre como cada CA foi verificado:

- **Conjunto D:** inserido por SQL direto (`insert ... values` com parâmetros), com `edge-01` e `sim-01` registrados por hash. Cada linha recebe um `inspection_id` v4 novo, e as asserções de ordem comparam os IDs das linhas #N. Os floats usam `pytest.approx(rel=1e-6)`.
- **CA-01:** as 4 rotas, cada uma com: sem header, `errada`, uma chave aleatória e a chave de `edge-01` → 401 com o corpo exato. A chave `R` na mesma rota → 200 (controle).
- **CA-02:** valida o corpo como `Page[InspectionRead]` e cada item como `InspectionRead`.
- **CA-11:** o teste do CA usa o app padrão. Como o Postgres do Docker roda em UTC, um `date_trunc` sem o fuso `'UTC'` também passaria nele. Por isso o teste extra repete o caso com a sessão da API em `America/Sao_Paulo`, `Pacific/Kiritimati` (+14) e `Asia/Kathmandu` (+05:45), via `make_conninfo(..., options="-c TimeZone=...")`. O bucket continua `2026-10-02T00:00:00Z`.
- **CA-13:** 5 001 linhas inseridas com `generate_series` e `gen_random_uuid()`, em minutos distintos. `minute` → 422 com o corpo exato; `day` → 200, com a soma de `total` = 5 001.
- **CA-17:** app com `DATABASE_URL` numa porta local fechada. A senha fictícia é gerada em tempo de execução. As 4 rotas → 503 `Database unavailable`, cerca de 5 s por rota (o timeout do pool da SPEC-004).
- **CA-19:** varredura AST de todo `api/src/qc_api/**/*.py`. Conta como ocorrência uma f-string com campo, um `%` ou um `.format` cujo texto (literal, nome ligado a literal no módulo ou concatenação com `+`) contenha `select`, `where` ou `insert`, sem diferenciar maiúsculas. `sql.SQL(...).format(...)` não conta. O próprio teste confere o scanner com uma sonda: ele marca as 3 formas proibidas e aceita as 2 formas com `psycopg.sql`, o que prova que o teste não é vazio. Nenhuma ocorrência no código.
- **CA-20:** a restrição `ca20_marker` é real. Ela é criada numa fixture e removida no `finally` (antes também roda um `drop ... if exists`). App com `LOG_LEVEL=DEBUG` e `caplog` em DEBUG. Resultado: o single e o batch respondem 422 com o corpo exato; a tabela fica com 0 linhas; `last_seen_at` continua nulo; há um registro com `sqlstate=23514`; `L-INTEG-MARK` não aparece em nenhum registro (texto, args, `exc_text`) nem nas respostas.
- **CA-21:** as 3 rotas são acrescentadas com `app.add_api_route` no app real (sem banco), e as chamadas usam `TestClient(app, raise_server_exceptions=False)`. Os marcadores são aleatórios. Nos casos 1 e 2: há um `ERROR` com `sqlstate=42P01` / `sqlstate=23514`; os marcadores não aparecem; nenhum registro tem `exc_info`. No caso 3, há um registro com `exc_info`.

## Suíte completa

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
103 files already formatted

$ uv run pytest -q                    # sem TEST_DATABASE_URL
1261 passed, 443 skipped, 1 warning in 192.45s

$ TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
execução 1: 1 failed, 1703 passed   (falha intermitente da SPEC-004, ver OBS-03)
execução 2: 1704 passed, 1 warning in 245.62s
execução 3: 1704 passed, 1 warning in 233.46s

$ ... uv run pytest -q api/tests/acceptance/test_spec_005.py
com banco: 63 passed; sem banco: 4 passed, 59 skipped
```

Testes de aceite desta SPEC: 63, sendo 21 de CA e 42 exploratórios (`test_extra_*`, contando as parametrizações). Nenhum teste roda o pytest em subprocesso. Nenhuma credencial ou chave fictícia aparece como literal em URL, conninfo ou header: a senha da URL sem banco é gerada em tempo de execução (`urlunsplit`), o `errada` do CA-01 é montado em tempo de execução, e as chaves dos dispositivos vêm de `secrets.token_urlsafe`.

## Bugs encontrados

Nenhum bug contra os critérios de aceite. Há uma observação de robustez, fora dos CAs, para o reviewer e o architect decidirem:

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| OBS-01 | baixa (fora dos CAs; não alcançável pela API) | §4.3 (listagem), "Erros de banco no log" (espírito) | 1. Inserir por SQL direto (SQL Editor ou migração) uma linha válida para o banco, mas fora do contrato: `inspection_id` UUID v1 (`uuid.uuid1()`) e/ou `model_version='MODEL_X'`. O banco não tem `check` para a versão do UUID nem para a regex de `model_version`. 2. `GET /api/v1/inspections` com `R`. | A SPEC não define. O esperado seria a listagem continuar respondendo (ou uma regra explícita). | 500 `Internal server error` em toda página que contém a linha, porque `InspectionRead.model_validate(row)` falha em `repositories/inspections.py`. O `logger.exception` registra o `ValidationError` do pydantic com `input_value=UUID('...')` e `input_value='MODEL_X'`, ou seja, valores da linha no traceback (não é `psycopg.Error`, então a regra de §4 não se aplica literalmente). `summary`, `timeseries` e `lots` respondem 200. Pela API a linha nunca entra, porque o contrato valida na escrita. Sugestão: um `check` para `model_version` no banco (SPEC-003) ou uma decisão explícita na SPEC. |

## Testes exploratórios (além dos critérios)

Todos estão automatizados em `test_spec_005.py` (`test_extra_*`) e passam, exceto quando o texto indica que foram sondas manuais.

- **Chaves:** a chave de leitura em `POST /inspections` e `/batch` → 401, nada gravado. Nas 4 rotas → 401: chave vazia, com espaço antes ou depois, em maiúsculas, um caractere a menos ou a mais, chave de `sim-01` e o hash SHA-256 da chave de `edge-01`. O nome do header não diferencia maiúsculas. Sem chave e com parâmetros inválidos → 401 (a auth vem antes da validação).
- **Paginação:** `offset` = 9, 10⁶, 2³¹, 2⁶³−1, 2⁶³, 2⁶⁴ e 10⁴⁰ em `/inspections` e `/lots` → 200, `items=[]`, `total` correto, `offset` ecoado (sem 500 de `bigint`). `limit=abc|1.5|-5|vazio`, `offset=1e3|x` → 422. Padrão `limit=50`, `offset=0`. `limit` repetido (`500&501`) → 422 (vale o último). Ordem estável com 6 linhas no mesmo `inspected_at`: as páginas de 2 em 2 seguem `inspection_id asc`, sem repetir nem pular. Lotes que empatam em `started_at` saem por `lot_id asc`.
- **Datas e fusos:** `from` é inclusivo e `to` exclusivo, conferidos no microssegundo. A mesma janela escrita em `-03:00` e em `+14:00` dá o mesmo resultado. → 422 nas 4 rotas: `from == to`, data sem hora, `yesterday`, mês 13, `+25:00`, `0001-01-01T00:00:00+14:00` e `9999-12-31T23:59:59-14:00` (estes dois saem da faixa do `datetime` ao normalizar para UTC; não há 500). `0001-01-01Z` a `9999-12-31Z` → 200. Sonda manual: `+` sem codificar na URL vira espaço → 422; nanossegundos → 200.
- **Filtros:** injeção e unicode em `lot_id`/`device_id` (`' or '1'='1`, `L-ção`, 41 caracteres, vazio, `\n` final, `%00`), enums em maiúsculas e `defective=maybe` → 422 nas 4 rotas, com a tabela intacta. IDs no tamanho máximo (40 e 32) → 200. `defective=false` → 5. A soma por `grade` = 7, porque a linha `unknown` fica fora. Filtros combinados com `AND` na listagem e nos lotes (`device_id`, `defective`).
- **Agregações:** o banco vazio dá listas vazias, `[]` na série e `defect_rate=null`. Um bucket só com `unknown` dá `defect_rate=null`. A soma de `total`/`defective` da série (minute, hour e day) bate com o resumo para 4 combinações de filtros. As médias são `float` finitos e as contagens são `int`. Cada item da listagem ecoa os valores gravados em D, e `is_defective` = `grade in (poor, unusable)`. `unknown` aparece na listagem com `grade=null` e `is_defective=false`.
- **R-06:** `source` aparece em cada item. Os lotes trazem `sources` na ordem do enum. Sem `source`, o resumo soma as duas origens; com `source=live`, só `live`.
- **Buckets:** exatamente 5 000 → 200 com 5 000 pontos. Com 6 000 linhas → 422, mas com `from`/`to` estreitando a 100 minutos → 200 com 100 pontos, e com `hour` → 200. `bucket` = `Hour`, `HOUR`, `' hour'`, `'hour '`, vazio, `hours`, `second`, `month` ou `'hour'` → 422. Sem `bucket`, o resultado é igual a `hour`.
- **Erros de banco no log:** com um erro real na leitura (tabela `inspections` renomeada durante o teste e restaurada no `finally`), `/metrics/summary` → 500 com o corpo genérico. Há uma única linha `ERROR` exatamente `unhandled database error: route=/api/v1/metrics/summary type=UndefinedTable sqlstate=42P01`, sem `exc_info` e sem `does not exist`. Formato da linha (§4.5 item 2): `psycopg.Error` sem SQLSTATE → `type=Error sqlstate=-`; `UniqueViolation` só no `__context__` (relançada com `from None`) → `type=UniqueViolation sqlstate=23505`; uma rota com parâmetro registra o template (`route=/x/items/{item_id}`).
- **IntegrityError no `update devices`** (§4.5 item 1): com uma restrição real em `devices` que recusa qualquer `last_seen_at`, o single e o batch → 422 `Value cannot be stored`. Nenhuma linha é gravada, `last_seen_at` continua nulo, o log tem `sqlstate=23514`, e nem o `lot_id`, nem o nome da restrição, nem `Failing row` aparecem no log. Controle do CA-20: com `ca20_marker` ativa, um payload comum → 201.
- **Outros:** `POST`/`PUT`/`DELETE` em `/metrics/*` e `/lots` → 405. As leituras não alteram `devices.last_seen_at` nem a tabela.
- **Sonda manual (OBS-02, informativo):** `from=1700000000`, `to=0` e `from=-1` (Unix timestamp) são aceitos como datetimes UTC (modo lax do pydantic, o mesmo do contrato, SPEC-023 §4.4). A SPEC só exige 422 para datetime sem fuso, o que é respeitado. Não é bug; fica o registro para a SPEC-013.
- **OBS-03 (intermitente, fora desta SPEC):** na 1ª execução completa com banco, `api/tests/acceptance/test_spec_004.py::test_extra_r2_real_server_unencodable_bodies_are_422_and_not_logged` falhou uma vez. É o teste que sobe um uvicorn real numa porta livre. Ele não falhou de novo em 2 execuções completas nem em 6 execuções isoladas. O traceback não foi capturado (a saída era `-q`). Suspeita de corrida de porta ou de tempo sob carga. Fica o registro para o reviewer e o CI.
- **OBS-04 (informativo):** o 503 com o banco fora leva cerca de 5 s por requisição (o timeout do pool da SPEC-004), então o CA-17 leva cerca de 20 s.

## SPEC_ISSUE (se houver)

Nenhum. O SPEC_ISSUE-01 da r1 (dev-report) já foi resolvido pela §3.1, e o ajuste foi aplicado no commit `0fec76e`.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` (`test_spec_005.py`, novo, e a asserção autorizada de `test_spec_004.py`) e este relatório.
