# SPEC-004 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-004](../../docs/specs/SPEC-004-api-ingestao.md) |
| Rodada | r2 |
| Autor | developer |
| Branch | `spec/SPEC-004-api-ingestao` |
| Commits | `8bd8306` (fix(api): keep validation errors a 422 when the body cannot be encoded), mais o commit deste relatório. Os commits da r1 estão em [r1-dev-report.md](r1-dev-report.md) |

## Resumo

- Rodada de correção dos bugs T-01 e T-02 de [r1-test-report.md](r1-test-report.md). Só mudou `api/src/qc_api/errors.py`, além dos testes do autor.
- Novo handler de `RequestValidationError` (`_request_validation_error`), registrado em `install_exception_handlers`. Ele delega ao handler padrão do FastAPI (`request_validation_exception_handler`), então todo 422 que já funcionava continua **idêntico** ao padrão (§4.5).
- Só quando o handler padrão falha ao codificar o `input` ecoado (`UnicodeDecodeError`, que é um `ValueError`, para bytes não UTF-8; `RecursionError` para JSON aninhado além do limite de recursão), a resposta é o mesmo 422 `{"detail": [...]}`, mas cada erro leva só `type`, `loc` e `msg`, sem `input` (e sem `ctx`). Esse fallback é montado só com `str` e `int`, então não pode falhar de novo.
- Com isso, nenhuma exceção chega ao `UnhandledErrorMiddleware` nesses casos: a resposta é 422 em vez de 500 (T-01), e o `logger.exception` que registrava a `RequestValidationError` encadeada, com o corpo bruto, não é mais chamado (T-02).
- Nada muda na precedência (413 → 503 → 401 → 422 → 403 → 422): o handler só age depois da autenticação, como antes. Nada é gravado e `last_seen_at` não muda nesses 422.

## Rastreabilidade (critério de aceite → implementação)

