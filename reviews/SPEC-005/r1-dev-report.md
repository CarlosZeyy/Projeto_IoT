# SPEC-005 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-005](../../docs/specs/SPEC-005-api-leitura-metricas.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-005-api-leitura-metricas` (empilhada sobre `docs/pendencias-pos-007`; diff desta SPEC: `docs/pendencias-pos-007...HEAD`) |
| Commits | `26d6377` (fix(api): hide database error messages from writes and the generic 500), `9819021` (feat(api): add read routes for inspections, metrics and lots), `0734c41` (test(api): cover read routes, filters and the bucket limit), mais o commit deste relatório |

## Resumo

- **Leitura (§4.1 a §4.4):** `GET /api/v1/inspections` (no mesmo router da escrita, com `require_read_key` na rota), `GET /api/v1/metrics/summary` e `/metrics/timeseries` (`routers/metrics.py`) e `GET /api/v1/lots` (`routers/lots.py`). Os dois routers novos têm `require_read_key` como dependência do router. As dependências da rota rodam antes dos parâmetros, então o 401 vem antes do 422.
- **Filtros (`filters.py`):** `InspectionFilters` e `Pagination` são dataclasses congeladas usadas como dependência (`Depends()`). As regexes (`DEVICE_ID_PATTERN`, `LOT_ID_PATTERN`) e o datetime com fuso normalizado para UTC (`UtcDatetime`) vêm de `qc_contracts`. A validação é do pydantic, que casa a string inteira (`edge-01\n` → 422, testado). `from >= to` levanta `RequestValidationError` (422 no formato padrão).
- **Consultas (`repositories/inspections.py`):** cada filtro é um fragmento fixo `sql.SQL("coluna = %(f_<nome>)s")`, juntado com `sql.SQL(" and ").join`. Todo valor, inclusive o `bucket`, o fuso `'UTC'` do `date_trunc`, `limit`/`offset` e o `'unknown'`, é parâmetro. Os textos SQL são `str` simples, compostos só na chamada com `sql.SQL(CONST).format(where=...)`. As agregações ficam no SQL (`count(*) filter`, `avg`, `group by`, `jsonb_object_agg`, `array_agg(distinct)`). A taxa de defeito é `defective / nullif(total − unknown, 0)`, então o resultado é `null` e nunca há erro de divisão.
- **Consistência:** cada leitura roda numa transação `repeatable read, read only`. A página e o `total` (e o resumo e as quebras) saem do mesmo snapshot.
- **Manutenção da SPEC-004 (§4.5):** a escrita trata `psycopg.IntegrityError` (classe 23) como o `DataError`: rollback, 422 `Value cannot be stored`, `WARNING` só com rota, `device_id` e `sqlstate=`. Quando o `UnhandledErrorMiddleware` encontra um `psycopg.Error` na exceção ou na cadeia `__cause__`/`__context__`, registra uma linha `ERROR` `unhandled database error: route=<rota> type=<classe> sqlstate=<código|->`, sem `exc_info` e sem a mensagem. As outras exceções continuam com `logger.exception`.

## Rastreabilidade (critério de aceite → implementação)

