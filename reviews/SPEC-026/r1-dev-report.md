# SPEC-026 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-026](../../docs/specs/SPEC-026-spc-teto-de-lotes.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-026-spc-teto-de-lotes` |
| Commits | `0d35f5c`, `bc1fcc0`, `6d9c335` (e o commit deste relatório) |

## Resumo

- **Contrato 0.3.0 (§4.1):** `SpcResponse` ganha `max_points` (`int ≥ 1 | None`), `valid_lots_total` e `excluded_lots_total` (`int ≥ 0 | None`), depois de `message`, todos com padrão `None`. Versão 0.3.0 em `__init__.py` e `pyproject.toml`, linha `| 0.3.0 |` no histórico do `packages/contracts/README.md` (cita a SPEC-026) e `uv.lock` alterado só na versão do `qc-contracts` (`0.2.0 -> 0.3.0`, 1 linha).
- **Serviço (§4.2):** `LotCounts` rejeita `n`/`defects` que não sejam `int` (ou sejam `bool`) e datas sem fuso (RV-03). Novos `MAX_EXCLUDED_LOTS = 50`, `LotSelection`, `select_lots` (referência pura do corte) e `build_p_chart`. `compute_p_chart = build_p_chart(select_lots(...))`, com `max_points` e `max_excluded` só por palavra-chave. O módulo continua puro.
- **Repositório (§4.3):** `lot_selection` substitui `lot_counts` (que saiu, sem outro uso). Uma única instrução SQL: a agregação por `lot_id` roda uma vez numa CTE `as materialized`, e as quatro partes (totais, base, janela, excluídos) saem dela por `union all`, cada uma com `order by ... limit`. Desempates por `lot_id collate "C"`. Mesmo snapshot `repeatable read, read only`.
- **Rota (§4.4):** `max_points` (2 a 500, padrão 100). A rota chama `lot_selection(..., max_excluded=MAX_EXCLUDED_LOTS)` e `build_p_chart`. Autenticação, 503 e R-06 inalterados.

## Rastreabilidade (critério de aceite → implementação)

Abreviações: `c/` = `packages/contracts/tests/`, `u/` = `api/tests/test_spc.py`, `r/` = `api/tests/test_spc_route.py` (marcado `db`), `f/` = `api/tests/test_filters.py`. Arquivos: `schemas` = `packages/contracts/src/qc_contracts/schemas.py`, `svc` = `api/src/qc_api/services/spc.py`, `repo` = `api/src/qc_api/repositories/inspections.py`, `rt` = `api/src/qc_api/routers/metrics.py`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `packages/contracts/src/qc_contracts/__init__.py`, `packages/contracts/pyproject.toml`, `packages/contracts/README.md`, `uv.lock` | `c/test_smoke.py::test_import_and_version`, `::test_pyproject_version_matches_dunder_version`, `::test_readme_has_version_history_row` |
| CA-02 | `schemas` (`SpcResponse`) | `c/test_schemas.py::test_spc_response_0_2_0_json_is_still_valid`, `::test_spc_response_round_trip`, `::test_spc_response_empty_with_message`, `::test_spc_response_rejects_bad_cut_fields`, `::test_spc_response_cut_field_boundaries`, `::test_spc_response_fields_are_0_2_0_plus_the_cut_fields`, `::test_spc_response_reader_ignores_unknown_fields` |
| CA-03 | `svc` (`LotCounts.__post_init__`, `_is_aware`) | `u/::test_lot_counts_rejects_wrong_types_and_naive_datetimes`, `u/::test_lot_counts_accepts_any_offset` |
| CA-04 | `svc` (`select_lots`, `LotSelection`, `_last`) | `u/::test_select_lots_cut_of_example_1`, `::test_select_lots_without_caps_keeps_everything`, `::test_select_lots_sorts_a_copy_with_python_str_order`, `::test_select_lots_last_excluded_lots_in_ascending_order`, `::test_select_lots_caps_larger_than_the_history` |
| CA-05 | `svc` (`build_p_chart`, `compute_p_chart`) | `u/::test_cut_does_not_move_the_baseline`, `u/::test_build_p_chart_uses_the_selection_as_given` |
| CA-06 | `svc` | `u/::test_without_cut_is_the_spec_006_chart`, `u/::test_build_p_chart_copies_max_points_even_none` e os testes da SPEC-006 que continuam em `u/` |
| CA-07 | `svc` (`build_p_chart`, ramo de dados insuficientes) | `u/::test_insufficient_data_keeps_the_totals` |
| CA-08 | `svc` (`validate_selection_parameters`) | `u/::test_select_lots_rejects_invalid_parameters`, `::test_compute_rejects_invalid_caps`, `::test_compute_accepts_max_excluded_zero`, `::test_build_p_chart_rejects_invalid_parameters`, `::test_build_p_chart_rejects_a_selection_without_baseline` |
| CA-09 | `svc` | `u/::test_cut_equals_the_uncut_chart_sliced[0..59]` (60 sementes, mesmo gerador descrito no CA; os 200 do CA são do tester) |
| CA-10 | `repo` (`lot_selection`), `rt` | `r/::test_example_1_has_the_default_cap_and_totals`, `r/::test_empty_database` |
| CA-11 | `repo`, `rt` | `r/::test_route_cuts_to_the_latest_lots` (mesmos 190 lotes do CA, corpo comparado com `compute_p_chart(...).model_dump(mode="json")` e `max_points=10`) |
| CA-12 | `repo` (`collate "C"`) | `r/::test_route_ties_use_the_c_collation`, `r/::test_lot_selection_matches_select_lots[0..3]` |
| CA-13 | `rt` (`Query(ge=2, le=500)`) | `r/::test_invalid_max_points_is_422`, `r/::test_boundary_max_points_is_200`, `r/::test_missing_key_is_401_before_max_points_validation`, `f/::test_openapi_documents_the_query_parameters`, `f/::test_openapi_documents_the_max_points_range` |
| CA-14 | `repo` (corte no SQL) | `r/::test_route_large_history_is_bounded` (3 000 + 150 lotes), `r/::test_rows_reaching_python_are_bounded`; medição manual abaixo |
| CA-15 | `repo` (`SELECT_LOT_SELECTION`) | `r/::test_lot_selection_sql_is_cut_in_the_database` |
| CA-16 | `repo` (`source = %(f_source)s`), `rt` | `r/::test_route_simulated_lots_never_enter_the_live_cut` |

