# SPEC-006 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-006](../../docs/specs/SPEC-006-spc.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-006-spc` (diff `main...HEAD`) |
| Commits | `df400bd` (feat(api): add p chart service and GET /api/v1/metrics/spc), `0089839` (test(api): cover the p chart service and the SPC route), `b059f30` (ci: add coverage gate for qc_api.services), mais o commit deste relatório |

## Resumo

- **Serviço puro (§4.1):** `api/src/qc_api/services/spc.py` define `LotCounts` (dataclass congelada, `ValueError` se `n < 1` ou `defects` fora de `0..n`) e `compute_p_chart(lots, baseline_lots=20, min_lot_size=5, *, source=Source.LIVE) -> SpcResponse`. O algoritmo segue os passos 1 a 8 da SPEC: ordena uma cópia por `(started_at, lot_id)` (com `sorted`, sem mutar a entrada), separa os excluídos, devolve `points = []`, `p_bar = None` e `message` com menos de 2 válidos, calcula `p̄` nos primeiros `baseline_lots` válidos e os limites por lote com `max(0.0, p̄(1−p̄))` antes da raiz (com `p̄ = 0` ou `1`, `σ = 0` e `ucl = lcl = p̄`), com corte em `[0, 1]` e desigualdades estritas. Sem arredondamento. O módulo importa só `math`, `collections.abc`, `dataclasses`, `datetime` (a classe, para a anotação) e `qc_contracts`.
- **Consulta (§4.2):** `repositories/inspections.py::lot_counts(pool, source, object_type=None)` usa fragmentos fixos `sql.SQL` (`object_type <> %(unknown)s`, `source = %(f_source)s` e, se informado, `object_type = %(f_object_type)s`), agrupa por `lot_id` (`count(*)`, `count(*) filter (where is_defective)`, `min`/`max(inspected_at)`) e roda na mesma transação `repeatable read, read only` das outras leituras. Cada linha vira um `LotCounts`.
- **Rota (§4.2):** `GET /api/v1/metrics/spc` em `routers/metrics.py`, no router que já tem `require_read_key` e as respostas 401/422/503 documentadas. `source` (`Source`, padrão `live`), `object_type` (só `screw`/`nut`), `baseline_lots` (2…100, padrão 20) e `min_lot_size` (1…500, padrão 5) são validados pelo FastAPI (422 padrão). O banco indisponível vira 503 pelo caminho existente (`db_connection` → `DatabaseUnavailableError`). A resposta repete os parâmetros efetivos.
- **CI (§4.3):** passo novo depois do `uv run pytest -q`, com o comando exato da SPEC.

## Rastreabilidade (critério de aceite → implementação)

Abreviações: `svc` = `api/src/qc_api/services/spc.py`, `repo` = `api/src/qc_api/repositories/inspections.py`, `rt` = `api/src/qc_api/routers/metrics.py`; `u/` = `api/tests/test_spc.py` (sem banco), `r/` = `api/tests/test_spc_route.py` (marcado `db`), `fl/` = `api/tests/test_filters.py` (sem banco), `ci/` = `tests/test_ci_workflow.py`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `svc` (`compute_p_chart`, `_point`) | `u/::test_example_1`, `u/::test_example_1_points_keep_counts_and_period`, `u/::test_example_1_values_are_not_rounded` |
| CA-02 | `svc` | `u/::test_example_2_defaults` |
| CA-03 | `svc` (`sorted(lots, key=_sort_key)`) | `u/::test_shuffled_input_gives_the_same_chart_and_is_not_mutated`, `u/::test_tuple_input_is_accepted` |
| CA-04 | `svc` (`_sort_key = (started_at, lot_id)`) | `u/::test_ties_on_started_at_are_ordered_by_lot_id`, `u/::test_order_uses_instants_not_offsets` |
| CA-05 | `svc` (`max(0.0, p̄(1−p̄))`) | `u/::test_p_bar_zero_collapses_the_limits`, `u/::test_point_exactly_on_a_limit_is_in_control` |
| CA-06 | `svc` | `u/::test_p_bar_one_collapses_the_limits` |
| CA-07 | `svc` (`INSUFFICIENT_DATA`, `MIN_VALID_LOTS`) | `u/::test_one_valid_lot_is_insufficient`, `u/::test_no_lots_is_insufficient`, `u/::test_insufficient_message_uses_the_effective_min_lot_size`, `u/::test_insufficient_response_serializes_null_p_bar` |
| CA-08 | `svc` (`min(1.0, ·)`, `max(0.0, ·)`) | `u/::test_limits_are_clipped_to_zero_and_one` |
| CA-09 | `svc` (`LotCounts.__post_init__`, validação de `baseline_lots`/`min_lot_size`) | `u/::test_lot_counts_rejects_impossible_counts`, `u/::test_lot_counts_accepts_the_boundaries`, `u/::test_invalid_parameters_raise` |
| CA-10 | `repo` (`SELECT_LOT_COUNTS`, `lot_counts`), `rt` (`metrics_spc`) | `r/::test_example_1_from_the_database`, `r/::test_lot_period_comes_from_the_rows_in_utc` |
| CA-11 | `rt` (padrões 20 e 5) | `r/::test_example_2_defaults` |
| CA-12 | `repo` (filtro `source` e `object_type`), `rt` | `r/::test_simulated_only_with_explicit_source`, `r/::test_object_type_filter`, `r/::test_types_are_pooled_without_filter_and_split_with_it`, `r/::test_sources_are_never_mixed_in_one_lot`, `r/::test_lot_of_unknown_rows_only_does_not_appear` |
| CA-13 | `rt` (`Query(ge=..., le=...)`, `SpcObjectType`) | `r/::test_invalid_parameters_are_422`, `r/::test_boundary_parameters_are_200`, `fl/::test_validation_does_not_need_the_database`, `fl/::test_openapi_documents_the_spc_parameters` |
| CA-14 | `rt` (router com `require_read_key`), `db.py` (já existia) | `r/::test_needs_the_read_key`, `r/::test_missing_key_is_401_before_validation`, `fl/::test_read_routes_without_key_are_401_without_database`, `fl/::test_read_routes_without_database_are_503` (o `READ_URLS` agora inclui `/api/v1/metrics/spc`) |
| CA-15 | `svc` (só `math`, `collections.abc`, `dataclasses`, `datetime`, `qc_contracts`) | `u/::test_spc_module_has_no_io_imports`, `u/::test_spc_module_does_not_read_the_clock` |
| CA-16 | `.github/workflows/ci.yml` | `ci/::test_services_coverage_gate_runs_after_pytest`; execução local do comando: 100% de cobertura (ver abaixo) |

