# SPEC-044 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-044](../../docs/specs/SPEC-044-ferramentas-so-identificadas.md) |
| Rodada | r1 (Partes A e B) |
| Tester | tester |
| Commit testado | `e42c7d5` (código de produção e testes do autor até `f4c5772`; depois disso só `docs/`, e este commit de testes) |
| **Veredicto** | **PASS**: todos os CAs automatizados (CA-01 a CA-14) têm teste de aceite e passam (294 testes novos), os ajustes de aceites antigos da §3.1 (e os casos da §10 que ela não previu) estão feitos e registrados, a suíte inteira passa com `CI=true` e o banco de teste, e o ruff está limpo. Nenhum bug, nenhum SPEC_ISSUE. O CA-15 é manual, em produção, e fica **pendente** para depois do merge (não é falha). |

Os testes foram escritos a partir do texto da SPEC (§3.1, §4 e §5), em caixa-preta, antes da leitura da implementação; a leitura veio depois, só para os exploratórios de borda. Para os padrões de interface (fixtures de banco, modelo dummy, importador, `AppTest`, CLI do split), segui os aceites da SPEC-021, de que esta SPEC é extensão.

- Datasets todos sintéticos (`make_synthetic_dataset` e imagens geradas em memória), sempre em diretórios temporários; nada de `ml/data/` foi lido nem aberto; nenhuma imagem real (R-14).
- Chaves de dispositivo, tokens de sessão e marcadores gerados em tempo de execução (R-03).
- Fronteiras simuladas: só o HTTP do dashboard (`httpx.MockTransport`) e o relógio e o `sleep` do importador. Banco real (`partqc_test` no contêiner `partqc-pg`) na API, modelo dummy ONNX da SPEC-008 §6 (construído no teste) na borda, sem torch.
- O split roda pela CLI (`python -m qc_ml.split`, subprocesso); nenhum teste roda o pytest em subprocesso.
- CA-08, `capture.js`: além de conferir que os três valores e o `PREFIX_TYPES` estão no script servido, o teste avalia com o Node só as declarações do topo do script (de `"use strict";` até a primeira `function`, sem DOM) e confere que `PREFIX_TYPES.T` contém os três (e as 4 elétricas, e não `other` nem `screw`). Sem o Node no `PATH`, essa parte é omitida e a checagem estática continua; nesta máquina o Node existe (v20) e a avaliação rodou.

## Arquivos e contagem