Outros testes do autor: `r/::test_lot_selection_rejects_invalid_parameters`, `u/::test_max_excluded_lots_is_50`, `u/::test_select_lots_caps_are_keyword_only_and_required`, `u/::test_compute_new_parameters_are_keyword_only`.

**Mutação conferida:** sem `collate "C"` no SQL (o banco de teste é `en_US.utf8`), 6 testes de `r/` falham (`test_route_ties_use_the_c_collation`, os 4 `test_lot_selection_matches_select_lots` e o estático). O arquivo foi restaurado em seguida.

**Medição do cenário do CA-14** (script fora do repositório, no banco de teste local, 120 000 lotes de 1 inspeção e 600 lotes de 5, aquecimento com `source=simulated` antes do `tracemalloc`): 200, 100 pontos, 50 excluídos, `valid_lots_total = 600`, `excluded_lots_total = 120000`, corpo de 18 278 bytes, pico do `tracemalloc` de 0,25 MB e 1,1 s.

**Cobertura** (portão da SPEC-006 §4.3): `uv run pytest api/tests/test_spc.py --cov=qc_api.services` → `services/spc.py` 100% (83 statements).

## Testes de aceite de SPECs anteriores que falham (esperado; ajustes do tester, §3.1)

Não toquei em nenhum arquivo `**/tests/acceptance/**`. Com e sem banco, falham exatamente estes 4:

| Teste | Requisito que o invalida | Ajuste da §3.1 |
|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_002.py::test_ca16_response_models_json_round_trip[spc]` | §4.1: `model_dump(mode="json")` passa a trazer `max_points`, `valid_lots_total` e `excluded_lots_total` (`None`) | 3 |
| `packages/contracts/tests/acceptance/test_spec_002.py::test_ca16_response_models_json_round_trip[spc-empty]` | §4.1, idem | 3 |
| `packages/contracts/tests/acceptance/test_spec_023.py::test_ca01_contracts_version` | §4.1: `__version__ == "0.3.0"` (a asserção exata `== "0.2.0"` falha) | 1 |
| `packages/preprocess/tests/acceptance/test_spec_023.py::test_ca12_spec002_acceptance_suites_still_pass` | §4.1, em cascata: ele roda o `test_spec_002.py` do contrato em subprocesso (caminhos explícitos) e falha só pelos 2 casos acima | nenhum: volta a passar com o ajuste 3, sem mudar o arquivo |

O CA-28 da SPEC-004 (`api/tests/acceptance/test_spec_004.py::test_ca28_version_expectations_migrated`) **passa hoje**, porque ainda não existe `packages/contracts/tests/acceptance/test_spec_026.py`. Ele vai falhar quando o tester criar esse arquivo com `== "0.3.0"`, até o ajuste 2 (`ALLOWED_EXACT`). Os testes de aceite das SPECs 004, 006 e 014 passam sem mudança (inclusive `test_extra_naive_datetimes_are_not_silently_accepted` da SPEC-006, que aceita `ValueError`).

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest -q packages/contracts/tests api/tests/test_spc.py api/tests/test_filters.py
TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test \
  uv run pytest -q api/tests/test_spc_route.py
uv run pytest api/tests -q -m "not db" --cov=qc_api.services --cov-report=term-missing --cov-fail-under=80
```

