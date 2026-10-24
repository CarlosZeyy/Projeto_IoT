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
