# SPEC-004 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-004](../../docs/specs/SPEC-004-api-ingestao.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `1f06a99` (implementação do developer; os commits do tester `d6d9e2b` e `e6b0fc8` só mexem em `tests/acceptance/`) |
| **Veredicto** | **FAIL** |

Motivo do FAIL: os 28 critérios de aceite têm teste e todos passam. Mas a suíte inteira **com banco** termina com 4 falhas, todas em testes exploratórios que reproduzem dois defeitos contra requisitos explícitos da SPEC: T-01 (500 em vez de 4xx, §4.4/§4.5) e T-02 (corpo da requisição no log, §4.2). Sem `SPEC_ISSUE`.

## Cobertura dos critérios de aceite

Arquivo: `api/tests/acceptance/test_spec_004.py`. Os testes de banco são marcados `db`; CA-17, CA-19, CA-20, CA-27 e CA-28 não são (§6).

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_health_ok` | ✅ |
| CA-02 | `test_ca02_starts_without_database_and_health_is_503` (5,0 s < 10 s) | ✅ |
| CA-03 | `test_ca03_create_stores_utc_and_server_fields` | ✅ |
| CA-04 | `test_ca04_duplicates_do_not_change_original` | ✅ |
| CA-05 | `test_ca05_invalid_keys_are_401` | ✅ |
| CA-06 | `test_ca06_auth_before_validation` | ✅ |
| CA-07 | `test_ca07_device_mismatch_is_403` | ✅ |
| CA-08 | `test_ca08_invalid_bodies_are_422` | ✅ |
| CA-09 | `test_ca09_body_limit` (+ `test_extra_real_server_413_for_declared_and_chunked_bodies`, com uvicorn real) | ✅ |
| CA-10 | `test_ca10_last_seen_only_on_success` | ✅ |
| CA-11 | `test_ca11_batch_created_in_order` | ✅ |
| CA-12 | `test_ca12_batch_duplicates_inside_and_outside` | ✅ |
| CA-13 | `test_ca13_invalid_batch_is_422_and_writes_nothing` | ✅ |
| CA-14 | `test_ca14_batch_with_foreign_device_is_403` | ✅ |
| CA-15 | `test_ca15_concurrent_same_id_creates_one_row` | ✅ |
| CA-16 | `test_ca16_write_without_database_is_503` | ✅ |
| CA-17 | `test_ca17_no_cors_headers` | ✅ |
| CA-18 | `test_ca18_logs_have_no_secrets[None]`, `[DEBUG]` (`LOG_LEVEL` padrão e `DEBUG`) | ✅ |
| CA-19 | `test_ca19_openapi_only_json_and_docs` | ✅ |
| CA-20 | `test_ca20_settings_validation_hides_values` | ✅ |
| CA-21 | `test_ca21_register_device` | ✅ |
| CA-22 | `test_ca22_rotate` | ✅ |
| CA-23 | `test_ca23_script_errors` | ✅ |
| CA-24 | `test_ca24_latency_limits` | ✅ |
| CA-25 | `test_ca25_float4_underflow_is_422` | ✅ |
| CA-26 | `test_ca26_huge_json_integer_is_4xx` (resposta 400) | ✅ |
| CA-27 | `test_ca27_meta_tests_removed` | ✅ |
| CA-28 | `test_ca28_version_expectations_migrated` | ✅ |

Contagem: 51 testes no arquivo (29 de CA, porque o CA-18 roda com 2 parâmetros, e 22 `test_extra_*`). Com banco: 47 passam e 4 falham (T-01/T-02). Sem banco: 10 passam e 41 são pulados (`db`).

### Tarefas de manutenção do §3.1 (commits próprios)

- **`d6d9e2b` (`test: remove full-suite meta-tests from SPEC-022 and SPEC-023`):** remove `test_ca15_ruff_and_full_suite_without_ci_and_db_url` de `tests/acceptance/test_spec_022.py` e `test_ca13_ruff_and_full_suite` + `_clean_env` de `packages/contracts/tests/acceptance/test_spec_023.py`. Cada um vira o comentário de uma linha da SPEC. Saem também os imports que ficaram sem uso (`os`, `subprocess` e `sys` no arquivo da SPEC-023). No arquivo da SPEC-022, `_clean_env`, `re`, `sys` e `subprocess` continuam em uso e ficaram. As docstrings de módulo que ainda citam "CA-13"/"CA-16" como cobertos não foram tocadas, porque o §3.1 só autoriza mexer em imports e helpers.
- **`e6b0fc8` (`test: migrate version expectations of shared-package acceptance tests`):** os 5 arquivos da tabela do §3.1 passam para a forma do §10 (coerência + `re.fullmatch` + piso por tupla), com os pisos da tabela: `(0, 1, 0)` nos dois `test_spec_002.py` e `(0, 2, 0)` nos demais. As docstrings dos dois `test_spec_002.py` deixam de citar versão. No CA-09 da SPEC-024 saem as asserções textuais de `"0.3.0"`/`"0.2.0"`, fica a checagem dos nomes e entram as regex `\b\d+ passed\b` / `\b\d+ (failed|errors?)\b`. `import re` entrou onde faltava.
  - **Interpretação registrada (não é `SPEC_ISSUE`):** o CA-28(b) exige, em cada um dos 5 arquivos, a comparação de coerência "para cada pacote cuja versão verificava antes". Isso inclui o pacote que fica exato no próprio arquivo (`qc-preprocess` em `preprocess/test_spec_024.py` e `qc-contracts` em `contracts/test_spec_023.py`). Nesses dois CA-01, as asserções exatas ficaram como estavam, e entrou **uma** linha a mais: `<mod>.__version__ == importlib.metadata.version("<dist>")`. A versão continua exata, como manda a tabela, e a linha é o item 1 da forma do §10. O reviewer deve conferir se aceita essa leitura.
- Contagens coletadas, `main` (`dad1880`) → agora: `test_spec_022.py` 39 → 38; `contracts/test_spec_023.py` 23 → 22; `contracts/test_spec_002.py` 165 → 165; `preprocess/test_spec_002.py` 50 → 50; `preprocess/test_spec_023.py` 36 → 36; `preprocess/test_spec_024.py` 29 → 29. Os 5 arquivos migrados passam (302 testes nos `packages/*/tests/acceptance/`). Antes de fixar o oráculo, confirmei que a análise AST do CA-28 encontra as asserções exatas antigas nas versões da `main`, ou seja, o teste falharia sem a migração.
- O CA-15 da SPEC-022 e o CA-13 da SPEC-023 ("ruff + suíte inteira terminam com 0") ficam **verificados por esta execução da suíte**: ruff limpo e as contagens abaixo.

## Suíte completa

Ambiente: Python 3.12, `uv`, Postgres 16 local (`TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`), sem `CI`.

```text
# Com banco (HEAD = e6b0fc8 + api/tests/acceptance/test_spec_004.py)
uv run pytest -q --cov=qc_api
4 failed, 1230 passed, 1 warning in 146.22s (0:02:26)
FAILED api/tests/acceptance/test_spec_004.py::test_extra_binary_non_json_body_is_4xx_not_500[/api/v1/inspections]
FAILED api/tests/acceptance/test_spec_004.py::test_extra_binary_non_json_body_is_4xx_not_500[/api/v1/inspections/batch]
FAILED api/tests/acceptance/test_spec_004.py::test_extra_deeply_nested_json_is_4xx_not_500[2000]
FAILED api/tests/acceptance/test_spec_004.py::test_extra_request_body_never_logged
Cobertura qc_api: TOTAL 306 stmts, 10 miss, 97% (auth 97%, db 100%, main 93%, middleware 94%,
routers/health 100%, routers/inspections 100%, config 100%, errors 100%)

# Sem banco (TEST_DATABASE_URL e CI ausentes)
uv run pytest -q
975 passed, 259 skipped, 1 warning in 91.24s (0:01:31)

uv run ruff check .            -> All checks passed!
uv run ruff format --check .   -> 73 files already formatted
```

O único warning é o `StarletteDeprecationWarning` do `fastapi.testclient` (httpx), já registrado no dev-report.

### Duração da suíte, antes e depois da remoção dos meta-testes

Medi a duração "antes" no commit `1f06a99`, o último antes da remoção, com o mesmo venv. A medição com banco rodou num worktree temporário, já removido. Os tempos são os do próprio pytest.

| Execução | Antes (`1f06a99`) | Depois, sem os meta-testes (`e6b0fc8`) | Depois + aceite da SPEC-004 |
|---|---|---|---|
| Sem banco | 967 passed, 218 skipped, **324 s** | 975 passed, 257 skipped, **100 s** (já com os 49 testes de aceite da época) | 975 passed, 259 skipped, **91 s** |
| Com banco | 1185 passed, **373 s** | — | 1230 passed + 4 failed, **146 s** |

Os dois meta-testes custavam, sozinhos, 246 s da execução sem banco (CA-15 da SPEC-022: 171 s; CA-13 da SPEC-023: 75 s) e 263 s da execução com banco (153 s + 110 s).

### Avaliação do timeout de 5 s da "app sem banco" (pedido do orquestrador)

- **Não é isso que deixava a suíte lenta.** O dev-report atribui os ~5 min sem banco ao timeout do pool, mas a medição mostra que 246 s dos 324 s eram os meta-testes. Cada requisição da app sem banco que chega ao pool leva 5,0 s, e hoje há 6 testes assim: 3 do autor (`test_app_no_db.py`) e 3 de aceite (CA-02, CA-16 e CA-17, este pelo `GET /health`). Somam cerca de 30 s. O `--durations` não mostra mais nenhum outro teste acima de 5 s, fora os dois testes que rodam pytest em subprocesso com caminhos explícitos (CA-09 da SPEC-024 e CA-12 da SPEC-023, cerca de 6 a 7 s cada).
- **É exigência da SPEC.** O §4.2 fixa `ConnectionPool(..., timeout=5, ...)`, e o §4.1 define as settings como exatamente quatro variáveis, sem nenhuma para o timeout do pool. Com uma porta fechada, a conexão é recusada na hora, mas o `getconn` espera o `timeout` inteiro enquanto o pool tenta de novo em segundo plano. O CA-02 ("menos de 10 s") se apoia nesse valor.
- **Dá para usar um timeout menor nos testes sem violar a SPEC?** Não sem mudar código ou SPEC. As alternativas seriam: (a) fazer monkeypatch do `ConnectionPool`/`POOL_TIMEOUT_S`, o que é mock da unidade testada e deixaria o CA-02 sem verificar o valor real; ou (b) criar uma setting nova, o que muda o §4.1 e exige SPEC. Recomendação: manter. Os ~30 s são aceitáveis agora que a suíte inteira leva 1,5 min sem banco e 2,5 min com banco.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | média | §4.4 (erros 401/403/413/422/503) e §4.5 ("erros de validação usam o 422 padrão"); checklist §3 | 1. App com banco, `edge-01` registrado com a chave `KE`. 2. `POST /api/v1/inspections` (ou `/batch`) com `X-API-Key: KE` e um corpo que não é JSON e não é UTF-8. Exemplos: `files={"image": ("a.jpg", b"\xff\xd8\xff...", "image/jpeg")}` (multipart), ou `content=b"\xff\xd8\xff..."` com `Content-Type: application/octet-stream` ou `image/jpeg`. 3. Variante: corpo JSON bem formado com 1000 ou mais níveis de aninhamento (`b"[" * 2000 + b"]" * 2000`, com `Content-Type: application/json`). Testes: `test_extra_binary_non_json_body_is_4xx_not_500[...]` (2) e `test_extra_deeply_nested_json_is_4xx_not_500[2000]` | 4xx (422 padrão, ou 400/415), nada gravado | **500** `{"detail": "Internal server error"}`, nas duas rotas. Nada é gravado e `last_seen_at` não muda. Causa: o handler padrão de `RequestValidationError` do FastAPI chama `jsonable_encoder(exc.errors())` sobre o `input` ecoado. Com bytes não UTF-8 isso levanta `UnicodeDecodeError` (`bytes: lambda o: o.decode()`), e com aninhamento profundo, `RecursionError`. O `UnhandledErrorMiddleware` converte a exceção em 500. Só acontece **depois** da autenticação: sem chave, a resposta é 401. Com 900 níveis a resposta é 422; com 100 000, 400 (o `json.loads` recusa) |
| T-02 | média (tag `security`) | §4.2 ("**Nunca** logar ... o corpo da requisição"); R-02 em espírito | Mesmos passos do T-01, com `caplog` em DEBUG ou olhando o stderr do uvicorn. Corpo de teste: `b"\xff\xd8\xff" + b"BODYMARK<hex>" + b"\xff" * 8` com `application/octet-stream`. Teste: `test_extra_request_body_never_logged` | Nenhum registro de log contém bytes do corpo | O `logger.exception("unhandled exception")` do `UnhandledErrorMiddleware` registra a exceção encadeada `RequestValidationError`, cujo texto inclui `'input': b'<corpo bruto>'`. O log de ERROR do servidor recebe o corpo inteiro, até 256 KB: uma imagem JPEG enviada por engano vai parar no log da nuvem (Render), e um corpo aninhado em 5000 níveis gera cerca de 25 KB de traceback por requisição. Um corpo JSON comum recusado com 422 **não** é logado (confirmado no mesmo teste) |

Nota para o developer, sem prescrever a correção: um handler próprio de `RequestValidationError`, que não ecoe ou não decodifique `input` quando ele for `bytes` ou profundo demais, resolve T-01 e T-02 de uma vez. O 422 padrão continua sendo o do §4.5 para os casos de JSON objeto.

## Testes exploratórios (além dos critérios)

Automatizados em `test_spec_004.py` (`test_extra_*`):

| Caso | Resultado |
|---|---|
| `hash_api_key` = SHA-256 hex minúsculo (vazio, unicode, 256 caracteres) | ✅ |
| `import qc_api.main` sem `DATABASE_URL`/`READ_API_KEY` no ambiente (`app` em nível de módulo, settings só no lifespan) | ✅ |
| Nenhum `CORSMiddleware` em `app.user_middleware` | ✅ |
| Chave vazia → 401; chave registrada de 256 caracteres → 201; de 257 caracteres, mesmo registrada → 401 | ✅ |
| Chave com caracteres não ASCII → 401 (não 500) | ✅ |
| Multipart/binário com chave válida → 4xx | ❌ T-01 |
| JSON aninhado 500 níveis → 422; 2000 níveis → 4xx | 500 ✅; 2000 ❌ T-01 |
| Corpo da requisição nunca aparece no log | ❌ T-02 |
| ID já gravado por outro dispositivo → 200 `duplicate`, sem 409 e sem trocar o dono (§7) | ✅ |
| Lote de 100 itens, um deles `unknown` (grade e campos nulos) → 200, 100 linhas | ✅ |
| `GET` na rota de escrita → 405; `POST /health` → 405; rota inexistente → 404 sem traceback | ✅ |
| Corpo JSON que não é objeto (`[]`, `null`, `"x"`, `1`) → 422 | ✅ |
| `lot_id` com unicode, espaço, `\n` final, 41 caracteres ou vazio → 422 | ✅ |
| `inspected_at` 10 min no futuro → 422 | ✅ |
| 413 vem antes do 503 e do 401 (app sem banco, sem chave, corpo de 262 146 bytes → 413 em < 4 s) | ✅ |
| Lote com sucesso atualiza `last_seen_at` | ✅ |
| Underflow → o log tem `22003` e `edge-01`, sem a mensagem do servidor | ✅ |
| Underflow só no item do meio de um lote de 3 → nada gravado, `last_seen_at` nulo, e a conexão do pool continua usável | ✅ |
| `register_device.py --database-url "not a url ::"` → sai com 1 ou 2, sem `DEVICE_API_KEY=`, sem linha nova | ✅ |
| uvicorn real + socket bruto: `Content-Length: 300000` sem corpo → 413 em < 4 s (o corpo não é lido); chunked de 311 296 bytes → 413; o log do servidor não tem a senha da URL nem a `READ_API_KEY` | ✅ |

Manuais (script descartável, não versionado):

| Caso | Resultado |
|---|---|
| `inspected_at = 0001-01-01T00:00:00Z` | 201, gravado como ano 1 UTC |
| `0001-01-01T00:00:00+14:00` e `9999-12-31T23:00:00-14:00` | 422 (fora da faixa ao normalizar para UTC, pelo contrato) |
| `grade_score = 3.99999999999`, `type_confidence = 0.999999999999` | 201; o `float4` arredonda para 4.0 e 1.0, dentro dos `check` |
| `type_confidence = -0.0` | 201, gravado como `-0.0` |
| `grade_confidence = 1e-46` | 422 `Value cannot be stored` |
| `grade_score = 1e-45` (subnormal representável) | 201 |
| `latency_ms = 1.0` / `"5"`, `needs_review = "true"` | 201 (modo lax do contrato, já documentado na SPEC-023) |
| `inspection_id` UUID v1 | 422; UUID v4 em maiúsculas → 201 |
| `lot_id` com emoji | 422 |
| `X-API-Key` repetido (inválida primeiro / válida primeiro) | 401 / 201 (vale o primeiro valor) |
| `Content-Length: abc` | ignorado, corpo contado → 201 (decisão 3 do dev-report) |
| `Content-Type: application/json; charset=utf-8` e `application/vnd.api+json` | 201 |
| Chave JSON duplicada (`lot_id` duas vezes) | 201, vale a última (comportamento do `json.loads`) |
| JSON com 100 000 níveis | 400 `There was an error parsing the body` |
| `IntegrityError` alcançável? | Não encontrei valor aceito pelo contrato que algum `check` do `001_init.sql` recuse: regex, faixas e invariantes batem. |

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