Resultado da suíte inteira (`uv run pytest -q`), depois dos 3 commits:

- com `TEST_DATABASE_URL`: **4 failed, 2176 passed** (os 4 da tabela acima);
- sem `TEST_DATABASE_URL`: **4 failed, 1665 passed, 511 skipped** (os mesmos 4).

`ruff check .` e `ruff format --check .`: limpos (111 arquivos).

## Decisões tomadas dentro do escopo da SPEC

1. **`validate_selection_parameters`** (função pública em `services/spc.py`): concentra as regras do passo 1 da §4.2 (`baseline_lots < 1`, `min_lot_size < 1`, `max_points < 1`, `max_excluded < 0` → `ValueError`; `None` sempre vale). É usada por `select_lots`, por `build_p_chart` (com `max_excluded=None`) e por `lot_selection`, que valida **antes** de consultar: sem isso, um `limit` negativo viraria `DataError` do Postgres (SQLSTATE 2201W) e um 500 genérico. A rota não alcança esse caso (ela valida 2…500).
2. **`build_p_chart` valida `baseline_lots`, `min_lot_size` e `max_points`** com a mesma função, para nunca devolver uma resposta com parâmetros que o próprio serviço recusaria. Além disso, levanta `ValueError` com `baseline` vazio e `valid_lots_total >= 2`, como a §4.2 pede. Não verifico outras incoerências da seleção (ex.: `len(window) > max_points`), que a SPEC não pede.
3. **`LotCounts` com data que não é `datetime`** (ex.: uma string): `ValueError`, pela mesma checagem de fuso (`isinstance(datetime)` + `tzinfo` + `utcoffset()`). Sem isso, a checagem `value.tzinfo` levantaria `AttributeError`. Os tipos são conferidos antes das faixas, então `n="5"` vira `ValueError`, e não `TypeError` da comparação.
4. **`lot_selection` aceita `None` em `max_points` e `max_excluded`**, com o mesmo sentido de `select_lots` (sem teto; no SQL, `limit null`). A rota sempre passa inteiros. Isso deixa a função do repositório igual à referência para a SPEC-017.
5. **Forma da consulta:** uma instrução só, com a CTE `lots as materialized` e as quatro partes num `union all` de `select`s entre parênteses, marcadas pela coluna `part` (`totals`, `baseline`, `window`, `excluded`). A linha de totais tem colunas próprias (`valid_lots_total`, `excluded_lots_total`) e `null` nas de lote. As partes de janela e excluídos usam `order by started_at desc, lot_id collate "C" desc limit ...`, e um `order by part, started_at, lot_id collate "C"` externo devolve cada parte em ordem crescente (o Python só agrupa as linhas). Um teste conta as linhas: `baseline_lots + max_points + max_excluded + 1`.
6. **Constante `SPC_MIN_MAX_POINTS = 2`** na rota, ao lado de `SPC_DEFAULT_MAX_POINTS` e `SPC_MAX_MAX_POINTS`, no padrão de `SPC_MIN_BASELINE_LOTS`.
7. **`lot_counts` e `SELECT_LOT_COUNTS` removidos** (§3.1: "sai, se nada mais a usar"). Nenhum código nem teste os usava fora da rota.
8. **Testes do autor ajustados pela mudança de contrato:** `api/tests/test_spc_route.py::test_empty_database` (o corpo exato ganha os 3 campos), `api/tests/test_filters.py::test_openapi_documents_the_query_parameters` (`max_points` no conjunto de parâmetros) e `packages/contracts/tests/test_schemas.py` (os exemplos de round trip da `SpcResponse` passam a trazer os 3 campos; o JSON 0.2.0 ganhou um teste próprio).
9. **Credenciais nos testes:** nenhuma credencial ou chave como literal em URL, conninfo ou header nos testes novos. Os testes de rota reusam a chave de leitura `"r" * 32` e as fixtures de `api/tests/conftest.py`. Nenhum teste novo roda pytest em subprocesso.

Nenhuma variável de ambiente nova: `.env.example` não muda. Nenhuma dependência nova.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (com e sem banco)
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