| Arquivo | Testes coletados | Itens de CA (`test_caNN_*`, com parametrização) | Exploratórios (`test_extra_*`, com parametrização) |
|---|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_044.py` | 147 | 12 | 135 |
| `api/tests/acceptance/test_spec_044.py` | 23 | 10 | 13 |
| `edge/tests/acceptance/test_spec_044.py` | 67 | 14 | 53 |
| `dashboard/tests/acceptance/test_spec_044.py` | 14 | 5 | 9 |
| `ml/tests/acceptance/test_spec_044.py` | 43 | 13 | 30 |
| **Total** | **294** | **54** | **240** |

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `packages/contracts/tests/acceptance/test_spec_044.py::test_ca01_contracts_version_is_0_7_0` (`__version__ == metadata.version == "0.7.0"`), `::test_ca01_object_type_has_15_members_ending_with_the_new_tools`, `::test_ca01_new_tool_labels_pt`, `::test_ca01_grade_forbidden_group_is_exactly_the_eight_types`, `::test_ca01_three_groups_are_disjoint_and_sum_the_enum`, `::test_ca01_pyproject_and_readme_history` | ✅ |
| CA-02 | `packages/contracts/.../test_spec_044.py::test_ca02_new_tool_without_grade_is_accepted[hammer/wrench/spirit_level]`, `::test_ca02_new_tool_with_grade_is_rejected[…]` (`good`, `1.0`, `0.8`) | ✅ |
| CA-03 | `api/tests/acceptance/test_spec_044.py::test_ca03_database_accepts_exactly_the_contract_pairs` (15 tipos × 6 graus = 90 pares contra o `InspectionCreate` 0.7.0; 48 aceitos, os outros 42 com `23514`), `::test_ca03_migration_007_runs_again_without_changing_the_checks` (`pg_get_constraintdef` dos dois `check` igual depois de rodar a `007` mais duas vezes; `spirit_level` nos dois) | ✅ |
| CA-04 | `api/.../test_spec_044.py::test_ca04_post_hammer_without_grade_is_201`, `::test_ca04_post_hammer_with_grade_is_422_and_not_stored`, `::test_ca04_spc_leaves_the_wrench_lot_out` (`L-04` fora de `points` e de `excluded_lots`), `::test_ca04_spc_filter_by_wrench_is_422`, `::test_ca04_summary_counts_the_wrenches` (`by_object_type["wrench"] == 10`), `::test_ca04_list_filter_by_spirit_level_is_200`, `::test_ca04_openapi_spc_object_type_enum_is_the_spec016_one`, `::test_ca04_health_reports_contract_0_7_0` | ✅ |
| CA-05 | `edge/tests/acceptance/test_spec_044.py::test_ca05_model_with_hammer_and_empty_ungraded_list_is_refused` (modelo `screw`, `other`, `hammer`, sem `nut`), `::test_ca05_model_with_hammer_listed_as_ungraded_loads`, `::test_ca05_decision_of_a_hammer_has_no_grade` (`[0.05, 0.05, 0.90]`), `::test_ca05_capture_of_a_hammer_is_ungraded_with_pt_br_labels` (`OnnxInferencer` real; `approved` nulo, `sem grau`, `martelo`; payload do outbox válido no contrato) | ✅ |
| CA-06 | `edge/.../test_spec_044.py::test_ca06_spirit_level_without_grade_is_collected` (`raw/spirit_level/_/T-010__1__…`, 1 linha no manifest), `::test_ca06_hammer_with_grade_is_422_with_its_own_message` (`{"detail": "grade must be empty for an identification-only tool"}`, sem arquivo nem linha nova), `::test_ca06_hammer_with_o_prefix_is_422_and_nothing_written` (`O-012`), `::test_ca06_drill_with_grade_keeps_the_power_tool_message` (`T-013`) | ✅ |
| CA-07 | `edge/.../test_spec_044.py::test_ca07_hammer_without_grade_is_imported` (`T-601`, `c01`, saída 0, `raw/hammer/_/`), `::test_ca07_wrench_with_grade_refuses_the_whole_plan` (saída 2, `plan line 3: grade_on_other (grade)`, nada gravado), `::test_ca07_spirit_level_with_o_prefix_is_a_prefix_mismatch` (`O-603`: `item_prefix_mismatch (object_type)`) | ✅ |
| CA-08 | `edge/.../test_spec_044.py::test_ca08_capture_page_has_the_three_options` (os três `<option value="…">rótulo</option>` exatos), `::test_ca08_capture_script_has_the_three_in_the_t_prefix` (`/static/capture.js` servido), `::test_ca08_console_coverage_has_one_row_per_new_tool` (console por `http://127.0.0.1:<porta>/`; uma linha por tipo novo na `table#coverage`, com `sem grau`) | ✅ |
| CA-09 | `dashboard/tests/acceptance/test_spec_044.py::test_ca09_history_row_of_a_wrench_without_grade`, `::test_ca09_chart_order_has_each_of_the_15_types_once`, `::test_ca09_chart_colors_have_15_keys_and_15_distinct_colors`, `::test_ca09_history_type_filter_offers_the_new_labels` (`filters.TYPE_OPTIONS`), `::test_ca09_spc_type_filter_is_the_spec016_one` (`filters.SPC_OBJECT_TYPES` = `screw`, `nut` e as 5 manuais, o `SpcObjectType` do CA-05 da SPEC-016) | ✅ |
| CA-10 | `ml/tests/acceptance/test_spec_044.py::test_ca10_power_and_identified_tool_tuples`, `::test_ca10_new_tools_are_the_last_three_known_types`, `::test_ca10_new_tools_in_the_t_prefix_and_grade_forbidden`, `::test_ca10_tool_grade_coverage_keys_are_the_hand_tools` | ✅ |
| CA-11 | `ml/.../test_spec_044.py::test_ca11_new_tools_load_with_9_t_items_in_no_grade_dirs`, `::test_ca11_hammer_with_grade_is_grade_on_other`, `::test_ca11_power_tools_alone_are_still_12_t_items` | ✅ |
| CA-12 | `ml/.../test_spec_044.py::test_ca12_model_labels_end_with_the_new_tools_all_ungraded` (`object_types` termina em `hammer`, `wrench`, `spirit_level`; os três em `ungraded_object_types`; `grade_target("hammer", "good", labels) is None`) | ✅ |
| CA-13 | `ml/.../test_spec_044.py::test_ca13_extension_with_the_new_tools_exits_0`, `::test_ca13_each_new_tool_in_train_val_and_test` (6 peças por tipo, nenhuma em dois splits), `::test_ca13_no_small_stratum_warning_for_hammer_grades` (stdout, stderr e `split_v2.json`), `::test_ca13_split_v1_rows_keep_their_split` | ✅ |
| CA-14 | `ml/.../test_spec_044.py::test_ca14_defaults_are_byte_for_byte_the_same` | ✅ |
| CA-15 | manual, em produção, depois do merge (migração `007` no Supabase, `pg_get_constraintdef`, deploy do `partqc-api` e do `partqc-web`, `contract_version: "0.7.0"`, borda, `requeue`) | ⏳ **pendente** (humano com o security-devops, depois do merge; registrar data e resultado de cada passo, sem o subdomínio real). Não é falha desta rodada. |

