# SPEC-004 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-004](../../docs/specs/SPEC-004-api-ingestao.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-004-api-ingestao` (empilhada sobre `docs/pendencias-pos-024`, PR #10; diff desta SPEC: `docs/pendencias-pos-024...HEAD`) |
| Commits | `4ee3108` (feat(api): settings, auth, errors e middleware), `a9746cc` (feat(api): rotas health e inspections), `475ad44` (feat(scripts): register_device.py), `5d455d4` (docs: `.env.example` e README), mais o commit deste relatório |

## Resumo

- `qc-api` 0.1.0 (`__version__` e `api/pyproject.toml`; o `uv.lock` muda só a versão do membro). Módulos do §3.1: `config.py`, `db.py`, `auth.py`, `errors.py`, `middleware.py`, `main.py`, `routers/health.py`, `routers/inspections.py`.
- `create_app(settings=None)`: as settings vêm do ambiente no `lifespan`. O `ConnectionPool` é criado com exatamente os parâmetros do §4.2 e aberto com `open(wait=False)`, então a API sobe com o banco fora do ar. Não há `CORSMiddleware`. `app = create_app()` em nível de módulo.
- Rotas síncronas: `GET /api/v1/health` (200/503 com `HealthResponse`), `POST /api/v1/inspections` (201/200) e `POST /api/v1/inspections/batch` (200). As escritas usam `INSERT ... ON CONFLICT (inspection_id) DO NOTHING RETURNING` e o `update devices set last_seen_at = now()`, tudo numa única transação. O 403 é checado antes de gravar. `psycopg.DataError` vira 422 `Value cannot be stored`, com rollback e log só da rota, do `device_id` e do SQLSTATE.
- Middlewares ASGI puros: limite de corpo (413 por `Content-Length` sem ler o corpo; contagem dos bytes lidos no chunked), 500 genérico (traceback só no log) e uma linha de log por requisição (método, rota, status, `device_id`, duração).
- `scripts/register_device.py`: valida com `re.fullmatch(DEVICE_ID_PATTERN, ...)`, grava só `hash_api_key(chave)` e escreve uma linha `DEVICE_API_KEY=<chave>` no stdout, com `--rotate` e os códigos de saída 0/1/2.
- 65 testes do autor em `api/tests/` (os de banco marcados `db`), `.env.example` (`MAX_BODY_BYTES`, `LOG_LEVEL` e um comentário em `READ_API_KEY`) e uma seção nova no README.

## Rastreabilidade (critério de aceite → implementação)

Abreviações: `nd/` = `api/tests/test_app_no_db.py`, `ins/` = `api/tests/test_inspections.py`, `mw/` = `api/tests/test_middleware.py`, `cfg/` = `api/tests/test_config.py`, `au/` = `api/tests/test_auth.py`, `rd/` = `api/tests/test_register_device.py`. Os arquivos de produção estão em `api/src/qc_api/`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `routers/health.py`, `db.py` (`ping`) | `ins/::test_health_ok` |
| CA-02 | `main.py` (`lifespan`, `open(wait=False)`), `routers/health.py` | `nd/::test_startup_does_not_fail_and_health_is_503` |
| CA-03 | `routers/inspections.py`, `db.py` (`insert_inspections`) | `ins/::test_create_stores_utc_and_server_fields` |
| CA-04 | `db.py` (`ON CONFLICT DO NOTHING`) | `ins/::test_duplicate_does_not_change_original` |
| CA-05 | `auth.py` (`require_device`), `errors.py` (`unauthorized`) | `ins/::test_invalid_keys_are_401`, `::test_key_of_257_chars_is_401_even_if_registered` |
| CA-06 | `auth.py` (dependência resolvida antes da validação do corpo) | `ins/::test_auth_before_validation` |
| CA-07 | `routers/inspections.py` (`_write`) | `ins/::test_device_mismatch_is_403` |
| CA-08 | contrato (`InspectionCreate`) + 422 padrão do FastAPI | `ins/::test_invalid_bodies_are_422` |
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

Requisitos sem CA próprio: §4.1 (`cfg/::test_defaults`, `::test_reads_environment`, `::test_dotenv_file_is_not_read`, `::test_invalid_max_body_bytes`, `::test_invalid_log_level`; `nd/::test_settings_loaded_from_environment_at_startup`, `::test_startup_fails_without_settings`); `hash_api_key` e `require_read_key` (`au/`); 500 genérico (`mw/::test_unhandled_exception_is_generic_500`); log por requisição (`mw/::test_request_log_line`, `::test_request_log_unmatched_path_is_escaped`).

