# SPEC-004 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-004](../../docs/specs/SPEC-004-api-ingestao.md) |
| Rodada | r2 |
| Tester | tester |
| Commit testado | `d894eb0` (correção do developer em `8bd8306`; o único arquivo de produção alterado na r2 é `api/src/qc_api/errors.py`) |
| **Veredicto** | **PASS** |

Os 28 critérios de aceite têm teste e todos passam. T-01 e T-02 da r1 estão corrigidos, e as variações que procurei também deram 4xx, sem o corpo no log. A suíte inteira passa com e sem banco, e o ruff está limpo. Sem bugs novos e sem `SPEC_ISSUE`.

## Cobertura dos critérios de aceite

Arquivo: `api/tests/acceptance/test_spec_004.py`. Os testes dos CAs são os mesmos da r1 (commit `7bc3372`): nenhum foi alterado nesta rodada. Os testes de banco são marcados `db`. CA-17, CA-19, CA-20, CA-27 e CA-28 não são (§6).

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_health_ok` | ✅ |
| CA-02 | `test_ca02_starts_without_database_and_health_is_503` | ✅ |
| CA-03 | `test_ca03_create_stores_utc_and_server_fields` | ✅ |
| CA-04 | `test_ca04_duplicates_do_not_change_original` | ✅ |
| CA-05 | `test_ca05_invalid_keys_are_401` | ✅ |
| CA-06 | `test_ca06_auth_before_validation` | ✅ |
| CA-07 | `test_ca07_device_mismatch_is_403` | ✅ |
| CA-08 | `test_ca08_invalid_bodies_are_422` | ✅ |
| CA-09 | `test_ca09_body_limit` (+ `test_extra_real_server_413_for_declared_and_chunked_bodies`) | ✅ |
| CA-10 | `test_ca10_last_seen_only_on_success` | ✅ |
| CA-11 | `test_ca11_batch_created_in_order` | ✅ |
| CA-12 | `test_ca12_batch_duplicates_inside_and_outside` | ✅ |
| CA-13 | `test_ca13_invalid_batch_is_422_and_writes_nothing` | ✅ |
| CA-14 | `test_ca14_batch_with_foreign_device_is_403` | ✅ |
| CA-15 | `test_ca15_concurrent_same_id_creates_one_row` | ✅ |
| CA-16 | `test_ca16_write_without_database_is_503` | ✅ |
| CA-17 | `test_ca17_no_cors_headers` | ✅ |
| CA-18 | `test_ca18_logs_have_no_secrets[None]`, `[DEBUG]` | ✅ |
| CA-19 | `test_ca19_openapi_only_json_and_docs` | ✅ |
| CA-20 | `test_ca20_settings_validation_hides_values` | ✅ |
| CA-21 | `test_ca21_register_device` | ✅ |
| CA-22 | `test_ca22_rotate` | ✅ |
| CA-23 | `test_ca23_script_errors` | ✅ |
| CA-24 | `test_ca24_latency_limits` | ✅ |
| CA-25 | `test_ca25_float4_underflow_is_422` | ✅ |
| CA-26 | `test_ca26_huge_json_integer_is_4xx` (400) | ✅ |
| CA-27 | `test_ca27_meta_tests_removed` | ✅ |
| CA-28 | `test_ca28_version_expectations_migrated` | ✅ |

Contagem: 81 testes no arquivo, contra 51 na r1. São 29 testes de CA (o CA-18 tem 2 parâmetros), os 22 `test_extra_*` da r1 e 30 `test_extra_r2_*` novos. Com banco, os 81 passam. Sem banco, 10 passam e 71 são pulados (`db`).

As tarefas de manutenção do §3.1 (commits `d6d9e2b` e `e6b0fc8`, da r1) não mudaram. O CA-27 e o CA-28 continuam verdes. O CA-15 da SPEC-022 e o CA-13 da SPEC-023 ("ruff + suíte inteira terminam com 0") ficam verificados pela execução abaixo.

## Verificação das correções da r1

| Achado r1 | Teste que reproduzia | r2 |
|---|---|---|
| T-01: 500 para corpo binário/multipart não UTF-8 e para JSON aninhado em 2000 níveis | `test_extra_binary_non_json_body_is_4xx_not_500[...]` (2), `test_extra_deeply_nested_json_is_4xx_not_500[2000]` | ✅ corrigido: 422 nas duas rotas, nada gravado, `last_seen_at` nulo |
| T-02: corpo bruto no log de ERROR, pela `RequestValidationError` encadeada no `logger.exception` | `test_extra_request_body_never_logged` | ✅ corrigido: nenhum registro de ERROR, e o marcador do corpo não aparece no log |

Os testes da r1 ficaram como estavam e não foram afrouxados.

**Os testes novos falhariam sem a correção.** Rodei o arquivo de aceite da r2 num worktree temporário em `05e4860` (código da r1, antes do `8bd8306`), com `PYTHONPATH` apontando para o `api/src` desse worktree. Já removi o worktree. Resultado: 33 dos 35 testes selecionados (os 5 testes da r1 sobre T-01/T-02 e os 30 `test_extra_r2_*`) falham com 500. Os 2 que passam são guardas de regressão que devem passar nas duas versões: `test_extra_r2_encodable_422_is_still_the_default` e `test_extra_deeply_nested_json_is_4xx_not_500[500]`.

## Suíte completa

Ambiente: Python 3.12, `uv`, Postgres 16 local (`TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`), sem `CI`.

```text
# Com banco (HEAD = d894eb0 + testes r2 de api/tests/acceptance/test_spec_004.py)
uv run pytest -q --cov=qc_api
1277 passed, 1 warning in 186.17s (0:03:06)
Cobertura qc_api: TOTAL 319 stmts, 10 miss, 97% (auth 97%, config 100%, db 100%, errors 100%,
main 93%, middleware 94%, routers/health 100%, routers/inspections 100%)