## Ajustes em testes de aceite de SPECs anteriores (`docs/architecture.md` §10)

Os da §3.1 da SPEC-044 seguem a lista dela; os demais são os casos que a §3.1 não previu, todos listados pelos dois relatórios do autor, cada um consequência direta do requisito citado. Só as asserções afetadas mudaram (mais a constante `IDENTIFIED_044` no `edge/.../test_spec_010.py` e os comentários que citam a SPEC-044); nenhum `test_caNN_` foi removido nem renomeado; nenhum teste extra foi removido; um teste extra foi renomeado (linha marcada). O ajuste do `ALLOWED_EXACT` está no mesmo commit que cria `packages/contracts/tests/acceptance/test_spec_044.py`.

| Arquivo | Teste | Antes → depois | Requisito da SPEC-044 |
|---|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_021.py` | `test_ca01_contracts_version_is_0_6_0` | `__version__ == metadata.version == "0.6.0"` → forma de piso: `__version__ == metadata.version`, `X.Y.Z` e `(0, 6, 0) <= versão < (1, 0, 0)` | §3.1 ("as asserções exatas de `0.6.0` passam para a forma de piso"), CA-01; §10 "Expectativas de versão" |
| `api/tests/acceptance/test_spec_004.py` | `test_ca28_version_expectations_migrated` (`ALLOWED_EXACT`) | constante `SPEC021_CONTRACTS` (`…/test_spec_021.py`) → `SPEC044_CONTRACTS` (`…/test_spec_044.py`); par `(SPEC021_CONTRACTS, "qc_contracts", "0.6.0")` → `(SPEC044_CONTRACTS, "qc_contracts", "0.7.0")` | §3.1 ("o `ALLOWED_EXACT` passa a apontar para `test_spec_044.py` com `0.7.0`, no mesmo commit") |
| `packages/contracts/tests/acceptance/test_spec_021.py` | `test_ca01_last_four_object_types_are_the_power_tools_in_order` | `values[-4:] == POWER_TOOLS`, `values == ALL_TYPES` e `len(values) == 12` → `values[8:12] == POWER_TOOLS` e `values[:12] == ALL_TYPES` (as 4 elétricas logo depois de `phillips_screwdriver`, os 12 primeiros na ordem) | §3.1 ("a lista completa de 12 valores passa a conferir os 12 primeiros, nessa ordem"), CA-01 |
| `packages/contracts/tests/acceptance/test_spec_021.py` | `test_ca01_grade_forbidden_group_is_unknown_and_the_power_tools` | `{unknown, 4 elétricas} == GRADE_FORBIDDEN_OBJECT_TYPES` → `<=` (contém) | §3.1 ("passa a 'contém `unknown` e as 4 elétricas'") |
| `packages/contracts/tests/acceptance/test_spec_021.py` | `test_extra_three_groups_are_disjoint_and_sum_the_12_members` → **renomeado** `test_extra_three_groups_are_disjoint_and_sum_the_members` | `sum(len(g)) == 12` → `== len(ObjectType)` (docstring: "the members of `ObjectType`"); disjunção, união = enum e os outros dois grupos continuam | §4.1 ("os três grupos continuam disjuntos e somam os 15 membros"); o nome antigo descrevia a contagem substituída |
| `packages/contracts/tests/acceptance/test_spec_021.py` | `test_extra_earlier_labels_did_not_change` | `len(set(rótulos)) == 12` → `== len(ObjectType)` (um rótulo distinto por tipo); os 8 rótulos anteriores continuam conferidos | §3.1 (rótulos `martelo`, `chave de aperto`, `nível`) |
| `packages/contracts/tests/acceptance/test_spec_002.py` | `test_ca17_labels_match_enums_and_are_immutable[object_type]` | tabela esperada com 12 rótulos → mais `hammer: martelo`, `wrench: chave de aperto`, `spirit_level: nível` (como as SPECs 016 e 021 fizeram); as checagens não mudam | §3.1 (rótulos), CA-01 |
| `packages/preprocess/tests/acceptance/test_spec_023.py` | `test_ca12_spec002_acceptance_suites_still_pass` | nenhuma linha mudou: roda a suíte de aceite da SPEC-002 e volta a passar com o ajuste acima | indireto (§3.1) |
| `api/tests/acceptance/test_spec_005.py` | `test_ca08_summary_without_rows` | `len(by_object_type) == 3 + 5 + 4` → `== 3 + 5 + 4 + 3` (a igualdade com `{o.value: 0 for o in ObjectType}` não mudou) | §3.1 (`ObjectType` 0.7.0) |
| `api/tests/acceptance/test_spec_016.py` | `test_ca03_hammer_is_refused_with_23514` | valor fora do enum `hammer` → `lathe` (com grau `good` e nulo, `23514`); o nome do teste fica (um `test_caNN_` não é renomeado) | §4.2 (`hammer` entra no `check`); a intenção do CA-03 da SPEC-016 ("um valor fora do contrato é recusado com `23514`") continua verificada |
| `api/tests/acceptance/test_spec_016.py` | `test_ca04_post_tool_without_grade_and_read_it_back` | `GET /api/v1/inspections?object_type=hammer` → 422 passa a usar `object_type=lathe` → 422 | CA-04 da SPEC-044 (filtro por tipo novo é válido) |
| `api/tests/acceptance/test_spec_016.py` | `test_extra_invalid_tool_payloads_are_422_and_not_stored` | caso `payload(object_type="hammer")` (sem grau) → `payload(object_type="lathe")` | §4.1 (martelo sem grau é aceito) |
| `api/tests/acceptance/test_spec_016.py` | `test_extra_tool_migration_keeps_mvp_rows_and_runs_again` | o conjunto de migrações "pendentes junto com a de ferramentas" (`power_tool_object_types`) passa a incluir também `identified_tool_object_types` | §3.1 (nome `007_identified_tool_object_types.sql`, que também casa com `tool_object_types`) |
| `api/tests/acceptance/test_spec_021.py` | `test_extra_power_tool_migration_keeps_rows_and_runs_again` | "a `006` é a última, ou nenhuma posterior cita `object_type`" → também aceita uma posterior `*_identified_tool_object_types.sql` | §3.1 e §4.2 (a `007` amplia os mesmos `check`) |
| `edge/tests/acceptance/test_spec_010.py` | `test_ca15_compute_coverage_counts_images_and_items` | `len(cells) == 11 + 25 + 4` → `+ 3`; o conjunto esperado de chaves ganha `{(t, None) for t in IDENTIFIED_044}` (constante nova `IDENTIFIED_044` ao lado de `POWER_021`) | §4.3 (uma linha por tipo novo na cobertura) |
| `edge/tests/acceptance/test_spec_010.py` | `test_ca15_missing_manifest_is_an_empty_table` | `len(cells) == 11 + 25 + 4` → `+ 3` | §4.3 |
| `edge/tests/acceptance/test_spec_010.py` | `test_extra_compute_coverage_ignores_unknown_cells` | `len(cells) == 11 + 25 + 4` → `+ 3` | §4.3 |
| `edge/tests/acceptance/test_spec_016.py` | `test_extra_coverage_has_the_tool_rows` | `len(cells) == 11 + 25 + 4` → `sum(1 for t, _ in cells if t in TOOLS) == 25` (só as linhas que a SPEC-016 introduziu) | §3.1 ("uma asserção que fixe … a contagem de linhas de uma tabela passa a conferir só o que aquela SPEC introduziu") |
| `edge/tests/acceptance/test_spec_021.py` | `test_extra_coverage_has_one_row_per_power_tool` | `len(cells) == 11 + 25 + 4` → `sum(1 for t, _ in cells if t in POWER_TOOLS) == 4` | §3.1 (idem) |
| `dashboard/tests/acceptance/test_spec_013.py` | `test_extra_by_object_type_and_series_charts` | conjunto de barras do gráfico por tipo + `martelo`, `chave de aperto`, `nível` | §3.1 (dashboard: `OBJECT_TYPE_ORDER` com os três) |
| `dashboard/tests/acceptance/test_spec_029.py` | `test_ca01_spec013_suite_passes_and_hides_key_with_local_secrets` | nenhuma linha mudou: roda a suíte de aceite da SPEC-013 e volta a passar com o ajuste acima | indireto (§3.1) |
| `dashboard/tests/acceptance/test_spec_016.py` | `test_extra_object_type_order_and_colors` | `[t for t in order if t not in power] == [screw, nut, *TOOLS, unknown]` → `[t … if t not in power and t in spec016] == spec016` (só a ordem relativa dos 8 tipos da SPEC-016) | §3.1 ("a lista completa … de um gráfico passa a conferir só o que aquela SPEC introduziu") |
| `dashboard/tests/acceptance/test_spec_021.py` | `test_extra_object_type_label_covers_the_12_types` | `len(ObjectType) == 12` → os 12 tipos da SPEC-021 estão no enum (`<=`); a checagem do rótulo de cada membro não mudou | §3.1 ("a contagem de 12 tipos") |
| `dashboard/tests/acceptance/test_spec_021.py` | `test_extra_chart_order_and_distinct_colors_with_the_power_tools` | `len(order) == 12` → `len(order) == len(set(order))` (cada tipo uma vez); `[t … if t not in POWER_TOOLS] == earlier` → `[t … if t in earlier] == earlier`; as elétricas juntas depois das manuais e as cores distintas continuam | §3.1 (contagem de 12 tipos; lista completa de um gráfico) |
| `ml/tests/acceptance/test_spec_021.py` | `test_extra_known_types_and_hand_tool_group` | `(12 tipos) == KNOWN_OBJECT_TYPES` → `== tuple(KNOWN_OBJECT_TYPES)[:12]` | §3.1 Parte B (`KNOWN_OBJECT_TYPES` com as três novas no fim; "a lista completa de tipos passa a conferir só o que aquela SPEC introduziu") |

Nenhuma asserção com a mensagem `grade must be empty for a power tool` precisou de ajuste: a mensagem das elétricas não mudou (§4.3) e o CA-06 desta SPEC confere que continua.

## Suíte completa

Executada em 2026-11-04, no commit `e42c7d5` mais os testes de aceite deste commit, sem o extra `train`, com `CI=true` e `TEST_DATABASE_URL` apontando para o `partqc_test` do contêiner local `partqc-pg` (uma única suíte com banco por vez):

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
11032 passed, 167 skipped, 1 warning in 1047.06s (0:17:27)

Pulos (todos por ambiente, previstos em docs/architecture.md §10):
  108  PARTQC_DOCKER_TESTS=1 (workflow docker)
   49  torch ausente (extra train)
    6  PARTQC_MQTT_TESTS=1 (mosquitto)
    1  PARTQC_TELEMETRY_TESTS=1
    3  modelo real fora do Git (QC_REAL_MODEL_DIR / ml/models/*/model.onnx)
Aviso: StarletteDeprecationWarning do fastapi.testclient (preexistente).

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
332 files already formatted
```

