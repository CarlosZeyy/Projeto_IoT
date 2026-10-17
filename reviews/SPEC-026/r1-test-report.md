# SPEC-026 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-026](../../docs/specs/SPEC-026-spc-teto-de-lotes.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `f0855c3` (código de produção do autor: `0d35f5c`, `bc1fcc0`, `6d9c335`) |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir da SPEC, do ADR-017 e do `docs/architecture.md` §3.4 (caixa-preta), antes de ler a implementação. Depois li o diff para procurar o que os testes não pegariam e fiz uma checagem de mutação (abaixo).

Arquivos de aceite:

- `packages/contracts/tests/acceptance/test_spec_026.py`: CA-01 e CA-02 (29 testes);
- `api/tests/acceptance/test_spec_026.py`: CA-03 a CA-16 (273 testes; CA-10 a CA-14, CA-16 e os extras de rota marcados `db`; CA-14 também `slow`).

Total: **302 testes** (238 ligados a CAs e 64 exploratórios `test_extra_*`).

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `packages/contracts/tests/acceptance/test_spec_026.py::test_ca01_contracts_version_is_0_3_0`, `::test_ca01_pyproject_matches`, `::test_ca01_readme_history_row` | ✅ |
| CA-02 | `packages/contracts/tests/acceptance/test_spec_026.py::test_ca02_json_0_2_0_is_valid_with_none_cut_fields`, `::test_ca02_cut_values_round_trip`, `::test_ca02_invalid_cut_values_are_rejected[3 casos]`, `::test_ca02_fields_are_0_2_0_plus_cut_fields` | ✅ |
| CA-03 | `api/tests/acceptance/test_spec_026.py::test_ca03_lot_counts_rejects_wrong_types_and_naive_datetimes[6 casos]`, `::test_ca03_lot_counts_accepts_minus_three_hours` | ✅ |
| CA-04 | `::test_ca04_select_lots_cut_of_example_1`, `::test_ca04_select_lots_without_caps` | ✅ |
| CA-05 | `::test_ca05_cut_does_not_move_the_baseline` | ✅ |
| CA-06 | `::test_ca06_without_cut_is_the_spec_006_chart` | ✅ |
| CA-07 | `::test_ca07_few_lots_keep_the_totals` | ✅ |
| CA-08 | `::test_ca08_invalid_caps_raise[2 casos]`, `::test_ca08_max_excluded_zero_is_valid` | ✅ |
| CA-09 | `::test_ca09_cut_equals_uncut_chart_sliced[0..199]` (200 sementes), `::test_ca09_generator_covers_the_spec_space` (confere que o gerador tem empates, maiúsculas, minúsculas, `_`, `-` e tamanhos de 0 a ~300) | ✅ |
| CA-10 | `::test_ca10_route_small_volume` (`db`) | ✅ |
| CA-11 | `::test_ca11_route_cut` (`db`; corpo inteiro igual a `compute_p_chart(..., max_points=100, max_excluded=50).model_dump(mode="json")`, e `?max_points=10`) | ✅ |
| CA-12 | `::test_ca12_ties_use_the_c_collation` (`db`) | ✅ |
| CA-13 | `::test_ca13_invalid_max_points_is_422[1, 501, abc, 2.5]`, `::test_ca13_boundary_max_points_is_200[2, 500]`, `::test_ca13_missing_key_is_401_before_422` (`db`) | ✅ |
| CA-14 | `::test_ca14_memory_and_body_are_bounded` (`db`, `slow`; 120 000 + 600 lotes por `generate_series`, aquecimento com `source=simulated`, `tracemalloc` só na chamada) | ✅ |
| CA-15 | `::test_ca15_cut_is_in_the_sql` (lê os objetos SQL de módulo referenciados por `lot_selection` e pelas funções do módulo que ela chama) | ✅ |
| CA-16 | `::test_ca16_simulated_lots_never_enter_the_live_cut` (`db`) | ✅ |

## Ajustes autorizados em testes de aceite de SPECs anteriores (§3.1)

Commit próprio: `1d29394` (`test: adjust earlier acceptance tests to qc-contracts 0.3.0`). Nenhum CA mudou; a contagem de testes coletados nos 3 arquivos é a mesma antes e depois (165, 22 e 81, medida com `pytest --collect-only -q` em cada arquivo).