Abreviações: `nd/` = `api/tests/test_app_no_db.py`, `ins/` = `api/tests/test_inspections.py`, `mw/` = `api/tests/test_middleware.py`, `er/` = `api/tests/test_errors.py`, `cfg/` = `api/tests/test_config.py`, `au/` = `api/tests/test_auth.py`, `rd/` = `api/tests/test_register_device.py`. Os arquivos de produção estão em `api/src/qc_api/`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `routers/health.py`, `db.py` (`ping`) | `ins/::test_health_ok` |
| CA-02 | `main.py` (`lifespan`, `open(wait=False)`), `routers/health.py` | `nd/::test_startup_does_not_fail_and_health_is_503` |
| CA-03 | `routers/inspections.py`, `db.py` (`insert_inspections`) | `ins/::test_create_stores_utc_and_server_fields` |
| CA-04 | `db.py` (`ON CONFLICT DO NOTHING`) | `ins/::test_duplicate_does_not_change_original` |
| CA-05 | `auth.py` (`require_device`), `errors.py` (`unauthorized`) | `ins/::test_invalid_keys_are_401`, `::test_key_of_257_chars_is_401_even_if_registered` |
| CA-06 | `auth.py` (dependência resolvida antes da validação do corpo) | `ins/::test_auth_before_validation` |
| CA-07 | `routers/inspections.py` (`_write`) | `ins/::test_device_mismatch_is_403` |
| CA-08 | contrato (`InspectionCreate`) + 422 padrão do FastAPI; `errors.py` (`_request_validation_error`, r2) | `ins/::test_invalid_bodies_are_422`; `er/::test_encodable_errors_keep_the_default_422` |
| CA-09 | `middleware.py` (`BodySizeLimitMiddleware`), `errors.py` (`BodyTooLargeError`) | `ins/::test_body_limit`; `mw/::test_body_at_limit_passes`, `::test_body_over_limit_is_413`, `::test_declared_length_over_limit_is_413_without_reaching_the_app`, `::test_chunked_body_over_limit_is_413`, `::test_chunked_json_body_over_limit_is_413_not_400`; `nd/::test_declared_body_over_limit_is_413_before_auth`, `::test_max_body_bytes_comes_from_settings` |
| CA-10 | `db.py` (`UPDATE_LAST_SEEN` na mesma transação) | `ins/::test_last_seen_updates_only_on_success` |
| CA-11 | `routers/inspections.py` (`create_inspections_batch`), `db.py` | `ins/::test_batch_created_in_order` |
| CA-12 | `db.py` (transação única, em ordem) | `ins/::test_batch_duplicates_inside_and_outside` |
| CA-13 | contrato (`BatchCreate`) | `ins/::test_batch_with_invalid_item_writes_nothing`, `::test_batch_size_limits` |
| CA-14 | `routers/inspections.py` (`_write`) | `ins/::test_batch_with_foreign_device_is_403` |
| CA-15 | `db.py` (`ON CONFLICT`) | `ins/::test_concurrent_same_id_creates_one_row` |
| CA-16 | `db.py` (`db_connection`), `errors.py` (`DatabaseUnavailableError` → 503) | `nd/::test_write_without_database_is_503` |
| CA-17 | `main.py` (sem `CORSMiddleware`) | `nd/::test_no_cors_headers` |
| CA-18 | `middleware.py` (`RequestLogMiddleware`), `auth.py`, `db.py` | `nd/::test_logs_have_no_password`; `ins/::test_logs_have_no_keys` |
| CA-19 | `routers/inspections.py` (corpos só JSON), `main.py` (`docs_url`) | `nd/::test_openapi_only_json_bodies_and_docs`, `::test_multipart_upload_is_rejected` |
| CA-20 | `config.py` (`hide_input_in_errors`) | `cfg/::test_short_read_key_error_hides_value`, `::test_missing_database_url`, `::test_database_url_value_not_in_error` |
| CA-21 | `scripts/register_device.py` | `rd/::test_register_then_use_then_rotate` |
| CA-22 | `scripts/register_device.py` (`--rotate`) | `rd/::test_register_then_use_then_rotate` |
| CA-23 | `scripts/register_device.py` (`re.fullmatch`, códigos 1/2) | `rd/::test_rotate_unknown_device_exits_1`, `::test_invalid_device_id_exits_2` (inclui `Edge_01` e `"edge-01\n"`), `::test_missing_url_exits_2` |
| CA-24 | contrato (`MAX_LATENCY_MS`) | `ins/::test_latency_limits` |
| CA-25 | `routers/inspections.py` (`except psycopg.DataError`) | `ins/::test_float4_underflow_is_422_and_rolls_back` |
| CA-26 | FastAPI 0.143 (corpo que o `json.loads` recusa → 400) | `ins/::test_huge_json_integer_is_4xx` |
| CA-27 | — (tester, §3.1) | — |
| CA-28 | — (tester, §3.1) | — |

Requisitos sem CA próprio: §4.1 (`cfg/::test_defaults`, `::test_reads_environment`, `::test_dotenv_file_is_not_read`, `::test_invalid_max_body_bytes`, `::test_invalid_log_level`; `nd/::test_settings_loaded_from_environment_at_startup`, `::test_startup_fails_without_settings`); `hash_api_key` e `require_read_key` (`au/`); 500 genérico (`mw/::test_unhandled_exception_is_generic_500`); §4.4/§4.5 "erros 4xx, nunca 500" e §4.2 "nunca logar o corpo" para corpos que o 422 padrão não codifica (r2, T-01/T-02): `er/::test_non_utf8_body_is_422`, `::test_multipart_image_is_422`, `::test_deeply_nested_json_is_422`, `::test_request_body_never_logged`, `::test_error_without_input_keeps_only_plain_fields`; `ins/::test_bodies_the_default_422_cannot_encode_are_422` (rota única e lote, com banco); log por requisição (`mw/::test_request_log_line`, `::test_request_log_unmatched_path_is_escaped`).

## Resposta à rodada anterior (a partir de r2)