Abreviações: `rd/` = `api/tests/test_reads.py` (marcados `db`), `fl/` = `api/tests/test_filters.py` (sem banco), `mw/` = `api/tests/test_middleware.py`, `ins/` = `api/tests/test_inspections.py`, `nd/` = `api/tests/test_app_no_db.py`. Os arquivos de produção ficam em `api/src/qc_api/`. `repo` = `repositories/inspections.py`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `auth.py` (`require_read_key`, já existia), `routers/inspections.py`, `routers/metrics.py`, `routers/lots.py` | `rd/::test_read_routes_need_the_read_key`, `rd/::test_missing_key_is_401_before_validation`, `fl/::test_read_routes_without_key_are_401_without_database` |
| CA-02 | `repo` (`list_inspections`, `SELECT_INSPECTIONS_PAGE`), `routers/inspections.py` | `rd/::test_listing_first_page` |
| CA-03 | `repo` (`COUNT_INSPECTIONS`, `limit`/`offset`) | `rd/::test_listing_default_page_and_offsets`, `rd/::test_listing_huge_offset_is_an_empty_page` |
| CA-04 | `filters.py` (`InspectionFilters`, `Pagination`) | `rd/::test_invalid_parameters_are_422`, `rd/::test_limit_500_is_accepted`, `fl/::test_from_must_be_before_to` |
| CA-05 | `repo` (`where_clause`) | `rd/::test_listing_filters`, `fl/::test_where_clause_combines_every_filter_with_placeholders` |
| CA-06 | `repo` (`SELECT_SUMMARY`, `summarize`) | `rd/::test_summary_without_filters`, `rd/::test_summary_json_keys` |
| CA-07 | `repo` (`summarize` + `where_clause`) | `rd/::test_summary_by_source_and_lot` |
| CA-08 | `repo` (`summarize`: chaves preenchidas com 0, `nullif`, `avg` nulo) | `rd/::test_summary_without_rows` |
| CA-09 | `repo` (`nullif` do denominador) | `rd/::test_summary_only_unknown` |
| CA-10 | `repo` (`SELECT_TIMESERIES`), `routers/metrics.py` (`bucket` padrão `hour`) | `rd/::test_timeseries_by_hour_is_the_default`, `rd/::test_timeseries_day_minute_and_source` |
| CA-11 | `repo` (`date_trunc(%(bucket)s, inspected_at, %(time_zone)s)` com `UTC`) | `rd/::test_timeseries_buckets_are_utc` (também com a sessão da API em `America/Sao_Paulo`) |
| CA-12 | `routers/metrics.py` (`bucket: Literal["minute","hour","day"]`), `repo` (bucket como parâmetro) | `rd/::test_timeseries_invalid_bucket`, `rd/::test_timeseries_day_minute_and_source` |
| CA-13 | `repo` (`MAX_BUCKETS`, `limit 5001`, `TooManyBucketsError`), `routers/metrics.py`, `errors.py` (`DETAIL_TOO_MANY_BUCKETS`) | `rd/::test_timeseries_bucket_limit` (5 000 → 200; 5 001 → 422; `day` → 200) |
| CA-14 | `repo` (`SELECT_LOTS_PAGE`, `list_lots`) | `rd/::test_lots`, `rd/::test_lots_ties_ordered_by_lot_id` |
| CA-15 | `repo` (`array_agg(distinct source)` ordenado pela ordem do enum `Source` em `_lot_summary`) | `rd/::test_lot_sources_in_enum_order_and_filters` |
| CA-16 | `repo` (`COUNT_LOTS`), `filters.py` (`Pagination`) | `rd/::test_lots_pagination`, `rd/::test_invalid_parameters_are_422` |
| CA-17 | `db.py` (`db_connection` → `DatabaseUnavailableError`, já existia), `repo` (`_read_snapshot`) | `fl/::test_read_routes_without_database_are_503` |
| CA-18 | `filters.py` (parâmetros desconhecidos são ignorados pelo FastAPI) | `rd/::test_listing_filters` (caso `lot_id=L-A&foo=bar`) |
| CA-19 | `repo` (SQL em `str` + `sql.SQL(...).format(...)`), demais módulos sem SQL formatado | `fl/::test_sql_is_never_formatted_as_a_python_string` (varredura AST de `api/src/qc_api`; conferido com um arquivo-sonda com f-string, `%` e `.format`, que o teste marcou nas 3 linhas) |
| CA-20 | `routers/inspections.py` (`_write`: `except (psycopg.DataError, psycopg.IntegrityError)`), `db.py` (docstring) | `ins/::test_integrity_error_is_422_and_rolls_back` (restrição real `author_strict_lot`, removida no `finally`) |
| CA-21 | `middleware.py` (`find_database_error`, `sqlstate_label`, `UnhandledErrorMiddleware`) | `mw/::test_database_error_is_logged_without_message` (direta, `__cause__`, `__context__` suprimido, sem SQLSTATE), `mw/::test_other_exceptions_keep_the_traceback`, `mw/::test_find_database_error_follows_chain_and_groups`, `mw/::test_find_database_error_survives_cycles`, `mw/::test_sqlstate_label_rejects_odd_values`, `nd/::test_database_error_in_a_route_of_the_real_app_is_sanitized` (app real + `add_api_route`) |

## Resposta à rodada anterior (a partir de r2)