| # | Arquivo e teste | Antes | Depois | Base |
|---|---|---|---|---|
| 1 | `packages/contracts/tests/acceptance/test_spec_023.py::test_ca01_contracts_version` | `__version__ == "0.2.0"` e `version("qc-contracts") == "0.2.0"` | coerência `qc_contracts.__version__ == importlib.metadata.version("qc-contracts")`, `re.fullmatch(r"\d+\.\d+\.\d+", v)` e `(0, 2, 0) <= ... < (1, 0, 0)` | §3.1 item 1; `architecture.md` §10, "Expectativas de versão" |
| 2 | `api/tests/acceptance/test_spec_004.py`, `ALLOWED_EXACT` do CA-28 | `(SPEC023_CONTRACTS, "qc_contracts", "0.2.0")` | `(SPEC026_CONTRACTS, "qc_contracts", "0.3.0")`, com a constante nova `SPEC026_CONTRACTS = "packages/contracts/tests/acceptance/test_spec_026.py"` ao lado das outras. `VERSION_FILES` e as contagens não mudaram | §3.1 item 2 |
| 3 | `packages/contracts/tests/acceptance/test_spec_002.py::test_ca16_response_models_json_round_trip` | `model_dump(mode="json") == data` em todos os casos | só quando `model is SpcResponse` (os casos `spc` e `spc-empty`), o esperado é `data` mais `"max_points": None, "valid_lots_total": None, "excluded_lots_total": None`. `SPC_JSON` e `SPC_EMPTY_JSON` não mudaram, e os outros casos continuam comparando com `data` | §3.1 item 3 |

O 4º teste que o dev-report listava como falhando (`packages/preprocess/tests/acceptance/test_spec_023.py::test_ca12_spec002_acceptance_suites_still_pass`) voltou a passar com o ajuste 3, sem mudança no arquivo, como o dev-report previa.

## Suíte completa

```text
# com banco: TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
2482 passed, 1 warning in 324.96s (0:05:24)

# sem banco: uv run pytest -q (TEST_DATABASE_URL removida do ambiente)
1937 passed, 545 skipped, 1 warning in 173.97s (0:02:53)

# portão de cobertura (SPEC-006 §4.3, inalterado pela §4.5)
uv run pytest api/tests -q -m "not db" --cov=qc_api.services --cov-report=term-missing --cov-fail-under=80
api/src/qc_api/services/spc.py   83   0   100%
Required test coverage of 80% reached. Total coverage: 100.00%
504 passed, 357 deselected

uv run ruff check .            -> All checks passed!
uv run ruff format --check .   -> 113 files already formatted
```

O único aviso é o `StarletteDeprecationWarning` do `fastapi.testclient`, que já existia antes desta SPEC.

Conferência com o dev-report: ele registrou 4 falhas e 2176 aprovados com banco. Agora são 2482 = 2180 + 302 testes novos, sem falhas. Os testes de aceite das SPECs 002, 004, 006, 014 e 023 passam (Definição de pronto).

## Checagem de mutação (sem tocar no código de produção)

Rodei os testes `db and not slow` do meu arquivo com um plugin do pytest no scratchpad, fora do repositório. O plugin troca em memória o texto de `qc_api.repositories.inspections.SELECT_LOT_SELECTION`. O banco de teste usa collation `en_US.utf8`.

| Mutação | Testes de aceite que falham |
|---|---|
| sem `collate "C"` | 6: CA-12, extra de excluídos empatados, 4 extras de histórias aleatórias |
| janela pelos **primeiros** `max_points` | 8, inclusive CA-11 e CA-12 |
| excluídos pelos **primeiros** `max_excluded` | 5, inclusive CA-11 |
| base pelos **últimos** `baseline_lots` | 8, inclusive CA-10, CA-11 e CA-12 |

Todas as mutações foram detectadas.

## Medição do pior caso do SEC-06-01 (banco temporário)

O banco temporário `partqc_sec0601_probe_test` foi criado com `infra/migrations` e **apagado no fim**. Depois disso, só resta `partqc_test`. Usei a app real (`create_app` + `TestClient`), 1 000 000 de linhas por cenário, 5% dos lotes `simulated`, metade `screw` e metade `nut`, e 10% de defeitos, como no relatório do SEC-06-01. A chave de leitura foi gerada em tempo de execução, e a URL local não tem senha. Cada sonda rodou num processo novo. O "pico RSS" é o `ru_maxrss` do processo depois da chamada (cerca de 62,5 MB antes dela). O tempo do banco vem do `EXPLAIN ANALYZE` da consulta da rota.