# Sem banco (TEST_DATABASE_URL e CI ausentes)
uv run pytest -q
986 passed, 291 skipped, 1 warning in 83.60s (0:01:23)

uv run ruff check .            -> All checks passed!
uv run ruff format --check .   -> 74 files already formatted
```

O único warning é o `StarletteDeprecationWarning` do `fastapi.testclient` (httpx), já registrado na r1.

Checklist §4 nos testes de aceite:

- Nenhuma credencial fictícia como literal em URL, conninfo ou header. Chaves e marcadores vêm de `secrets` em tempo de execução. A URL da "app sem banco" é montada com `urlunsplit` e a senha `"p" + "w"`. O teste com uvicorn real usa a conninfo do `clean_db`, que vem do `TEST_DATABASE_URL`.
- Nenhum teste roda a suíte inteira em subprocesso. O único pytest em subprocesso é o `--collect-only` do CA-27/CA-28, com caminhos explícitos e sem o `migrated_db`. Os subprocessos novos sobem só o `uvicorn`.

## Bugs encontrados

Nenhum nesta rodada.

## Testes exploratórios (além dos critérios)

### Variações de T-01/T-02 automatizadas na r2 (`test_extra_r2_*`)

Em todos os casos abaixo o teste também verifica: nenhum registro de log em `ERROR` ou acima, o marcador do corpo e os bytes `\xff\xd8\xff` ausentes do log, nada gravado e `last_seen_at` de `edge-01` nulo.

| Teste | Caso | Resultado |
|---|---|---|
| `test_extra_r2_unencodable_bodies_are_422_and_not_logged` (22 casos: 11 corpos × 2 rotas) | Bytes não UTF-8 com `Content-Type` `application/octet-stream`, `image/jpeg`, `image/png`, `text/plain`, `application/x-www-form-urlencoded`, `application/xml` e sem `Content-Type`; JSON com lista aninhada em 5000 níveis; objeto aninhado em 3000 níveis; aninhamento de 3000 níveis num campo extra de `P(X)`; e item de lote aninhado em 3000 níveis | ✅ 422 com `{"detail": [...]}` |
| `test_extra_r2_multipart_with_json_and_image_parts` (2 rotas) | Multipart com uma parte JSON válida e uma parte de imagem | ✅ 422 |
| `test_extra_r2_nesting_sweep_around_recursion_limit` (2 rotas) | Listas e objetos aninhados de `recursionlimit − 150` a `+150`, de 25 em 25 níveis, além de 20 000 e 40 000 níveis | ✅ 422, ou 400 quando o `json.loads` recusa; nunca 500 |
| `test_extra_r2_non_finite_numbers_are_422` | `NaN`, `Infinity`, `-Infinity` e `1e400` nos campos numéricos, `NaN` num campo extra, corpo `NaN` e `{"items": NaN}`, na rota única e no lote | ✅ 422. **Antes da correção era 500**: o `json.dumps(allow_nan=False)` da resposta padrão levantava `ValueError`. Era uma variante do T-01 que a r1 não tinha listado, e o fallback a cobre |
| `test_extra_r2_lone_surrogates_and_nul_are_422` | `\ud800` numa chave extra; surrogate solto em `lot_id`, `object_type` e `inspection_id`; `\u0000` numa chave extra, em `lot_id` e em `source`; nas duas rotas | ✅ 422. **Antes da correção, o surrogate na chave extra dava 500** (outra variante do T-01, também coberta agora) |
| `test_extra_r2_encodable_422_is_still_the_default` | Sem `lot_id` → `type="missing"`, `loc=["body","lot_id"]`, com `input`; `not json` → `json_invalid` | ✅ quando dá para codificar, o 422 continua sendo o padrão do FastAPI (§4.5) |
| `test_extra_r2_real_server_unencodable_bodies_are_422_and_not_logged` | uvicorn real (pilha da thread principal), com o banco de teste: multipart, `octet-stream` e JSON aninhado em 1000, 2000, 5000 e 50 000 níveis, nas duas rotas. Verifica o stdout+stderr do servidor | ✅ 422, e 400 em 50 000 níveis. O log não tem o marcador, `Traceback`, linha `ERROR` nem a chave |

### Outros caminhos do corpo até o log (análise, sem teste novo)

- Todas as chamadas de log do `qc_api` são: a linha por requisição (método, rota, status, `device_id`, duração; o caminho sem rota vai com `repr` e corte em 200 caracteres), o aviso de 403 (só o `device_id`), o aviso de `DataError` (rota, `device_id` e SQLSTATE), o aviso do health (só o nome da classe da exceção) e o `logger.exception` do `UnhandledErrorMiddleware`. Só esse último poderia levar o corpo ao log, e só se uma exceção que o carregue escapar até ele.
- O 400 de corpo que o `json.loads` recusa (inteiro de 5000 dígitos, aninhamento de 50 000 níveis, bytes não UTF-8 com `application/json`, latin-1) vira `HTTPException` e não gera registro de ERROR.
- `IntegrityError` com `DETAIL: Failing row contains (...)`, que levaria a linha inteira ao traceback, não é alcançável com valores aceitos pelo contrato. As `check` do `001_init.sql` espelham as regex e as faixas do contrato. O arredondamento para `float4` fica dentro de `[0, 1]` e `[0, 4]`, e `$` não aceita `\n` final nem no Rust regex do Pydantic nem no `~` do Postgres. A violação de FK só aconteceria numa corrida improvável: o dispositivo apagado entre a autenticação e o `insert`, e o `DETAIL` de FK traz só o `device_id`.

### Observações (não são bugs)

- **O-01, para o security-devops.** O 422 padrão do FastAPI, exigido pelo §4.5, ecoa o `input` na **resposta**, não no log. Com `Content-Type: text/plain` e um corpo UTF-8 válido, a resposta devolve o corpo inteiro (até 256 KB) ao cliente que o enviou. Isso exige uma chave de dispositivo válida e não expõe nada a terceiros. Registro só para a avaliação do portão `security`.
- **O-02.** O corpo que o `json.loads` recusa responde 400 **antes** da autenticação: sem chave, a resposta é 400, não 401. Isso é coerente com a SPEC, porque a precedência do §4.5 vale "para JSON bem formado" e o CA-26 aceita 400. A linha de log por requisição desses casos sai com `device_id=-`.
- Corpo JSON em UTF-16 com BOM é aceito (201), porque o `json.loads` detecta a codificação.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