## Como rodar e verificar

```bash
uv sync --all-packages --frozen
export TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test
uv run pytest -q api/tests            # 65 testes; sem TEST_DATABASE_URL, os de banco são pulados
```

Os testes da "app sem banco" que chegam ao pool (health, escrita) levam cerca de 5 s cada, que é o `timeout` do pool fixado pela SPEC.

Smoke manual feito com `uvicorn qc_api.main:app` contra o Postgres local: `/health` 200, `register_device.py` + `POST` 201 e um corpo chunked de 300 000 bytes via `curl` → 413. A linha de teste foi apagada do banco depois.

## Decisões tomadas dentro do escopo da SPEC

1. **Chave ausente, vazia ou com mais de 256 caracteres → 401 sem consultar o banco** (§4.3, nessa ordem). Por isso, com o banco fora do ar, uma requisição **sem** chave recebe 401, e uma com qualquer chave não vazia de até 256 caracteres recebe 503 (CA-16). Leio o "503 → 401" da precedência do §4.5 como "banco indisponível **ao autenticar**", ou seja, quando a autenticação precisa da consulta (`nd/::test_missing_key_without_database_is_401` documenta o comportamento).
2. **JSON malformado e inteiro gigante são recusados antes da autenticação.** O FastAPI lê e decodifica o corpo antes de resolver as dependências. `not json` → 422 e o inteiro de 5 000 dígitos → 400 (`There was an error parsing the body`), mesmo sem chave. A precedência do §4.5 vale "para JSON bem formado", e o CA-26 aceita 400 ou 422.
3. **413 durante a leitura do corpo:** `BodyTooLargeError` é subclasse de `HTTPException`. Uma exceção comum levantada no `receive` seria convertida em 400 pelo FastAPI (`except Exception` no parse do corpo), e o `HTTPException` é relançado por ele. O middleware também responde 413 se a exceção escapar antes de a resposta começar. Um `Content-Length` não numérico é ignorado e os bytes são contados.
4. **500 por middleware próprio (`UnhandledErrorMiddleware`)**, e não por `add_exception_handler(Exception, ...)`. O handler genérico do Starlette relança a exceção depois de responder, o que duplicaria o traceback no log (uvicorn + nosso).
5. **Os routers carregam o prefixo `/api/v1`** (`routers.API_PREFIX`). No FastAPI 0.143, `scope["route"]` é a rota original do router, sem o prefixo do `include_router`. Com o prefixo no próprio router, o log registra o template completo (`/api/v1/inspections`). Uma rota não encontrada (ou um 413 por `Content-Length`, antes do roteamento) registra o caminho bruto com `repr`, truncado em 200 caracteres, o que evita injeção de linhas no log.
6. **Settings:** `case_sensitive=True` (só os nomes exatos do §4.1), `extra="ignore"` e `DATABASE_URL` com `min_length=1` (uma variável vazia conta como ausente). `hide_input_in_errors=True` cumpre "erro de configuração nunca mostra valores".
7. **`require_read_key` compara bytes UTF-8.** O `secrets.compare_digest` com `str` levanta `TypeError` para caracteres não ASCII, e o header é controlado pelo cliente (latin-1). Isso daria 500 em vez de 401 (`au/::test_read_key_refused`).
8. **`register_device.py`:** uma URL que o `conninfo_to_dict` não aceita sai com 2 (uso inválido, como em `infra/migrate.py`), sem ecoar a string. Erros de banco mostram só o tipo da exceção. A chave só é escrita depois do commit.
9. **Versão:** além de `__version__ = "0.1.0"`, `api/pyproject.toml` também foi para 0.1.0, para manter a coerência com `importlib.metadata.version("qc-api")` (a forma do §10). O `uv.lock` muda só nessa linha, e nenhuma dependência nova entra.
10. **Testes sem credenciais literais:** a URL da "app sem banco" é montada com `urlunsplit` e uma senha aleatória (`"pw" + token_hex`), e as chaves de dispositivo vêm de `secrets.token_urlsafe(32)` (checklist §4).

Observação, sem ação: o `fastapi.testclient` emite `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead` (Starlette 1.7). Trocar de cliente HTTP está fora do escopo desta SPEC.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando. Suíte inteira: `uv run pytest -q` **sem** banco → 967 passed, 218 skipped; **com** `TEST_DATABASE_URL` → 1185 passed (6 min 25 s, ainda com os dois meta-testes que o tester remove no §3.1)
- [x] `.env.example` atualizado (`MAX_BODY_BYTES`, `LOG_LEVEL`, sem valores secretos)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
