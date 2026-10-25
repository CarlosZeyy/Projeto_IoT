# SPEC-016 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-016](../../docs/specs/SPEC-016-ferramentas-manuais.md) |
| Rodada | r1 |
| Autor | developer (Parte A); a Parte B (ml-engineer) é acrescentada no fim deste arquivo |
| Branch | `spec/SPEC-016-ferramentas-manuais` |
| Commits | `fb6383e` (contracts), `a9a875b` (infra), `7fab41e` (api), `00d4cc9` (edge), `7249839` (dashboard) e o commit deste relatório |

## Parte A (developer)

### Resumo

- `qc-contracts` **0.4.0** (minor, ADR-021): `ObjectType` ganha as 5 ferramentas manuais depois dos membros atuais, com rótulos PT-BR; os grupos `GRADE_REQUIRED_OBJECT_TYPES`, `GRADE_FORBIDDEN_OBJECT_TYPES` e `GRADE_OPTIONAL_OBJECT_TYPES` (`frozenset[ObjectType]`, na raiz); a invariante de `_InspectionBase` segue os grupos, com mensagens sem valores. `pyproject.toml`, `__version__`, `uv.lock` e o histórico do `README.md` atualizados.
- Banco: `infra/migrations/003_tool_object_types.sql` (idempotente, um bloco `DO`) troca o `check` de `object_type` pelos 8 valores e o `check` de grau pelo equivalente da invariante. `is_defective` não muda.
- API: o SPC (`lot_selection`) e a taxa de defeito (resumo e série temporal) passam a contar só `grade is not null`; `unknown_count` não muda; `SpcObjectType` é uma `StrEnum` declarada com `screw`, `nut` e as 5 ferramentas.
- Borda: `labels.json.ungraded_object_types` lido e validado; decisão sem grau para esses tipos; captura com `approved = null` e `verdict = "sem grau"`; coleta, página e importação aceitam as ferramentas com `T-`/`XT-` e grau obrigatório; a tabela de cobertura do console ganha as 25 linhas das ferramentas. `edge/README.md` atualizado.
- Dashboard: "sem grau" no histórico (e no CSV), ordem e cores das ferramentas no gráfico por tipo e o filtro de tipo da carta p com os membros de `SpcObjectType`.

### Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `packages/contracts/src/qc_contracts/{enums,labels,__init__}.py`, `packages/contracts/pyproject.toml`, `packages/contracts/README.md`, `uv.lock` | `packages/contracts/tests/test_smoke.py::test_import_and_version`, `::test_readme_has_version_history_row`; `test_enums.py::test_enum_values`, `::test_grade_groups`, `::test_grade_groups_partition_object_type`; `test_labels.py::test_one_label_per_member` |
| CA-02 | `packages/contracts/src/qc_contracts/schemas.py` (`_InspectionBase._check_grade_invariants`) | `packages/contracts/tests/test_schemas.py::test_grade_optional_type_accepts_null_grade`, `::test_grade_optional_type_accepts_a_grade`, `::test_grade_required_type_without_grade_rejected`, `::test_unknown_with_grade_rejected`, `::test_grade_optional_type_keeps_the_null_together_rule`, `::test_invariant_follows_the_grade_groups` (8 tipos × 6 graus), `::test_invariant_messages_carry_no_values`, `::test_inspection_read_accepts_a_tool_without_grade` |
| CA-03 | `infra/migrations/003_tool_object_types.sql` | `infra/tests/test_schema_db.py::test_grade_groups_check_mirrors_the_contract` (48 pares contra `InspectionCreate`), `::test_values_outside_the_contract_are_refused` (`hammer` e outros, `23514`), `::test_grade_check_equals_the_spec_expression_on_the_enum`, `::test_tool_migration_runs_again_without_error`, `::test_tool_migration_keeps_mvp_rows_valid`; `infra/tests/test_migration_files.py::test_repository_migrations_are_valid` |
| CA-04 | (sem código novo nas rotas de escrita; contrato 0.4.0) | `api/tests/test_tools.py::test_post_tool_without_grade_is_created_and_listed`, `::test_post_every_tool_with_a_grade`, `::test_batch_with_tools`, `::test_unknown_object_type_filter_is_422`, `::test_post_invalid_tool_combinations_are_422` |
| CA-05 | `api/src/qc_api/repositories/inspections.py` (`lot_selection`), `api/src/qc_api/routers/metrics.py` (`SpcObjectType`) | `api/tests/test_tools.py::test_spc_counts_only_graded_inspections`, `::test_spc_filter_by_a_tool_without_grade_is_empty`, `::test_spc_filter_by_a_graded_tool`, `::test_spc_filter_outside_the_enum_is_422`, `::test_lot_selection_leaves_out_tools_without_grade`, `::test_openapi_lists_the_declared_spc_enum`, `::test_spc_object_type_is_a_declared_enum`, `::test_spc_object_type_is_the_graded_groups_of_the_contract`; `api/tests/test_filters.py::test_openapi_documents_the_spc_parameters` |
| CA-06 | `api/src/qc_api/repositories/inspections.py` (`SELECT_SUMMARY`, `SELECT_TIMESERIES`) | `api/tests/test_tools.py::test_summary_defect_rate_counts_only_graded`, `::test_summary_of_tools_without_grade_has_null_rate`, `::test_timeseries_defect_rate_counts_only_graded`, `::test_timeseries_bucket_of_tools_without_grade_has_null_rate`, `::test_lot_summary_is_unchanged_by_the_rule` |
| CA-07 | `edge/src/qc_edge/onnx_inferencer.py` (`_load_labels`, `_ungraded_object_types`) | `edge/tests/test_tools.py::test_labels_with_valid_ungraded_types_load`, `::test_labels_with_invalid_ungraded_types_are_refused` (12 casos, inclusive os 5 do CA), `::test_labels_ungraded_with_every_tool`, `::test_labels_unknown_key_is_still_refused` |
| CA-08 | `edge/src/qc_edge/decision.py` (`ModelLabels.ungraded_object_types`, `decide`) | `edge/tests/test_tools.py::test_ungraded_tool_has_no_grade_and_no_review`, `::test_ungraded_tool_with_low_margin_needs_review`, `::test_graded_tool_follows_the_grade_rule`, `::test_ungraded_tool_ignores_a_low_grade_confidence`, `::test_ungraded_tool_below_the_threshold_is_unknown`, `::test_decisions_are_valid_contract_payloads` |
| CA-09 | `edge/src/qc_edge/app.py` (`_verdict`, `VERDICT_UNGRADED`) | `edge/tests/test_tools.py::test_capture_of_an_ungraded_tool_goes_to_the_outbox` (modelo dummy + `SqliteOutbox`), `::test_tool_verdicts`, `::test_console_row_of_an_ungraded_tool` |
| CA-10 | `edge/src/qc_edge/collect.py` (`DatasetObjectType`, `ITEM_PREFIX_TYPES`, `item_prefix_matches`, `GRADED_DATASET_TYPES`, cobertura), `edge/src/qc_edge/app.py` (seletor), `edge/src/qc_edge/static/capture.js` | `edge/tests/test_tools.py::test_collect_of_a_tool_through_the_route`, `::test_collect_selector_offers_the_tools`; `edge/tests/test_collect.py::test_invalid_fields` (casos novos de `T-`), `::test_every_tool_with_t_prefix_and_grade_is_valid`, `::test_tool_capture_goes_to_its_grade_directory`, `::test_coverage_counts_tool_rows`, `::test_tool_types_mirror_the_contract`, `::test_item_prefix_matches`; `edge/tests/test_collect_route.py::test_console_coverage_without_manifest` |
| CA-11 | `edge/src/qc_edge/importer.py` (`CONTRIBUTOR_ITEM_PATTERN`, `EXTERNAL_ITEM_PATTERN`, `_object_type_problem`, `_grade_problem`) | `edge/tests/test_importer.py::test_tools_are_imported_with_t_and_xt`, `::test_every_tool_is_accepted_with_t`, `::test_xt_with_screw_is_refused_and_nothing_is_written`, `::test_contributor_row_problems` e `::test_external_row_problems` (casos `tool-*` e `ext-tool-*`) |
| CA-12 | `dashboard/src/qc_dashboard/formatting.py` (`inspection_grade_label`), `dashboard/src/qc_dashboard/charts.py`, `dashboard/src/qc_dashboard/filters.py` (`SPC_OBJECT_TYPES`), `dashboard/views/controle_estatistico.py` | `dashboard/tests/test_formatting.py::test_history_rows_of_tools_with_and_without_grade`, `::test_object_type_label_of_the_tools`, `::test_history_csv_writes_sem_grau_for_a_tool`; `dashboard/tests/test_charts.py::test_by_object_type_is_horizontal`, `::test_object_type_order_and_colors_cover_every_type`, `::test_by_object_type_counts_tools`; `dashboard/tests/test_filters_data.py::test_spc_object_types_are_the_graded_groups_of_the_contract`; `dashboard/tests/test_pages.py::test_spc_type_and_max_points`, `::test_spc_type_tool_is_sent_to_the_api` |

### Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
# só a Parte A, sem os aceites:
CI=true TEST_DATABASE_URL=... uv run pytest -q packages/contracts/tests infra/tests api/tests edge/tests dashboard/tests \
    --ignore=packages/contracts/tests/acceptance --ignore=infra/tests/acceptance \
    --ignore=api/tests/acceptance --ignore=edge/tests/acceptance --ignore=dashboard/tests/acceptance
```

Resultado da suíte completa (sem o extra `train`, com o `partqc_test`): **15 failed, 6828 passed, 56 skipped**. As 15 falhas são todas testes de aceite antigos que esta SPEC invalida de propósito (tabela abaixo); todos os testes do autor passam.

### Testes de aceite antigos que precisam de ajuste (`docs/architecture.md` §10; quem ajusta é o tester)

| Arquivo | Teste | O que falha | Requisito da SPEC-016 | Na §3.1? |
|---|---|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_026.py` | `test_ca01_contracts_version_is_0_3_0` | `0.4.0 != 0.3.0`; junto, o par do `qc-contracts` no `ALLOWED_EXACT` do CA-28 da SPEC-004 (`api/tests/acceptance/test_spec_004.py`) passa a ser `test_spec_016.py`/`0.4.0` | §4.1 (versão), "Expectativas de versão" | sim |
| `packages/contracts/tests/acceptance/test_spec_002.py` | `test_ca02_enum_values_grade_order_and_patterns` | `[m.value for m in ObjectType] == ["screw", "nut", "unknown"]` | §4.1 (`ObjectType` ganha as 5 ferramentas, depois dos membros atuais) | não |
| `packages/contracts/tests/acceptance/test_spec_002.py` | `test_ca17_labels_match_enums_and_are_immutable[object_type]` | `KeyError: 'pliers'` (a tabela esperada tem só os 3 rótulos do MVP) | §4.1 (`OBJECT_TYPE_LABELS_PT` das ferramentas) | não |
| `packages/preprocess/tests/acceptance/test_spec_023.py` | `test_ca12_spec002_acceptance_suites_still_pass` | roda a suíte de aceite da SPEC-002 em subprocesso e herda as 2 falhas acima; volta a passar quando o `test_spec_002.py` for ajustado | §4.1 (indireto) | não |
| `api/tests/acceptance/test_spec_005.py` | `test_ca06_summary_without_filters`, `test_ca08_summary_without_rows` | `by_object_type` tem as 8 chaves do enum (a SPEC-005 exige toda chave do enum, com 0 quando ausente) | §4.1 (`ObjectType` 0.4.0) | não |
| `edge/tests/acceptance/test_spec_008.py` | `test_ca10_invalid_labels[pliers]` | `pliers` agora é um valor válido do `labels.json` | §4.1/§4.4 (usar um valor fora do contrato, ex.: `"hammer"`) | sim |
| `edge/tests/acceptance/test_spec_010.py` | `test_ca15_compute_coverage_counts_images_and_items`, `test_ca15_missing_manifest_is_an_empty_table` | a tabela de cobertura tem 36 células (11 + 5 ferramentas × 5 graus), não 11 | §4.4 ("A tabela de cobertura do console ganha as linhas das ferramentas (5 graus cada)") | não |
| `edge/tests/acceptance/test_spec_010.py` | `test_extra_compute_coverage_ignores_unknown_cells` | `T-001` `pliers` `good` deixou de ser "célula desconhecida": é contado, e a tabela tem 36 células | §4.4 (coleta e cobertura das ferramentas) | sim (caso de `T-001` com `pliers`) |
| `edge/tests/acceptance/test_spec_036.py` | `test_ca04_invalid_plan_is_refused_and_nothing_written[item_tool]` e `[item_external_tool]` | `T-001`/`XT-0001` com `other` agora dão `item_prefix_mismatch (object_type)`, não `tools_not_supported (item_id)` (o código deixou de existir); a recusa com saída 2 e nada gravado continua | §4.4 ("Importação ... aceita os tipos de ferramenta com `T-` ... e `XT-`") e CA-11 ("o problema de prefixo da SPEC-036") | não |
| `dashboard/tests/acceptance/test_spec_013.py` | `test_extra_spc_controls_never_offer_all_or_unknown` | o filtro de tipo da carta p tem `Todos`, `parafuso`, `porca` e as 5 ferramentas (continua sem `desconhecido`) | §4.5 (filtro com os membros de `SpcObjectType`) | não |
| `dashboard/tests/acceptance/test_spec_013.py` | `test_extra_by_object_type_and_series_charts` | as barras do gráfico por tipo incluem as 5 ferramentas | §4.5 (`OBJECT_TYPE_ORDER` e cores com as ferramentas) | não |
| `dashboard/tests/acceptance/test_spec_029.py` | `test_ca01_spec013_suite_passes_and_hides_key_with_local_secrets` | roda a suíte de aceite da SPEC-013 em subprocesso e herda as 2 falhas acima | §4.5 (indireto) | não |