Outros testes: `r/::test_empty_database`, `r/::test_min_lot_size_is_the_effective_one`, `r/::test_unknown_query_parameters_are_ignored`, `u/::test_source_is_only_copied_to_the_response`, `u/::test_source_is_keyword_only`, `u/::test_baseline_*`, `u/::test_excluded_lots_follow_the_chart_order`, `u/::test_min_lot_size_one_keeps_every_lot`, `u/::test_lot_exactly_at_min_lot_size_is_valid`, `u/::test_lot_counts_is_frozen`.

## Resposta à rodada anterior (a partir de r2)

N/A (r1).

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest -q api/tests/test_spc.py api/tests/test_filters.py           # sem banco
TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q api/tests/test_spc_route.py
uv run pytest api/tests -q -m "not db" --cov=qc_api.services --cov-report=term-missing --cov-fail-under=80
```

Resultados desta rodada (máquina local, Postgres 16 do Docker da SPEC-001):

- `uv run ruff check .`: `All checks passed!`; `uv run ruff format --check .`: `107 files already formatted`.
- `uv run pytest -q` **com** `TEST_DATABASE_URL`: `1773 passed` (4 min 31 s).
- `uv run pytest -q` **sem** `TEST_DATABASE_URL` (e sem `CI`): `1303 passed, 470 skipped`.
- Portão de cobertura (comando do §4.3): `140 passed, 286 deselected`, `services/__init__.py` 100% e `services/spc.py` 100% (44 statements, 0 miss), `Required test coverage of 80% reached`.

Nenhum teste de aceite de SPEC anterior falhou.

## Decisões tomadas dentro do escopo da SPEC

- **`object_type` da rota:** `SpcObjectType`, um `StrEnum` derivado de `qc_contracts.ObjectType` sem `unknown` (não redefine valores: os tipos da Fase 2 entram sozinhos). Assim, `unknown` é o 422 padrão do FastAPI (`type: enum`) e o OpenAPI lista só `screw` e `nut`. Na rota, o valor é convertido de volta para `ObjectType` antes da consulta.
- **`lot_counts` no repositório:** fica junto das outras consultas de leitura, com o mesmo snapshot `repeatable read, read only`; o repositório importa `LotCounts` do serviço (o serviço não importa nada de I/O). A consulta já ordena por `(started_at, lot_id)`, só por determinismo; a ordem que vale é a de `compute_p_chart`.
- **Constantes:** limites da rota em `SPC_*` no `routers/metrics.py`; a mensagem em `INSUFFICIENT_DATA` no serviço, com `need=2` vindo de `MIN_VALID_LOTS`. O texto final é exatamente o da SPEC.
- **Logs:** a rota não registra nada. Falha de conexão → 503 pelo `db_connection`; outro `psycopg.Error` → 500 pelo `UnhandledErrorMiddleware`, que registra só rota, classe e SQLSTATE (§4, "Erros de banco no log").
- **Credenciais nos testes:** nenhuma URL ou conninfo literal com senha; o 503 usa o `no_db_settings` existente (senha gerada em tempo de execução). A chave de leitura é a `"r" * 32` já usada pelas outras suítes.

## Notas para o tester e o reviewer

- **CA-16 e a regra §10 ("Sem suíte dentro da suíte"):** o comando do CA-16 roda `pytest api/tests` (um diretório inteiro de `testpaths`). Um teste automatizado que o rode em subprocesso violaria a §10. Sugestão: verificar a presença do passo no `ci.yml` por teste e a execução do comando por fora, registrada no test-report (como fiz acima). Não abri `SPEC_ISSUE` porque a §10 já diz como tratar esse tipo de CA.
- **Tamanho da resposta:** a SPEC não limita o número de lotes; a resposta tem um ponto por lote válido da origem escolhida. Para a demo é irrelevante, mas fica registrado para o security-devops.
- **Tempo do teste sem banco:** o `READ_URLS` do `test_filters.py` ganhou a rota SPC, então `test_read_routes_without_database_are_503` espera mais um timeout do pool (~5 s).
- A instrução do orquestrador cita a regra "Testes de aceite de SPECs anteriores" na §10 da `architecture.md`; ela não existe nesta branch (a §10 tem "Marcadores", "Sem suíte dentro da suíte" e "Expectativas de versão"). Sem impacto: nenhum teste de aceite anterior falhou.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (com e sem banco)
- [x] `.env.example` atualizado (se houver variável nova): N/A, nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