Comparação com o dev-report: na execução do autor (Parte A, antes da Parte B) havia 36 falhas e 3 erros, todos em aceites antigos previstos ou em `ml/` sem a Parte B; com a Parte B e os ajustes da tabela acima, nenhuma falha.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Todos automatizados nos `test_spec_044.py` (`test_extra_*`) e passando.

- **Contrato:** matriz da invariante dos 15 tipos × 6 graus (90 pares); `InspectionRead` com a mesma regra para os três; qualquer campo de grau isolado (`grade_score`, `grade_confidence`, só `grade`) recusado; mensagens de erro sem valores do payload (lote, grau, tipo); variantes recusadas (`Hammer`, `HAMMER`, `hammer `, `spirit-level`, `spiritlevel`, `level`, `martelo`, `nível`, `chave de aperto`, `Wrench`, `wrenches`); ida e volta JSON; os 12 rótulos anteriores iguais e 15 rótulos distintos; `Grade` e `is_defective` sem mudança.
- **Banco e API:** forma da `007` (bloco `DO`, sem `BEGIN`/`COMMIT`, sem credencial, os dois nomes de restrição, os 15 valores); banco separado (`partqc_test_spec044_*`) com as migrações até a `006`, linhas antigas, `hammer` recusado, depois a `007`: linhas antigas mantidas (16), os três sem grau aceitos e com grau recusados, `007` rodada de novo sem mudar `pg_get_constraintdef`, `apply_migrations` de novo vazio; variantes (`Hammer`, `level`, `spirit-level`, `lathe`, `martelo`) recusadas com `CheckViolation`; `is_defective` falso para `wrench`; filtro do SPC por cada tipo novo é 422 sem traceback; payloads com campo de grau e lote em batch com um item inválido recusados inteiros; batch idempotente (R-05), inclusive reenvio individual (`duplicate`); resumo com 15 chaves e taxa de defeito só dos graduados; `defect_rate` nulo filtrando por `spirit_level`; série temporal ignora os tipos novos na taxa; tipos novos dentro de um lote de parafusos não mudam o `n` do SPC nem tiram um lote pequeno de `excluded_lots`; registro simulado continua `simulated` (R-06); filtros por cada tipo novo e variantes 422.
- **Borda:** cada tipo novo exige estar em `ungraded_object_types` (ausente ou `[]` → `ModelLoadError`); modelo com os 15 tipos exige as 7 ferramentas sem grau; listas inválidas (`Hammer`, repetido, fora de `object_types`, com `screw`, `level`); decisão ignora a probabilidade de `unusable` e um tipo abaixo do limiar vira `unknown`; captura de cada tipo novo com `approved` nulo, `sem grau` e o rótulo PT-BR; coleta de cada tipo em `raw/<tipo>/_/`; os 5 graus × 3 tipos com a mensagem nova (15 casos); `other` com a mensagem dele; grau só com espaço ou `sem grau`, prefixos `S`, `N`, `XT` pela coleta, variantes de tipo: 422 sem gravar; peça não muda de tipo (409); opções do seletor depois das elétricas, na ordem; cobertura com uma célula por tipo novo, sem células com grau, depois das elétricas; linhas do console exatamente `[rótulo, "sem grau", "0/90", "0/6"]` e o texto das metas com "(mínimo 3)"; importação com `T-` e `XT-` de cada tipo; problemas do plano (`XT-` com grau, prefixos `S`/`XS`, caixa); `--dry-run` não grava e a importação repetida é idempotente.
- **Dashboard:** histórico e rótulo de cada tipo novo; ordem do gráfico (os três juntos, depois das elétricas, antes de `unknown`, ordem relativa anterior mantida); cores novas em `#rrggbb` e diferentes das 12 anteriores; CSV do histórico com `nível`; gráfico por tipo com as barras novas; página de histórico com os três e a origem simulada visível (R-06); filtro do SPC na página sem nenhum tipo novo.
- **ML:** união elétricas + identificadas = grupo sem grau do contrato menos `unknown`; `build_data_report` mantém a cobertura só das manuais; qualquer grau em qualquer tipo novo → `grade_on_other` (15 casos); tipo novo com prefixo `S`/`N`/`O` → `item_prefix_mismatch`; linhas novas depois de todas as anteriores, numeração `T-` depois das elétricas; `XT-` externas sem grau e o registro `external_sources.csv` gravado; sem imagens de `hammer` no treino, ele sai dos tipos do modelo; elétricas e identificadas juntas, todas sem grau; contagens inválidas do gerador (`-1`, `1.5`, `"3"`) recusadas; extensão com só 2 martelos recusada (saída 2, `hammer` na stderr, nada gravado); `qc_ml.plots.type_label_pt` com os três rótulos (sem mudança de código, como a §3.1 pede).

Observações (sem bug):

- `api/tests/acceptance/test_spec_016.py::test_extra_tool_migration_keeps_mvp_rows_and_runs_again` ainda insere `hammer` com grau `good` esperando `CheckViolation`; continua passando, agora pelo `check` de grau e não pelo de valores. Não foi alterado porque não falha (a §10 só permite ajustar as asserções afetadas); fica o registro para o reviewer.
- O nome `test_ca01_last_four_object_types_are_the_power_tools_in_order` (SPEC-021) já não descreve a posição das elétricas (agora são as posições 9 a 12, não as 4 últimas); não foi renomeado porque um `test_caNN_` nunca é renomeado.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
- [x] Nenhuma foto de `ml/data/` aberta; nenhum acesso ao Supabase de produção nem à VPS.