Os testes da §3.1 para `ml/tests/acceptance/` (SPEC-011, 012, 035) não falham agora, porque a Parte B ainda não mudou o `qc-ml`. O `api/tests/acceptance/test_spec_006.py` não fixa os membros do enum do filtro e passa sem ajuste, assim como os das SPECs 005 (salvo os dois acima), 006 e 026 sobre SPC e taxa de defeito (§7).

### Decisões tomadas dentro do escopo da SPEC

1. **`check` de grau no banco (§4.2).** A restrição mantém o nome `inspections_grade_null_iff_unknown` (o nome que a SPEC-003 e os testes conhecem; a migração troca só a expressão) e foi escrita como duas implicações: `(object_type not in ('screw','nut') or grade is not null) and (object_type <> 'unknown' or grade is null)`. Para os 8 valores que `inspections_object_type_check` aceita, ela dá exatamente o resultado da expressão da §4.2, e o teste `test_grade_check_equals_the_spec_expression_on_the_enum` compara as duas expressões no Postgres para os 48 pares. A forma literal da §4.2 também recusaria um valor fora do enum, e com isso o Postgres acusaria a restrição de grau antes da de `object_type` (as `check` são avaliadas pela ordem do nome): o CA-06 da SPEC-003 (`bolt` → `inspections_object_type_check`) passaria a falhar. Com as implicações, um valor fora do enum continua recusado só por `inspections_object_type_check` (SQLSTATE `23514` nos dois casos).
2. **Metas das células de ferramenta na cobertura (§4.4).** A SPEC pede as linhas das ferramentas (5 graus cada), sem dizer a meta de cada célula. Usei o critério de grau da §4.6/§3.3 (60 imagens de 5 peças por grau, `TOOL_GRADE_TARGET_*` em `qc_edge.collect`), que é a única meta por (tipo, grau) da SPEC. A meta de identificação (90 imagens e 6 peças por ferramenta, mínimo 3) é por tipo e aparece só no texto acima da tabela e no `edge/README.md`.
3. **Ordem.** Cobertura e seletor da coleta: parafuso, porca, as 5 ferramentas (na ordem do contrato) e "outro" por último. `DatasetObjectType` segue a ordem do modelo da §4.8 (`screw`, `nut`, `other`, ferramentas). Gráfico por tipo do dashboard: parafuso, porca, ferramentas, desconhecido (§4.5).
4. **Filtro de tipo da carta p no dashboard (§4.5).** O dashboard não importa `qc_api` (R-12 e ADR-007), então `qc_dashboard.filters.SPC_OBJECT_TYPES` declara a mesma lista. Dois testes a amarram aos grupos do contrato (grau obrigatório ∪ grau opcional, na ordem do `ObjectType`), um no dashboard e outro na API para o `SpcObjectType`; assim as duas listas não divergem sem um teste falhar.
5. **"sem grau" fora do mínimo da SPEC.** Além de `history_rows` (§4.5), o CSV do histórico também escreve `sem grau` (é o download da mesma tabela), e a tabela de últimas inspeções do console da borda mostra `sem grau` no lugar de `—` para uma ferramenta sem grau.
6. **`ungraded_object_types` com `null` explícito** é recusado (não é lista). Todas as mensagens de erro do `labels.json` citam a regra, nunca o valor. A checagem "falta um tipo de `GRADE_FORBIDDEN_OBJECT_TYPES` presente em `object_types`" está implementada, mas é inalcançável na 0.4.0 (`unknown` nunca pode estar em `object_types`); vale para a SPEC-021.
7. **Importação.** O código `tools_not_supported` deixou de existir (as ferramentas são aceitas). `T-`/`XT-` com tipo que não é ferramenta, e ferramenta com `S-`/`N-`/`O-`, dão `item_prefix_mismatch (object_type)`; o grau é obrigatório para as ferramentas (`missing_grade`), como na coleta.
8. **`ModelLabels`** ganhou `ungraded_object_types: tuple[str, ...] = ()` e normaliza listas para tuplas no `__post_init__` (os CAs podem montar o objeto com listas). O ajudante `edge/tests/dummy_model.py` (fora de `acceptance/`, usado também pelos aceites) ganhou o parâmetro opcional `ungraded_object_types` em `write_model_dir`, sem mudar o comportamento padrão.
9. **Local do teste de equivalência contrato × banco.** Ficou em `infra/tests/test_schema_db.py`, ao lado dos testes de esquema da SPEC-003 e da SPEC-027 (mesmas fixtures), e não em `api/tests/`.
10. **`capture.js`.** A regra de prefixo do celular aceita `T-` com as 5 ferramentas (199 linhas, dentro do limite de 200 dos testes da SPEC-010).
11. A versão da `qc-api` não mudou (a SPEC não pede); o `/api/v1/health` passa a mostrar `contract_version = 0.4.0`. Nenhuma dependência nova; nenhuma variável de ambiente nova (`.env.example` sem mudança).