| Achado (relatório, ID) | O que mudou |
|---|---|
| r1-test-report, **T-01** (500 para corpo binário/multipart não UTF-8 e para JSON aninhado em 2000 níveis, nas duas rotas) | `errors.py`: handler próprio de `RequestValidationError` com fallback sem `input` (resumo acima). Agora: multipart, `application/octet-stream` e `image/jpeg` com bytes não UTF-8 → 422; JSON aninhado em 2000/3000/5000 níveis → 422 (com 100 000 continua 400, recusado pelo `json.loads` antes da validação, como já era). Testes: `er/::test_non_utf8_body_is_422`, `::test_multipart_image_is_422`, `::test_deeply_nested_json_is_422`; `ins/::test_bodies_the_default_422_cannot_encode_are_422[...]` (rota única e lote, com banco: nada gravado, `last_seen_at` nulo). Os testes exploratórios do tester `test_extra_binary_non_json_body_is_4xx_not_500[/api/v1/inspections]`, `[/api/v1/inspections/batch]` e `test_extra_deeply_nested_json_is_4xx_not_500[2000]` passam |
| r1-test-report, **T-02** (corpo bruto no log via `logger.exception` do `UnhandledErrorMiddleware`) | Mesma correção: a exceção que carregava o corpo não escapa mais do handler, e o fallback não ecoa nada. Testes: `er/::test_request_body_never_logged` (corpo binário com marcador e JSON aninhado em 3000 níveis com o marcador no fundo: o marcador e `\xff\xd8\xff` não aparecem no log, nenhum registro `ERROR`, e a linha de log por requisição mostra o 422) e a parte de log de `ins/::test_bodies_the_default_422_cannot_encode_are_422`. O teste do tester `test_extra_request_body_never_logged` passa |
| r1-test-report, avaliação do timeout de 5 s do pool | Sem mudança, conforme a recomendação do tester (valor fixado pelo §4.2) |

## Como rodar e verificar

```bash
uv sync --all-packages --frozen
export TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test
uv run pytest -q api/tests            # 152 testes (inclui os de aceite do tester); sem TEST_DATABASE_URL, os de banco são pulados
uv run pytest -q api/tests/test_errors.py   # handler de validação, sem banco
```

## Decisões tomadas dentro do escopo da SPEC

1. **Delegar ao handler padrão e só cair no fallback quando ele falha**, em vez de sempre remover o `input`. Assim o §4.5 ("erros de validação usam o 422 padrão do FastAPI") continua valendo à risca para todo corpo que o padrão consegue codificar. `er/::test_encodable_errors_keep_the_default_422` compara a resposta, campo a campo, com a de uma app idêntica sem o handler (`not json`, campos faltando, `[]`, JSON aninhado em 500 níveis).
2. **O fallback tira `input` e `ctx`.** O `ctx` pode conter objetos (ex.: a exceção de um validador), que exigiriam o `jsonable_encoder` de novo. `loc` vira uma lista de `str`/`int` (qualquer outro tipo passa por `str`). O formato continua `{"detail": [...]}`, a forma do 422 padrão.
3. **Exceções capturadas: `ValueError` e `RecursionError`, só em volta da chamada ao handler padrão.** São exatamente as duas falhas do `jsonable_encoder`/`json.dumps` descritas no T-01 (`UnicodeDecodeError` é subclasse de `ValueError`). Qualquer outra exceção continua indo para o 500 genérico.
4. **Sem mudança no `UnhandledErrorMiddleware`.** O §4.5 exige que o traceback de uma exceção inesperada vá para o log do servidor. A correção remove a causa (a exceção com o corpo), sem filtrar tracebacks de forma genérica.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos (74 arquivos)
- [x] Testes unitários do autor passando. Suíte inteira: **com** `TEST_DATABASE_URL` → 1247 passed (2 min 37 s), incluindo os 4 exploratórios do tester que falhavam na r1; **sem** banco (`TEST_DATABASE_URL` e `CI` ausentes) → 986 passed, 261 skipped (1 min 24 s)
- [x] `.env.example` atualizado (se houver variável nova): nenhuma variável nova nesta rodada
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhuma credencial literal em URL, conninfo ou header nos testes novos (o marcador do corpo é gerado em tempo de execução) e nenhum teste roda a suíte em subprocesso