| Cenário (1 M linhas) | Requisição | Tempo | Corpo | Pico `tracemalloc` | Pico RSS | Pontos / excluídos | Totais | Antes (SEC-06-01) |
|---|---|---|---|---|---|---|---|---|
| 2 000 lotes de 500 | padrão | 0,57 s | 20,5 KB | 0,22 MB | 63,3 MB | 100 / 0 | 1 900 / 0 | 0,52 s, 393 KB, 67 MB |
| idem | `max_points=500` | 0,50 s | 101,7 KB | 0,89 MB | 64,8 MB | 500 / 0 | 1 900 / 0 | — |
| 200 000 lotes de 5 | padrão | 2,38 s | 18,7 KB | 0,20 MB | 63,3 MB | 100 / 0 | 190 000 / 0 | 8,1 s, 34,6 MB, **405 MB** |
| idem | `max_points=500` | 2,55 s | 92,7 KB | 0,84 MB | 64,6 MB | 500 / 0 | 190 000 / 0 | — |
| 1 000 000 de lotes de 1 | padrão (`min_lot_size=5`) | 3,94 s | 1,6 KB | 0,08 MB | 62,8 MB | 0 / 50 | 0 / 950 000 | 19,5 s, 30,8 MB, **803 MB** |
| idem | `min_lot_size=1` | 5,20 s | 17,1 KB | 0,20 MB | 63,3 MB | 100 / 0 | 950 000 / 0 | 33,0 s, 159,5 MB, **1 724 MB** |
| idem | `min_lot_size=1&max_points=500&baseline_lots=100` | 5,25 s | 84,7 KB | 0,81 MB | 64,6 MB | 500 / 0 | 950 000 / 0 | — |

`EXPLAIN ANALYZE` da consulta: 0,53 s (2 000 lotes), 2,9 s (200 000 lotes), 4,2 s (1 M lotes, `min_lot_size=5`) e 5,3 s (1 M lotes, `min_lot_size=1`).

Conclusão:

- A memória e o corpo ficaram limitados, qualquer que seja o volume: o pico RSS ficou entre 62,8 e 64,8 MB, contra 803 MB e 1 724 MB antes, e o corpo máximo foi de 102 KB, com `max_points=500`.
- O tempo que sobra é quase todo do banco, como o ADR-017 aceita ("a agregação no banco continua linear"). Ele fica coberto pelo `statement_timeout` da SPEC-015. No pior caso, a agregação única com as 3 ordenações `limit` custa o mesmo que a agregação antiga (5,0 s medidos no SEC-06-01).
- O Python não segura mais o GIL por segundos.

O CA-14, com 120 600 lotes no banco de teste, passou com pico de `tracemalloc` abaixo de 20 MB e corpo abaixo de 64 KB, em 9,7 s (quase tudo é a carga dos dados).

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Os casos automatizados ficam em `test_extra_*`, nos dois arquivos de aceite, e todos passam. Os manuais estão marcados como tal.