### SPEC_ISSUE (se houver)

Nenhum. A decisão 1 usa uma forma equivalente (no domínio que o `check` de `object_type` admite, conferida por teste) da expressão literal da §4.2; se o reviewer entender que a §4.2 exige a forma literal, o efeito é só o nome da restrição acusada para um valor fora do enum, e o CA-06 da SPEC-003 precisaria de ajuste.

### Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (contracts, infra, api, edge e dashboard; suíte completa com banco: só as 15 falhas de aceite listadas acima)
- [x] `.env.example` atualizado (se houver variável nova): nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nada em `ml/` alterado (Parte B do ml-engineer)

## Parte B (ml-engineer)

| Campo | Valor |
|---|---|
| Autor | ml-engineer |
| Commits | `ba35ae3` (dados e gerador), `e25c928` (split), `60f7bc1` (modelo, limiares, avaliação, export, CHANGELOG e fixture), `0e412ef` (README) e o commit desta seção |

### Resumo

- **Dados (§4.6):** `KNOWN_OBJECT_TYPES` = `screw`, `nut`, `other` e as 5 ferramentas; `TOOL_OBJECT_TYPES` vem do contrato (`GRADE_OPTIONAL_OBJECT_TYPES`, na ordem do `ObjectType`). O prefixo `T` (e `XT`) exige uma ferramenta (`item_prefix_matches`); o grau é obrigatório para as ferramentas. `tool_grade_coverage(df)` aplica o critério (≥ 60 imagens de ≥ 5 peças em cada grau, só não externas e não excluídas) e o relatório de dados ganha a chave `tool_grade_coverage`.
- **Split (§4.7, ADR-022):** `--extend-test-types` e `--defer-types`; `type_decision_problems` faz as checagens (tipo novo sem decisão, tipo listado que não é novo, tipo nas duas listas, valor desconhecido, menos de 3 peças não externas) e a CLI imprime uma linha por problema e sai com 2 sem gravar nada. A extensão usa o procedimento do `split_v1`; o adiamento tira as imagens do CSV. `split_v<N>.json` ganha `test_extended_types` e `deferred_types`. `assign_splits`/`rows_for` ignoram as imagens de um tipo sem linha no split, com o aviso `deferred type images: <tipo>: <n>` no log.
- **Modelo (§4.8):** `derive_model_labels(df, train_rows)` e `grade_target(object_type, grade, labels)` (funções puras em `qc_ml.data`, sem torch). `ModelLabels` ganha `ungraded_object_types`; o `labels.json` do export e o `training_config.json` passam a tê-lo. `FU(t)` conta todos os tipos menos `other`; `unusable_threshold` e `grade_review_threshold` só `screw`/`nut`. `metrics.json` ganha `tool_grade_metrics` e os avisos `few test items for <tipo>: <n>`. O CHANGELOG ganha a linha "Tipos do modelo" e a observação sobre a `type_accuracy`.
- **Gerador (§4.9):** `tool_items_per_stratum` e `external_tool_items_per_type`, com silhuetas sintéticas das 5 ferramentas; com os dois em 0, os arquivos são os mesmos, byte a byte.
- **Fixture e README (§4.10):** `ml/tests/fixtures/tiny_model_tools/` (8 tipos, `allen_key` sem grau, 853.052 bytes), gerada por `ml/scripts/make_tiny_fixture.py --with-tools`; seção "Ferramentas (Fase 2)" no `ml/README.md`.

### Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-13 | `ml/src/qc_ml/data.py` (`TOOL_OBJECT_TYPES`, `KNOWN_OBJECT_TYPES`, `ITEM_PREFIX_TYPES`, `item_prefix_matches`, `GRADE_REQUIRED_DATASET_TYPES`, `_row_problems`) | `ml/tests/test_tools_data.py::test_ca13_tools_load_without_error`, `::test_ca13_t_item_with_screw_is_a_prefix_mismatch`, `::test_ca13_tool_without_grade_is_missing_grade`, `::test_t_prefix_with_a_mvp_type_is_refused`, `::test_tool_with_s_prefix_is_refused`, `::test_two_tool_types_for_one_item_conflict`, `::test_item_prefix_matches`, `::test_tool_types_are_the_grade_optional_types_of_the_contract` |
| CA-14 | `ml/src/qc_ml/data.py` (`TOOL_GRADE_MIN_IMAGES`, `TOOL_GRADE_MIN_ITEMS`, `tool_grade_coverage`, `build_data_report`) | `ml/tests/test_tools_data.py::test_ca14_tool_grade_criterion`, `::test_criterion_without_tools_has_the_5_tools_with_zeros`, `::test_criterion_ignores_excluded_images`, `::test_data_report_has_the_tool_coverage`, `::test_build_data_report_lists_every_known_type`; `ml/tests/test_data.py::test_report` |
| CA-15 | `ml/src/qc_ml/split.py` (`line_type_resolver`, `split_object_types`, `new_object_types`, `type_decision_problems`, `make_split`, `write_split`, `recorded_deferred_types`, `_type_list`, `main`) | `ml/tests/test_tools_split.py::test_ca15a_new_types_need_a_decision`, `::test_ca15_defer_extend_and_freeze` ((b), (c), (d)), `::test_ca15e_too_few_items_to_extend`, `::test_extension_is_the_split_v1_procedure_per_type`, `::test_invalid_type_lists_exit_2`, `::test_unknown_type_exits_2_even_for_split_v1`, `::test_split_v1_ignores_the_lists`, `::test_new_object_types_and_decisions`, `::test_make_split_checks_the_extension` |
| CA-15 (leitura do split, §4.7 último item) | `ml/src/qc_ml/split.py` (`deferred_type_counts`, `assign_splits`, `rows_for`) | `ml/tests/test_tools_split.py::test_readers_ignore_a_deferred_type`, `::test_present_type_with_new_images_is_still_outdated` |
| CA-16 | `ml/src/qc_ml/data.py` (`ModelLabels`, `derive_model_labels`, `grade_target`), `ml/src/qc_ml/train.py` (`model_labels_for`, `graded_training_counts`), `ml/src/qc_ml/dataset.py` (`PartsDataset.grade_index`) | `ml/tests/test_tools_model.py::test_ca16_model_labels_with_tools`, `::test_ca16_model_labels_of_the_mvp`, `::test_model_labels_use_only_the_train_rows_for_the_types`, `::test_ca16_grade_target`, `::test_graded_training_counts_leave_out_the_masked_rows`, `::test_model_labels_need_other_in_train`; com torch: `ml/tests/test_tools_torch.py::test_parts_dataset_masks_the_ungraded_tools` |
| CA-17 | `ml/src/qc_ml/thresholds.py` (`_choose_type`, `_screw_nut_mask`, `_choose_unusable`, `_choose_review`) | `ml/tests/test_tools_model.py::test_ca17_false_unknown_counts_every_type_but_other`, `::test_unusable_and_review_thresholds_ignore_the_tools`, `::test_thresholds_of_the_mvp_labels_are_unchanged` |
| CA-18 | `ml/src/qc_ml/evaluate.py` (`METRIC_KEYS`, `TOOL_GRADE_METRIC_KEYS`, `tool_grade_metrics`, `compute_metrics`, `split_counts`), `ml/src/qc_ml/artifacts.py` (`labels_to_dict`, `head_labels_to_dict`, `as_labels`, `check_labels`), `ml/src/qc_ml/decision.py` (`apply_decision`), `ml/src/qc_ml/export.py` (`training_labels`, `run`), `ml/src/qc_ml/train.py` (`training_config.json`, `best.pt`), `ml/src/qc_ml/pipeline.py`, `ml/src/qc_ml/plots.py`, `ml/tests/fixtures/tiny_model_tools/`, `ml/scripts/make_tiny_fixture.py` | `ml/tests/test_tools_model.py::test_ca18_evaluate_with_tools`, `::test_few_test_items_warning_per_model_type`, `::test_tool_grade_metrics_values`, `::test_tool_grade_metrics_without_test_images_are_null`, `::test_fixture_labels_json_has_the_ungraded_types`, `::test_labels_dict_has_the_ungraded_types`, `::test_invalid_ungraded_types_are_refused`, `::test_ungraded_type_outside_the_model_is_refused`, `::test_ungraded_types_must_be_a_list_of_strings`, `::test_unknown_labels_key_is_still_refused`, `::test_ungraded_tool_has_no_grade_and_only_the_type_margin`, `::test_same_result_as_the_edge_decision_with_ungraded_types`; `ml/tests/test_evaluate.py::test_ca22_metrics_file`; com torch: `ml/tests/test_tools_torch.py::test_pipeline_with_tools_records_the_model_types`, `::test_standalone_export_reads_the_labels_of_the_checkpoint`, `::test_training_labels_sources`; `ml/tests/test_pipeline_slow.py::test_ca08_training_config` |
| CHANGELOG (§4.8) | `ml/src/qc_ml/report.py` (`model_types_lines`, `TYPE_ACCURACY_NOTE`, `changelog_entry`) | `ml/tests/test_tools_model.py::test_changelog_lists_the_model_types_before_the_table`, `::test_changelog_without_tools_has_no_types_line`, `::test_changelog_refuses_invalid_labels` |
| CA-19 | `ml/src/qc_ml/synthetic.py` (`make_synthetic_dataset`, `TOOL_POLYGONS`, `_shape_mask`) | `ml/tests/test_tools_data.py::test_ca19_defaults_are_byte_for_byte_the_same`, `::test_tools_come_after_the_own_items`, `::test_tool_numbering_and_layout`, `::test_generator_refuses_invalid_tool_counts`, `::test_add_synthetic_item_draws_a_tool` |
| CA-20 | `ml/src/qc_ml/split.py` (externas sempre no treino, também `XT-`) | `ml/tests/test_tools_split.py::test_ca15_defer_extend_and_freeze` (split (c) com `external_tool_items_per_type=2`: nenhuma peça em dois splits, nenhuma `XT-` fora do treino) |
| CA-21 (manual) | `ml/README.md` (seção "Ferramentas (Fase 2)", passo a passo) | — (trabalho da dupla) |

### Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest -q ml/tests --ignore=ml/tests/acceptance          # testes do autor, sem torch
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
# com torch (local): uv sync --all-packages --extra train && uv run pytest -q ml/tests
# depois, voltar ao estado do CI: uv sync --all-packages --locked
```

Resultados (2026-10-24):

- Suíte completa, ambiente do CI (sem o extra `train`) e `partqc_test`: **18 failed, 6906 passed, 57 skipped**. As 18 falhas são as 15 de aceite antigos da Parte A (tabela acima) e as 3 de `ml/` da tabela abaixo. Nenhum teste do autor falha.
- `ml/tests` com o extra `train` instalado (inclui os testes *slow* e os aceites com torch): **5 failed, 917 passed, 2 skipped**; as 5 falhas são todas a asserção do conjunto exato de chaves de topo do `metrics.json` (tabela abaixo). O ambiente voltou ao estado do CI (`uv sync --all-packages --locked`; `torch` não instalado).
- Testes novos do autor: 85 (`test_tools_data.py` 33, `test_tools_split.py` 14, `test_tools_model.py` 34, `test_tools_torch.py` 4, este com `pytest.importorskip("torch")`).

### Testes de aceite antigos de `ml/` que passam a falhar por causa da Parte B (quem ajusta é o tester)

| Arquivo | Teste | O que falha | Requisito da SPEC-016 | Na §3.1? |
|---|---|---|---|---|
| `ml/tests/acceptance/test_spec_012.py` | `test_ca22_metrics_json_contents` | `set(metrics) == METRIC_KEYS`: chave a mais `tool_grade_metrics` | §4.8 (chave de topo nova) | sim |
| `ml/tests/acceptance/test_spec_012.py` | `test_extra_test_split_without_unusable_reports_null` | a mesma asserção (`_check_metrics`) | §4.8 | sim (mesma asserção do CA-22) |
| `ml/tests/acceptance/test_spec_035.py` | `test_ca12_metrics_counts_by_origin` | `set(metrics) == METRIC_KEYS` | §4.8 | sim |
| `ml/tests/acceptance/test_spec_012.py` (só com torch) | `test_extra_smoke_metrics_json_is_complete`, `test_extra_corn_smoke_pipeline_exports_probabilities` | `set(metrics) == METRIC_KEYS` no `metrics.json` do pipeline de fumaça | §4.8 | sim (mesma asserção) |

Os casos de `T-`/`XT-` listados na §3.1 para `test_spec_011.py` e `test_spec_035.py` **não** falham: os testes existentes usam `T-001` com `screw` e `XT-0001` com `screw`, que continuam recusados (`item_prefix_mismatch`). O `test_ca08_training_config_contents` da SPEC-012 (com torch) passa, porque `training_config.json["labels"]` mantém o formato da SPEC-012 (decisão 2).

### Decisões tomadas dentro do escopo da SPEC

1. **`ModelLabels` e `DEFAULT_LABELS`.** `KNOWN_OBJECT_TYPES` passa a ter 8 tipos, mas `DEFAULT_LABELS` continua com `screw`, `nut` e `other` (`MVP_OBJECT_TYPES`), como pede o CA-16. `GRADED_OBJECT_TYPES` continua `screw`/`nut` (metas do protocolo, métricas `grade_*` e limiares de grau); a obrigatoriedade do grau no manifest usa a nova `GRADE_REQUIRED_DATASET_TYPES` (`screw`, `nut` e as ferramentas).
2. **Onde fica `ungraded_object_types`.** No `labels.json` do export, sempre (`[]` sem ferramenta sem grau); a leitura aceita o arquivo sem a chave, então a fixture `tiny_model` da SPEC-012 continua igual e válida. No `training_config.json`, como chave de topo própria: o `labels` de lá mantém o formato da SPEC-012 (`object_types`, `grades`), que o CA-08 da SPEC-012 compara por igualdade. No `metrics.json`, dentro de `labels` (o CA-18 lê `labels.ungraded_object_types`). Também no `best.pt`, para que o `python -m qc_ml.export` sozinho reconstrua a cabeça de tipo certa (fonte seguinte: `training_config.json`; um checkpoint sem rótulos é do MVP).
3. **Validação do `labels.json` no `qc_ml`** (`check_labels`): a mesma regra da borda (lista de textos, sem repetição, dentro de `object_types`, só tipos de grau opcional ou proibido do contrato); as mensagens citam a regra, sem valores.
4. **Decisão do `qc_ml` igual à da borda.** `apply_decision` passou a tratar `ungraded_object_types` como a `qc_edge.decision.decide` da Parte A (sem grau; `needs_review` só pela margem de tipo). A §4.8 não cita o `qc_ml.decision`, mas ele é a cópia vetorizada da regra da borda (SPEC-012, teste cruzado), e os limiares e o `needs_review_rate` dependem dela. O teste cruzado novo compara as duas em 1.000 vetores com 8 tipos e `allen_key` sem grau.
5. **`grade_review_threshold` só em `screw`/`nut`** (texto da §4.8); ver o SPEC_ISSUE-1. `unusable_threshold` passou a filtrar explicitamente as imagens de `screw`/`nut` com grau (antes, "imagens com grau", o mesmo conjunto no MVP).
6. **Nota `no_screw_nut_in_val`** do `type_threshold`: o código da nota não mudou (compatibilidade do `thresholds_report.json`), mas agora significa "nenhuma imagem de validação de tipo diferente de `other`".
7. **Tipo de uma linha de split anterior** (`line_type_resolver`): pela linha do `df`; senão, pelo `item_id` resolvido (mesmas fontes do `item_id_resolver` da SPEC-011) e pelo tipo dessa peça no `df`, ou pela letra quando ela só admite um tipo (`S`, `N`, `O`).
8. **Extensão: um sorteio por tipo.** Cada tipo estendido usa um gerador novo `np.random.default_rng(seed)`, com os estratos do tipo em ordem lexicográfica, como o `split_v1` faria só com eles. Assim, estender `allen_key` sozinho ou junto com os outros dá a mesma divisão dele (teste `test_extension_is_the_split_v1_procedure_per_type`), e o sorteio das peças novas dos tipos antigos (treino/validação) não muda. Estratos com menos de 3 peças dentro de um tipo estendido seguem a regra do `split_v1` (tudo no treino), com `small_stratum` marcado `"scope": "test_extension"`.
9. **Versão gravada quando só a decisão muda.** O CA-15 (b) pede o `split_v2.json` com `deferred_types` mesmo quando o CSV é igual ao `split_v1`. A CLI grava uma versão nova quando o CSV muda **ou** quando `deferred_types` difere do registrado no `split_v<M>.json` anterior (ausente = `[]`, para os JSONs anteriores à SPEC-016); repetir a mesma decisão dá `split unchanged`. As listas são gravadas na ordem de `KNOWN_OBJECT_TYPES`.
10. **Mensagens da CLI.** Cada problema sai sozinho numa linha da saída de erro, sem prefixo (`new object type without decision: <tipo>`, `too few items to extend the test: <tipo>`), para os CAs compararem a linha inteira. Além das duas mensagens da SPEC: `object type is not new: <tipo>`, `object type in both --extend-test-types and --defer-types: <tipo>` e `unknown object type: <tipo>`. No `split_v1`, um valor desconhecido também dá saída 2 ("cada valor tem de estar em `KNOWN_OBJECT_TYPES`"); valores válidos são ignorados, com um aviso no log, e o JSON registra listas vazias.
11. **Leitura do split.** `assign_splits` devolve `None` para as linhas de tipo adiado (em vez de recusar), e o `rows_for` nunca as devolve; o relatório de dados as conta em `total`, sem split.
12. **Treino.** `derive_model_labels` fica em `qc_ml.data` (sem torch, testável no CI). O treino confere os rótulos derivados com `check_labels` e falha com `TrainError` se não houver `other` no treino (a regra de decisão depende dele). Os pesos de classe do grau contam só as imagens que entram na loss (`graded_training_counts`), e o QWK de validação do early stopping usa as mesmas linhas mascaradas (inclui ferramentas graduadas; igual ao de hoje no MVP).
13. **Avaliação.** `false_unknown_rate` do `metrics.json` continua em `screw`/`nut` (a §4.8 só muda o `FU(t)` dos limiares). `counts.<split>.by_class` passa a ter `by_grade` também para as ferramentas. O aviso `few test items for <tipo>: <n>` vale para todos os tipos do modelo, inclusive os do MVP: no dataset sintético pequeno, `other` com 1 peça de teste já gera o aviso.
14. **CHANGELOG.** A linha usa os valores crus de `labels` (`- Tipos do modelo: screw, nut, other, pliers, ...; sem grau: allen_key.`, ou `nenhum`). Um valor fora de `KNOWN_OBJECT_TYPES` em `labels` faz o `report changelog` sair com 2 sem ecoar o valor (mesma cautela da SPEC-037 com as contagens).
15. **Gerador.** As ferramentas vêm depois de todas as outras peças (inclusive as de conhecido e as externas), então um dataset gerado com ferramentas tem as mesmas linhas e imagens do dataset sem elas, mais as das ferramentas (é o que o CA-15 usa). As peças `T-` são de origem `capture` (sem linha no `sources.csv`); os graus das `XT-` seguem o rodízio dentro de cada ferramenta; a sequência `T-` é única e tem teto de 999 (no máximo 39 peças por estrato).
16. **Rótulos PT-BR nas matrizes de confusão** (`plots.TYPE_LABELS_PT`): as ferramentas usam o `OBJECT_TYPE_LABELS_PT` do contrato.
17. **Fixture.** `model.onnx` da `tiny_model_tools` não é ignorado pelo `.gitignore` (conferido com `git check-ignore`), então nenhuma regra nova é necessária. O teste de fumaça com ferramentas (`test_tools_torch.py`) usa 3+2 épocas e `lr_a = 0.01`: com 8 tipos e 1+1 épocas, a rede de fumaça ficava perto da distribuição a priori (parafuso e porca com a mesma contagem) e nenhuma entrada sintética tinha diferença ≥ 1e-3 entre as duas maiores probabilidades, que o export exige para a paridade. É só configuração do teste.

### SPEC_ISSUE

- **SPEC_ISSUE-1 (baixa; contradição de texto na §4.8, Limiares).** A frase "`unusable_threshold` e `grade_review_threshold` **continuam** calculados só em `screw`/`nut`" não corresponde à regra vigente da SPEC-012 §4.6 para o `grade_review_threshold`, que usa "a fração de val com `needs_review`", ou seja, todas as imagens de validação, inclusive as de `other`. Implementei o texto normativo da §4.8: a fração de revisão conta só as imagens de validação de `screw`/`nut` (numerador e denominador). Efeito no MVP: as imagens de `other` deixam de contar nessa fração, então o `grade_review_threshold` de um modelo do MVP pode mudar em relação à regra da SPEC-012. Nenhum teste de aceite antigo falha com isso. Se o architect preferir manter a regra da SPEC-012 (todas as imagens menos as ferramentas, por exemplo), a mudança é de uma linha em `qc_ml.thresholds._choose_review` (`scope`) e no teste `test_unusable_and_review_thresholds_ignore_the_tools`. Peço que o architect confirme a leitura ou corrija o texto da §4.8.

### Observações para o architect (fora do escopo da Parte B, não bloqueiam os CAs)

- **Piloto de concordância das ferramentas (§3.3).** `python -m qc_ml.agreement` só forma pares de `screw`/`nut` (`GRADED_OBJECT_TYPES`, SPEC-011 §4.3). O piloto de grau das ferramentas pedido na §3.3 (20 fotos, QWK ≥ 0,6) daria `no pairs to compare` se o arquivo só tiver ferramentas. A Parte B não lista o `agreement.py`; não o alterei. Se algum tipo cumprir o critério de grau, será preciso uma SPEC curta (ou um ajuste desta) para incluir as ferramentas no `agreement`.
- **Contagem de imagens por estrato da extensão.** Com a meta de 6 peças por ferramenta, cada estrato (ferramenta, grau dominante) terá em geral 1 ou 2 peças, e a regra do `split_v1` manda estratos com menos de 3 peças inteiros para o treino. Na prática, uma ferramenta com 6 peças espalhadas pelos 5 graus pode ficar **sem teste** mesmo estendida (aviso `small_stratum` com `scope: test_extension`). O comportamento segue a §4.7 ("procedimento do `split_v1`"); registro aqui porque o CA-21 depende disso e a dupla deve olhar os avisos do `split_v<N>.json` antes de treinar.

### Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes do autor passando (sem torch e com torch); suíte completa com banco: só as falhas de aceite listadas nas duas tabelas
- [x] Seeds fixas: split (`seed` do CLI; extensão com `default_rng(seed)` por tipo), gerador (`seed`), bootstrap e treino sem mudança
- [x] Nenhuma métrica reportada: não houve treino real (CA-21 é manual)
- [x] Nenhuma imagem real, nenhum `.onnx` de modelo real, nada de `~/partqc-entrada/`; a fixture usa só entradas sintéticas
- [x] `.env.example` sem mudança (nenhuma variável nova); nenhuma dependência nova; `uv.lock` sem mudança
- [x] Nenhum arquivo fora de `ml/` alterado (salvo esta seção do relatório) e nenhum em `tests/acceptance/`
- [x] Ambiente devolvido ao estado do CI (`uv sync --all-packages --locked`)

### Adendo: ajuste depois da reaprovação (SPEC_ISSUE-1 e SPEC_ISSUE-2)

O architect corrigiu a SPEC (commit `83d64a1`, §4.7, §4.8, §3.3, §6, §7, CA-22 e CA-23 novos) e o humano reaprovou (commit `be3d2ec`). Ajustes da Parte B, ainda na r1:

| Commit | O que muda |
|---|---|
| `f6fe277` | **§4.8 (SPEC_ISSUE-1).** `qc_ml.thresholds._choose_review` passa a contar a fração de `needs_review` entre as imagens de validação de `screw`, `nut` e `other` (`_mvp_mask`; numerador e denominador), deixando de fora só as ferramentas. Isso é a regra da SPEC-012 nos dados do MVP. `unusable_threshold` continua só em `screw`/`nut`. O texto do `rule` no `thresholds_report.json` foi atualizado. |
| `cec9f3a` | **§4.7 (SPEC_ISSUE-2).** Estrato da extensão: (tipo, grau dominante) se a ferramenta é graduada por `tool_grade_coverage(df)`, calculado no `df` que a CLI do split leu; senão, o tipo inteiro (estrato `(tipo, "none")`). Um tipo que não é ferramenta mantém o grau dominante. Um tipo estendido que ficaria sem nenhuma peça no teste é recusado por `ExtensionError` (subclasse de `SplitError`): a CLI imprime uma linha `too few items to extend the test: <tipo>` por tipo, sai com 2 e não grava nada. A checagem prévia de menos de 3 peças (`type_decision_problems`) continua. Na mesma rodada: `ml/README.md` (limiares, estrato da extensão, conferência do teste no `split_v<N>.json` e nota sobre o `qc_ml.agreement`). |

**Testes do autor afetados ou novos:**

- `test_tools_model.py`
  - `test_unusable_and_review_thresholds_ignore_the_tools` continua igual: nele, as imagens de validação são só de `screw` e `pliers`, e com isso o resultado não muda.
  - Novos: `test_review_threshold_counts_screw_nut_and_other` (o `other` entra na fração, `n_images == 20`) e `test_ca22_review_threshold_example` (o exemplo do CA-22: `type_threshold == 0.85`, `grade_review_threshold == 0.60` e nenhuma nota `review_adjusted`).
  - `test_ca18_evaluate_with_tools` foi ajustado: com 3 peças por estrato, as ferramentas desse dataset ficam sem grau pelo critério, então cada uma vira um estrato de 15 peças, com 2 peças (4 imagens) no teste.
- `test_tools_split.py`
  - `test_extension_is_the_split_v1_procedure_per_type` foi ajustado: no CA-15, `allen_key` fica sem grau, então tem um estrato de 20 peças e a divisão fica 14/3/3.
  - Novos: `test_ca23_ungraded_tool_is_one_stratum` (3/1/1 por ferramenta) e `test_ca23_graded_tool_is_split_by_grade` (3/1/1 em cada grau, com as 5 ferramentas graduadas).
  - Novo: `test_graded_type_without_any_test_item_is_refused`. Ferramenta graduada com 5 peças de graus dominantes diferentes: 5 estratos de 1 peça, nenhuma peça no teste, `ExtensionError`.
  - Novo: `test_cli_prints_each_extension_error_alone`.
  - Continuam passando sem mudança: CA-15 (a) a (e) (no (c), sem grau: 14/3/3 por ferramenta, todas com `train`, `val` e `test`) e CA-20.

**Rastreabilidade acrescentada:**

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-22 | `ml/src/qc_ml/thresholds.py` (`_mvp_mask`, `_choose_review`) | `ml/tests/test_tools_model.py::test_ca22_review_threshold_example`, `::test_review_threshold_counts_screw_nut_and_other`, `::test_unusable_and_review_thresholds_ignore_the_tools` |
| CA-23 | `ml/src/qc_ml/split.py` (`make_split`: `extension_strata`, `ExtensionError`; `main`) | `ml/tests/test_tools_split.py::test_ca23_ungraded_tool_is_one_stratum`, `::test_ca23_graded_tool_is_split_by_grade`, `::test_graded_type_without_any_test_item_is_refused`, `::test_cli_prints_each_extension_error_alone`, `::test_extension_is_the_split_v1_procedure_per_type` |

**Resultados (2026-10-24, depois dos dois commits):**

- Suíte completa no ambiente do CI, com o `partqc_test`: **18 failed, 6912 passed, 57 skipped**. São as mesmas 18 falhas de aceite antigos de antes (15 da Parte A e 3 de `ml/` pela chave `tool_grade_metrics`). Nenhum teste do autor falha.
- Com o extra `train`: `test_tools_torch.py`, `test_pipeline_slow.py` e `acceptance/test_spec_012.py` dão 4 failed e 70 passed. As 4 falhas são as asserções de `METRIC_KEYS` já listadas.
- O ambiente foi devolvido ao estado do CI (`uv sync --all-packages --locked`, sem torch). `ruff check .` e `ruff format --check .` limpos.
- Testes do autor de SPEC-016 em `ml/`: 91 (87 sem torch e 4 com torch).
- Nenhum aceite antigo novo passa a falhar com o ajuste.

**SPEC_ISSUE:** nenhum novo. A observação do piloto de concordância das ferramentas foi incorporada à §3.3 pelo architect; o `agreement.py` não mudou.