N/A (r1).

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest -q api/tests                                    # sem banco: os testes db são pulados
TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q api/tests
```

Resultados desta rodada (máquina local, Postgres 16 do Docker da SPEC-001):

- `uv run ruff check .`: `All checks passed!`; `uv run ruff format --check .`: `102 files already formatted`.
- `uv run pytest -q` **sem** `TEST_DATABASE_URL`: `1257 passed, 384 skipped`.
- `uv run pytest -q` **com** `TEST_DATABASE_URL`: `1640 passed, 1 failed`. A falha é `api/tests/acceptance/test_spec_004.py::test_extra_wrong_methods_and_unknown_route`, explicada no SPEC_ISSUE-01 abaixo. Todos os testes do autor passam.

## Decisões tomadas dentro do escopo da SPEC

- **`InspectionFilters` como dataclass dependência.** O módulo `filters.py` não usa `from __future__ import annotations`, porque o FastAPI lê a assinatura da dataclass em tempo de execução. O parâmetro `from` é o campo `from_` com `Query(alias="from")` (§7 da SPEC).
- **Erro de `from >= to`:** 422 no formato padrão, `{"detail": [{"type": "value_error", "loc": ["query", "to"], "msg": "'from' must be earlier than 'to'"}]}`, sem `input`.
- **`offset` gigante:** o FastAPI aceita qualquer inteiro ≥ 0, mas o Postgres recusa `offset` acima de `bigint` (SQLSTATE 22003), o que viraria 500. O valor enviado ao banco é limitado a `2**63 − 1` (`MAX_SQL_OFFSET`). A resposta ecoa o `offset` pedido, com `items=[]` e o `total` correto, o mesmo resultado de "offset além do total" da §4.3. Não há 422 novo. Teste: `rd/::test_listing_huge_offset_is_an_empty_page`.
- **Limite de buckets:** a consulta busca no máximo `MAX_BUCKETS + 1` = 5 001 linhas. Se vierem 5 001, a resposta é 422, sem carregar todos os buckets no Python.
- **Transação de leitura** `repeatable read, read only` (primeiro comando da transação, por cursor; nada muda no estado da conexão do pool). No modo transaction do pooler do Supabase isso vale, porque fica dentro da transação.
- **Resumo numa única instrução:** CTE `matched` + subconsultas `jsonb_object_agg` para `by_grade` e `by_object_type`. Os parâmetros de filtro entram uma vez só. O Python só completa as chaves ausentes com 0, a partir dos enums de `qc_contracts`.
- **`sources` dos lotes:** `array_agg(distinct source)` no SQL. A ordem do enum `Source` é aplicada no Python sobre no máximo 2 valores por lote.
- **Log do 500 de banco:** `type=` é `type(exc).__name__` da primeira `psycopg.Error` da cadeia. A busca é em profundidade (`__cause__` antes de `__context__`), também dentro de `ExceptionGroup`, e inclui o contexto suprimido por `from None` (regra conservadora). O SQLSTATE só é registrado se casar com `[0-9A-Z]{5}`; senão sai `-`. Se a resposta já tiver começado, o middleware relança `RuntimeError("unhandled database error") from None`, para que o servidor não imprima a mensagem do banco no traceback dele.
- **`READ_ERROR_RESPONSES`** (documentação OpenAPI de 401/422/503) fica em `routers/__init__.py`.
- **Sem variável de ambiente nova:** o `.env.example` não mudou.

## SPEC_ISSUE (se houver)

**SPEC_ISSUE-01 — teste "extra" de aceite da SPEC-004 contradiz o CA-01 da SPEC-005.**

- `api/tests/acceptance/test_spec_004.py::test_extra_wrong_methods_and_unknown_route` (do tester da SPEC-004, commit `e8f4b3b`) afirma `env.client.get(URL_ONE, headers=key_header(env.ke)).status_code == 405`, ou seja, `GET /api/v1/inspections` com a chave do dispositivo → 405, porque na SPEC-004 a rota só tinha `POST`.
- A SPEC-005 (§4.3 e CA-01) cria `GET /api/v1/inspections` e exige 401 `{"detail": "Missing or invalid API key"}` para a chave de dispositivo. Com a implementação, essa linha do teste antigo recebe 401 e falha. É a única falha da suíte com banco.
- Eu não posso alterar `tests/acceptance/` (R-07), e a §3.1 da SPEC-005 não autoriza o tester a mudar o `test_spec_004.py`. O código segue a SPEC-005, e não há como satisfazer os dois.
- **Decisão pedida (orquestrador/architect, com o humano):** autorizar o tester da SPEC-005 a ajustar essa asserção no `test_spec_004.py`, por exemplo trocando o método por um que continue sem rota (`PUT`/`DELETE` em `/api/v1/inspections` → 405) ou esperando 401. Não é CA da SPEC-004; é um teste "extra" dela.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (com e sem banco)
- [x] `.env.example` atualizado (se houver variável nova): nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhuma credencial literal em URL/conninfo/header nos testes: o app sem banco usa a URL de `closed_port_url` (senha gerada em tempo de execução), e a sessão em outro fuso é montada com `make_conninfo(clean_db, options=...)`
- [x] Nenhum teste roda o pytest em subprocesso