| Caso | Resultado |
|---|---|
| Contrato: `max_points=1`, `valid_lots_total=0` e `excluded_lots_total=0` (limites inferiores) | aceitos |
| Contrato: `"abc"`, `1.5`, lista e objeto nos 3 campos | `ValidationError` |
| Contrato: `null` explícito nos 3 campos | `None` |
| Contrato: chave desconhecida (campo futuro) | ignorada (`extra="ignore"`) |
| Contrato, compatibilidade 0.2.0: corpo 0.3.0 sem os 3 campos | é um corpo 0.2.0 válido com os mesmos valores |
| `MAX_EXCLUDED_LOTS` | `50`, `int` |
| `LotSelection` | `frozen`, com os campos na ordem da §4.2 |
| Parâmetros novos de `compute_p_chart`, `select_lots`, `build_p_chart` e `lot_selection` | só por palavra-chave; padrões de `compute_p_chart` inalterados (20, 5, `LIVE`, `None`, `None`) |
| `select_lots` | não muta a entrada e ordena como `str` do Python (`0-1`, `B-1`, `_-1`, `a-1`) |
| `select_lots` com `baseline_lots=0`, `min_lot_size=0`, `max_points=-5` ou `max_excluded=-50` | `ValueError` |
| `build_p_chart` com `baseline=()` e `valid_lots_total=2` | `ValueError` (seleção incoerente) |
| `build_p_chart(select_lots(...))` | igual a `compute_p_chart`, inclusive com `source=simulated` |
| Teto maior que a história | mesma carta sem corte |
| História vazia | totais 0 e `(found 0)` |
| Serviço com `max_points=1` | aceito (só `< 1` falha; a rota exige 2) |
| `LotCounts` com `n` ou `defects` em `True`, `5.0`, `"5"` ou `None` | `ValueError` |
| `LotCounts` com `tzinfo` cujo `utcoffset()` é `None` | `ValueError` |
| `LotCounts` com subclasse de `int` | aceita |
| Módulo `spc.py` | continua sem `psycopg`, `logging`, `os`, `time` e `.now(` |
| Rota: `max_points` = `0`, `-1`, vazio, espaço, `1e2`, `99999999999999999999999`, `５` (dígito de largura total), `NaN` ou `inf` | 422 sem stack trace |
| Rota: chave de dispositivo com `max_points=501` | 401 antes do 422 |
| Rota: `max_points=500`, `baseline_lots=100` e `min_lot_size=1` sobre 190 lotes | todos os 190 pontos, totais 190 / 0 |
| Rota: 53 lotes pequenos com o mesmo `started_at` e `lot_id` mistos (`a-0`, `Z-0`, `_-0`, `0-0`…) | os 50 mantidos são os últimos na ordem `str`; corpo igual ao de `compute_p_chart` |
| Rota contra a referência, em 4 histórias aleatórias no banco (40 a 160 lotes, empates frequentes, alfabeto completo de `LOT_ID_PATTERN`, parâmetros sorteados) | corpo JSON idêntico ao de `compute_p_chart(..., max_excluded=50)` |
| Rota: `object_type=nut` com corte | só porcas, `valid_lots_total=5`; sem filtro, os 15 lotes e a janela correta |
| Rota: lote só com linhas `unknown` | fora dos pontos, dos excluídos e dos totais |
| Rota: banco vazio | totais 0, `max_points=100` e `(found 0)` |
| Rota: 4 chamadas repetidas com `max_points=37` | corpos idênticos byte a byte |
| `lot_selection` direto (pool próprio) contra `select_lots`, com tetos `7/3`, `7/0` e `None/None` | iguais (`limit null` = sem teto) |
| Rota sem banco com `max_points=50` | 503 `{"detail": "Database unavailable"}` |
| OpenAPI | `max_points` com `minimum` 2, `maximum` 500 e `default` 100; os 3 campos no schema `SpcResponse` |
| Manual: `max_points=+5`, `%205` (espaço), `05`, `1_0` e `10.0` | 200, com o valor convertido (5 ou 10); é o modo leniente do pydantic/FastAPI, igual aos outros parâmetros inteiros da API. Sem impacto: o valor fica sempre em 2…500. `true` dá 422 |
| Manual: `max_points=5&max_points=7` | 200, vale o último (7), comportamento padrão do FastAPI |
| Manual: pior caso do SEC-06-01 | ver a seção de medição |

## SPEC_ISSUE (se houver)

Nenhum.

## Observações para o reviewer (não são bugs)

- O CA-15 foi verificado pelos objetos SQL de módulo que `lot_selection` referencia (hoje, `SELECT_LOT_SELECTION`), e não por uma busca no arquivo inteiro. Assim, um SQL antigo esquecido no módulo não faz o teste passar sozinho.
- Entre os commits `1d29394` (ajustes) e o commit seguinte (testes de aceite), o CA-28 da SPEC-004 falharia isolado, porque o `ALLOWED_EXACT` já aponta para o arquivo `test_spec_026.py` do contrato, que só entra no commit seguinte. No `HEAD` da branch, tudo passa.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` (os 2 arquivos novos e os 3 ajustes autorizados pela §3.1) e este relatório.
- [x] Nenhuma credencial ou chave fictícia como literal em URL, conninfo ou header: as chaves e senhas são geradas em tempo de execução, e a URL do Postgres local não tem senha.
- [x] Nenhum teste novo roda o pytest em subprocesso.
- [x] O banco temporário da medição (`partqc_sec0601_probe_test`) foi apagado.
