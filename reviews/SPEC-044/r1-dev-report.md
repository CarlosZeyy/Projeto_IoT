# SPEC-044 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-044](../../docs/specs/SPEC-044-ferramentas-so-identificadas.md) |
| Rodada | r1 |
| Autor | developer (Parte A); a Parte B (ml-engineer) é acrescentada no fim deste arquivo |
| Branch | `spec/SPEC-044-ferramentas-so-identificadas` |
| Commits | `02b492d` (contracts), `9263254` (infra), `f53ef68` (api), `1548501` (edge), `8e6cd00` (dashboard) e o commit deste relatório |

## Parte A (developer)

### Resumo

- `qc-contracts` **0.7.0** (minor, ADR-025 e ADR-021): `ObjectType` ganha `hammer`, `wrench` e `spirit_level`, depois de `cordless_screwdriver` e nessa ordem (15 membros), com os rótulos `martelo`, `chave de aperto` e `nível`; os três entram em `GRADE_FORBIDDEN_OBJECT_TYPES`. A invariante não muda de código (segue os grupos). `pyproject.toml`, `__version__`, `uv.lock` e o histórico do `packages/contracts/README.md` atualizados.
- Banco: `infra/migrations/007_identified_tool_object_types.sql`, na forma da 006 (um bloco `DO`, idempotente, sem `BEGIN`/`COMMIT`, sem credenciais, mesmos nomes de restrição): `inspections_object_type_check` com os 15 valores e `inspections_grade_null_iff_unknown` com a expressão literal da SPEC §4.2.
- API: nenhum código novo (SPEC §3.1). Testes do autor provam a escrita com e sem grau, o SPC e a taxa de defeito sem os três (regra `grade is not null`), o `SpcObjectType` (e o `openapi.json`) igual ao da SPEC-016 e `contract_version = 0.7.0` no `/api/v1/health`.
- Borda: `DatasetObjectType` ganha os três; tupla nova `IDENTIFIED_TOOL_OBJECT_TYPES` em `UNGRADED_DATASET_TYPES` e no prefixo `T` de `ITEM_PREFIX_TYPES`; a coleta responde 422 com `grade must be empty for an identification-only tool` (as elétricas e o `other` mantêm as mensagens deles); a importação os aceita pelas listas do `qc_edge.collect`, sem regra própria (`grade_on_other` e `item_prefix_mismatch` como as elétricas); seletor da `/capture`, `capture.js`, tabela de cobertura (43 células) e texto das metas do console. O carregamento do `labels.json` e a decisão não mudaram (já derivam do contrato).
- Dashboard: os três em `charts.OBJECT_TYPE_ORDER` (depois das elétricas, antes de `desconhecido`) e em `charts.OBJECT_TYPE_COLORS`; os filtros de tipo já derivavam do `ObjectType`; `filters.SPC_OBJECT_TYPES` não muda.

### Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `packages/contracts/src/qc_contracts/{enums,labels,schemas,__init__}.py`, `packages/contracts/pyproject.toml`, `packages/contracts/README.md`, `uv.lock` | `packages/contracts/tests/test_smoke.py::test_import_and_version`, `::test_readme_has_version_history_row`; `test_enums.py::test_enum_values`, `::test_grade_groups`, `::test_grade_groups_partition_object_type` (15), `::test_identified_tools_come_last_in_order`, `::test_identified_tools_are_never_graded`, `::test_power_tools_come_after_the_hand_tools`; `test_labels.py::test_one_label_per_member` |
| CA-02 | `packages/contracts/src/qc_contracts/enums.py` (`GRADE_FORBIDDEN_OBJECT_TYPES`; a invariante de `schemas.py` não muda) | `packages/contracts/tests/test_schemas.py::test_identified_tool_without_grade_accepted`, `::test_identified_tool_with_grade_rejected` (`good`, `1.0`, `0.8`), `::test_identified_tool_with_only_score_or_confidence_rejected`, `::test_identified_tool_message_carries_no_values`, `::test_inspection_read_of_an_identified_tool`, `::test_identified_tool_round_trip`, `::test_invariant_follows_the_grade_groups` (15 tipos × 6 graus) |
| CA-03 | `infra/migrations/007_identified_tool_object_types.sql` | `infra/tests/test_schema_db.py::test_grade_groups_check_mirrors_the_contract` (90 pares contra `InspectionCreate` 0.7.0), `::test_grade_check_equals_the_spec_expression_on_the_enum` (90 pares), `::test_identified_tool_grade_check_is_the_spec_expression` (expressão literal da §4.2, 96 pares com um valor fora do enum), `::test_identified_tool_is_accepted_only_without_grade` (SQLSTATE `23514`), `::test_identified_tool_check_values`, `::test_identified_tool_migration_runs_again_without_error` (`pg_get_constraintdef` dos dois `check` igual depois de duas execuções), `::test_identified_tool_migration_keeps_older_rows_valid`, `::test_identified_tool_migration_has_the_shape_of_006`, `::test_identified_tool_migration_is_the_latest_grade_check_migration`; `infra/tests/test_migrate_db.py::test_running_sql_file_again_changes_nothing`, `::test_identified_tool_migration_supersedes_the_power_tool_checks`; `infra/tests/test_migration_files.py::test_repository_migrations_are_valid` |
| CA-04 | (sem código novo na API: contrato 0.7.0 e migração 007) | `api/tests/test_identified_tools.py::test_post_identified_tool_without_grade_is_created_and_listed`, `::test_post_identified_tool_with_a_grade_is_422`, `::test_spc_leaves_out_a_lot_of_wrenches` (cenário do CA), `::test_spc_filter_by_an_identified_tool_is_422`, `::test_summary_counts_the_wrenches` (`by_object_type["wrench"] == 10`), `::test_read_filters_accept_an_identified_tool` (inclui `object_type=spirit_level`), `::test_spc_object_type_is_unchanged`, `::test_openapi_spc_enum_is_unchanged`, `::test_openapi_object_type_has_the_identified_tools`, `::test_health_shows_the_contract_0_7_0`, `::test_same_identified_tool_twice_is_a_duplicate`, `::test_batch_with_identified_tools`, `::test_batch_with_one_graded_identified_tool_is_refused_whole`, `::test_identified_tools_inside_a_screw_lot_do_not_change_n`, `::test_summary_leaves_identified_tools_out_of_the_defect_rate`, `::test_summary_of_spirit_levels_only_has_null_rate` |
| CA-05 | `edge/src/qc_edge/onnx_inferencer.py` e `decision.py` sem mudança de código (o grupo sem grau vem do contrato; só a docstring de `decision.py`), `edge/src/qc_edge/app.py` (rótulo e veredito) | `edge/tests/test_identified_tools.py::test_model_with_a_hammer_needs_it_in_ungraded` (modelo `screw`, `other`, `hammer`, sem `nut`: ausente e `[]` → `ModelLoadError`; `["hammer"]` carrega), `::test_model_with_the_three_must_list_all_of_them`, `::test_decided_hammer_has_no_grade` (`[0.05, 0.05, 0.90]`), `::test_capture_of_a_hammer_goes_to_the_outbox_without_grade` (`approved` nulo, `sem grau`, `martelo`, com o `OnnxInferencer` real), `::test_identified_tool_verdict`, `::test_console_row_of_a_spirit_level` |
| CA-06 | `edge/src/qc_edge/collect.py` (`DatasetObjectType`, `IDENTIFIED_TOOL_OBJECT_TYPES`, `UNGRADED_DATASET_TYPES`, `ITEM_PREFIX_TYPES`, `_parse_grade`) | `edge/tests/test_identified_tools.py::test_collect_of_the_identified_tools_through_the_route` (cenário do CA: `T-010`, `T-011`, `O-012`, `T-013`), `::test_collect_of_each_identified_tool_goes_to_its_no_grade_folder`, `::test_identified_tool_with_empty_grade_is_valid`, `::test_identified_tool_with_a_grade_is_refused`, `::test_other_ungraded_types_keep_their_messages`, `::test_identified_tool_needs_the_t_prefix`, `::test_identified_tools_mirror_the_contract`, `::test_identified_tools_are_in_the_t_prefix`, `::test_t_prefix_admits_the_identified_tools` |
| CA-07 | `edge/src/qc_edge/importer.py` (só comentários: as regras vêm de `UNGRADED_DATASET_TYPES` e `item_prefix_matches`) | `edge/tests/test_importer.py::test_identified_tool_is_imported_without_grade` (`T-601`, `c01`), `::test_graded_identified_tool_refuses_the_whole_plan` (`plan line 3: grade_on_other (grade)`, saída 2, nada gravado), `::test_identified_tool_needs_the_t_prefix` (`O-603` → `item_prefix_mismatch (object_type)`), `::test_every_identified_tool_is_accepted_with_t_or_xt_and_no_grade`, `::test_identified_tools_count_in_their_coverage_row` |
| CA-08 | `edge/src/qc_edge/app.py` (`DATASET_OBJECT_TYPE_LABELS_PT`, `_UNGRADED_TOOL_VALUES`, texto das metas), `edge/src/qc_edge/collect.py` (`_coverage_keys`, `_targets`, `_coverage_key`, `IDENTIFIED_TOOL_TARGET_*`), `edge/src/qc_edge/static/capture.js` (`NO_GRADE`, `PREFIX_TYPES`) | `edge/tests/test_identified_tools.py::test_collect_selector_lists_the_identified_tools`, `::test_capture_script_knows_the_identified_tools` (arquivo e `/static/capture.js` servido), `::test_console_coverage_has_a_row_per_identified_tool`, `::test_coverage_counts_identified_tools_in_one_row_each`, `::test_coverage_order_puts_the_identified_tools_before_other`, `::test_targets_are_those_of_the_power_tools`; `edge/tests/test_tools.py::test_collect_selector_offers_the_tools`; `edge/tests/test_collect.py::test_coverage_of_a_missing_manifest`; `edge/tests/test_collect_route.py::test_console_coverage_without_manifest` |
| CA-09 | `dashboard/src/qc_dashboard/charts.py` (`OBJECT_TYPE_ORDER`, `OBJECT_TYPE_COLORS`), `dashboard/src/qc_dashboard/filters.py` (só comentário) | `dashboard/tests/test_identified_tools.py::test_history_rows_of_a_wrench_without_grade` (cenário do CA), `::test_chart_order_has_every_type_once`, `::test_chart_colors_are_15_distinct`, `::test_history_type_filter_offers_the_identified_tools`, `::test_spc_filter_is_unchanged`, `::test_chart_order_puts_the_identified_tools_before_unknown`, `::test_by_object_type_counts_the_identified_tools`, `::test_history_rows_of_every_identified_tool`, `::test_history_csv_writes_sem_grau_for_a_spirit_level`, `::test_object_type_label_of_the_identified_tools`; `dashboard/tests/test_charts.py::test_by_object_type_is_horizontal` |
| CA-15 (manual) | — | Trabalho humano com o security-devops, depois do merge (migração `007` em produção, deploy, `contract_version`, borda, `requeue`). |

### Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
docker start partqc-pg
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
# só os testes do autor da Parte A:
CI=true TEST_DATABASE_URL=... uv run pytest -q packages/contracts/tests infra/tests api/tests edge/tests dashboard/tests \
    --ignore=packages/contracts/tests/acceptance --ignore=infra/tests/acceptance \
    --ignore=api/tests/acceptance --ignore=edge/tests/acceptance --ignore=dashboard/tests/acceptance
```

Resultado da suíte completa (2026-11-04, sem o extra `train`, com o `partqc_test` no contêiner `partqc-pg`, `CI=true`), no commit `8e6cd00`: **36 failed, 10653 passed, 167 skipped, 3 errors** (17 min 04 s). `ruff check` e `ruff format --check` limpos. **Todos os testes do autor da Parte A passam** (contracts 389, infra 606 + 40 skips do Docker, api, edge 1994, dashboard 691). As falhas e erros são de dois grupos, todos previstos pela SPEC:

- 23 falhas em testes de aceite antigos fora de `ml/`, que a SPEC-044 muda de propósito (tabela abaixo);
- 13 falhas e 3 erros em `ml/` (aceites da SPEC-021 e testes do autor do `qc-ml`), porque a Parte B ainda não foi feita: com o contrato 0.7.0, o `qc_ml.data` deriva as "elétricas" do grupo sem grau e passa a contar os três tipos novos como elétricos (SPEC §1, "Por que a Parte B está aqui"). Ver "Para a Parte B".

### Testes de aceite antigos que precisam de ajuste (`docs/architecture.md` §10; quem ajusta é o tester)

| Arquivo | Teste | O que falha | Requisito da SPEC-044 | Na §3.1? |
|---|---|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_021.py` | `test_ca01_contracts_version_is_0_6_0` | `'0.7.0' == '0.6.0'` (piso) | §3.1 (contrato 0.7.0), CA-01 | sim |
| `packages/contracts/tests/acceptance/test_spec_021.py` | `test_ca01_last_four_object_types_are_the_power_tools_in_order` | os 4 últimos agora são `cordless_screwdriver` e as 3 novas (as 4 elétricas continuam depois das manuais) | §3.1, CA-01 | sim (lista do `ObjectType`) |
| `packages/contracts/tests/acceptance/test_spec_021.py` | `test_ca01_grade_forbidden_group_is_unknown_and_the_power_tools` | igualdade exata; o grupo tem também as 3 novas | §3.1, CA-01 | sim |
| `packages/contracts/tests/acceptance/test_spec_021.py` | `test_extra_three_groups_are_disjoint_and_sum_the_12_members` | `15 == 12` (os grupos continuam disjuntos e somam o enum) | §4.1, CA-01 | sim |
| `packages/contracts/tests/acceptance/test_spec_021.py` | `test_extra_earlier_labels_did_not_change` | `15 == 12` (os 12 rótulos anteriores não mudaram) | §3.1 (rótulos novos) | sim |
| `packages/contracts/tests/acceptance/test_spec_002.py` | `test_ca17_labels_match_enums_and_are_immutable[object_type]` | `KeyError: 'hammer'` (a tabela esperada tem os 12 rótulos anteriores) | §3.1 (rótulos `martelo`, `chave de aperto`, `nível`) | não (mesmo caso listado nas SPECs 016 e 021) |
| `packages/preprocess/tests/acceptance/test_spec_023.py` | `test_ca12_spec002_acceptance_suites_still_pass` | roda a suíte de aceite da SPEC-002 em subprocesso e herda a falha acima | §3.1 (indireto) | não |
| `api/tests/acceptance/test_spec_004.py` | CA-28 (`ALLOWED_EXACT`) | ainda passa; a §3.1 manda apontá-lo para `packages/contracts/tests/acceptance/test_spec_044.py` com `0.7.0` no mesmo commit que cria esse arquivo | §3.1 | sim |
| `api/tests/acceptance/test_spec_005.py` | `test_ca08_summary_without_rows` | `15 == 3 + 5 + 4`: o resumo tem as 15 chaves do enum | §3.1 (`ObjectType` 0.7.0) | não |
| `api/tests/acceptance/test_spec_016.py` | `test_ca03_hammer_is_refused_with_23514` | usa `hammer` como valor fora do enum; com a 007, o banco o aceita sem grau | §3.1 e §4.2 (`hammer` no `check`) | não |
| `api/tests/acceptance/test_spec_016.py` | `test_ca04_post_tool_without_grade_and_read_it_back` | a última parte espera 422 para `GET /api/v1/inspections?object_type=hammer`; agora é 200 com lista vazia | §3.1, CA-04 (`object_type` novo é filtro válido) | não |
| `api/tests/acceptance/test_spec_016.py` | `test_extra_invalid_tool_payloads_are_422_and_not_stored` | `hammer` sem grau agora é aceito (201) | §4.1, CA-04 | não |
| `api/tests/acceptance/test_spec_016.py` | `test_extra_tool_migration_keeps_mvp_rows_and_runs_again` | procura `"tool_object_types"` no nome dos arquivos, excluindo só `power_tool_object_types`; o nome `007_identified_tool_object_types.sql` vem da §3.1 e também casa | §3.1 (nome da migração) | não |
| `api/tests/acceptance/test_spec_021.py` | `test_extra_power_tool_migration_keeps_rows_and_runs_again` | exige que a 006 seja a última migração ou que nenhuma posterior cite `object_type`; a 007 vem depois e cita | §3.1 e §4.2 | não |
| `edge/tests/acceptance/test_spec_010.py` | `test_ca15_compute_coverage_counts_images_and_items`, `test_ca15_missing_manifest_is_an_empty_table`, `test_extra_compute_coverage_ignores_unknown_cells` | a tabela de cobertura tem 43 células (11 + 25 + 4 elétricas + 3 novas), não 40 | §3.1 e §4.3 (uma linha por tipo novo) | não |
| `edge/tests/acceptance/test_spec_016.py` | `test_extra_coverage_has_the_tool_rows` | `43 == 11 + 25 + 4` | §4.3 | não |
| `edge/tests/acceptance/test_spec_021.py` | `test_extra_coverage_has_one_row_per_power_tool` | `43 == 11 + 25 + 4` (as linhas das elétricas continuam lá) | §4.3 | sim (contagem de linhas de uma tabela) |
| `dashboard/tests/acceptance/test_spec_013.py` | `test_extra_by_object_type_and_series_charts` | as barras do gráfico por tipo incluem `martelo`, `chave de aperto` e `nível` | §3.1 (dashboard: ordem e cores) | não |
| `dashboard/tests/acceptance/test_spec_029.py` | `test_ca01_spec013_suite_passes_and_hides_key_with_local_secrets` | roda a suíte de aceite da SPEC-013 em subprocesso e herda a falha acima | §3.1 (indireto) | não |
| `dashboard/tests/acceptance/test_spec_016.py` | `test_extra_object_type_order_and_colors` | `OBJECT_TYPE_ORDER` tem as 3 novas antes de `unknown` | §3.1 (dashboard) | sim (lista de um gráfico) |
| `dashboard/tests/acceptance/test_spec_021.py` | `test_extra_object_type_label_covers_the_12_types`, `test_extra_chart_order_and_distinct_colors_with_the_power_tools` | `15 == 12` | §3.1, CA-09 | sim (contagem de 12 tipos) |

Os aceites de `infra/tests/acceptance/` passam (525 passed). Nenhuma asserção com a mensagem `grade must be empty for a power tool` falhou: a mensagem das elétricas não mudou.

### Decisões tomadas dentro do escopo da SPEC

1. **Migração 007.** Mesma forma da 006 (§4.2): um bloco `DO`, duas restrições com os nomes antigos, sem transação própria. A expressão gravada é a da §4.2, palavra por palavra; um teste a compara com a expressão literal da SPEC no Postgres, em 96 pares (os 15 tipos e um valor fora do enum × 5 graus e `null`).
2. **Testes que rodam de novo uma migração anterior no banco compartilhado.** O banco da sessão de testes é `autocommit`, e rodar a 003 ou a 006 de novo traz de volta o `check` de 8 ou 12 valores. A fixture `rerun_003` de `infra/tests/test_schema_db.py` passa a rodar a **007** no fim (constante `LATEST_GRADE_CHECK_SQL`), e os dois testes da 006 que a rodam de novo passam a usar essa fixture; `test_migrate_db.py::test_power_tool_migration_supersedes_the_hand_tool_checks` roda a 006 e a 007 depois da 003. O teste antigo "a 006 é a última migração que troca os `check`" passou a "só a 007 vem depois da 006".
3. **Mensagem da coleta.** `_parse_grade` confere primeiro `other`, depois `IDENTIFIED_TOOL_OBJECT_TYPES` (`grade must be empty for an identification-only tool`) e depois o resto de `UNGRADED_DATASET_TYPES` (as elétricas, `grade must be empty for a power tool`). A importação continua com o código `grade_on_other` para todo tipo sem grau (§7 da SPEC).
4. **Constantes da borda.** `IDENTIFIED_TOOL_TARGET_IMAGES`, `IDENTIFIED_TOOL_TARGET_ITEMS` e `IDENTIFIED_TOOL_MIN_ITEMS` em `qc_edge.collect`, iguais às das elétricas (90, 6 e 3, §4.3). `POWER_TOOL_OBJECT_TYPES` continua só com as 4 elétricas (não é mais "o grupo sem grau menos `unknown`"). Ordem da cobertura: parafuso, porca, as 5 manuais × 5 graus, as 4 elétricas, as 3 só identificadas, outro (43 células).
5. **Texto das metas do console.** "Ferramentas só identificadas (sem grau): martelo, chave de aperto e nível, 90 imagens e 6 peças por ferramenta (mínimo 3)." Os nomes vêm de `OBJECT_TYPE_LABELS_PT`, na ordem do contrato.
6. **`capture.js`** (200 linhas, o teto dos testes das SPECs 007 e 010): a lista `POWER` foi absorvida em `NO_GRADE` (`other`, as 4 elétricas e as 3 novas), e o prefixo `T` passou a ser as 5 manuais mais `NO_GRADE.slice(1)`. O arquivo continua com 200 linhas. O teste do autor da SPEC-021 que procurava o literal `NO_GRADE = ["other"].concat(POWER)` passou a conferir o conteúdo de `NO_GRADE`.
7. **Cores do gráfico por tipo:** `#BCBD22` (martelo), `#6A3D9A` (chave de aperto) e `#E7298A` (nível), distintas das 12 anteriores, do cinza de `desconhecido` e do vermelho da carta p.
8. **`hammer` como valor fora do contrato.** Três testes do autor usavam `hammer` como exemplo de tipo inválido (`api/tests/test_tools.py`, `edge/tests/test_tools.py` e `infra/tests/test_schema_db.py`); passaram a usar `lathe` (e `Hammer`/`level` no teste de valores do banco).
9. **READMEs.** `edge/README.md`: tabela da coleta, parágrafo das ferramentas só identificadas, cobertura do console, regra do `labels.json` e plano de importação. `api/README.md` e `dashboard/README.md` não citam a versão do contrato nem listam os tipos: sem mudança.
10. Nenhuma dependência nova; nenhuma variável de ambiente nova (`.env.example` sem mudança). Nada em `ml/` alterado; nada em `tests/acceptance/` criado ou alterado.

### SPEC_ISSUE (se houver)

Nenhum.

### Para a Parte B (ml-engineer)

**Estado de `ml/` com a Parte A e sem a Parte B** (mesma execução da suíte): 13 falhas e 3 erros, todos pela derivação de `POWER_TOOL_OBJECT_TYPES` a partir do grupo sem grau do contrato, que agora inclui `hammer`, `wrench` e `spirit_level`:

- aceites da SPEC-021 em `ml/tests/acceptance/test_spec_021.py`: `test_ca10_model_labels_end_with_the_power_tools_all_ungraded`, `test_extra_known_types_and_hand_tool_group`, `test_extra_power_rows_come_after_every_earlier_row`, `test_extra_labels_without_power_train_images_skip_them` (falhas) e `test_ca11_extend_the_test_with_the_power_tools`, `test_ca12_evaluate_with_the_power_tools` (erros na fixture: o gerador sintético muda);
- testes do autor do `qc-ml`: `ml/tests/test_power_tools.py` (`test_power_tools_are_the_grade_forbidden_types_of_the_contract_but_unknown`, `test_ca10_power_tools_are_always_ungraded`, `test_power_tools_are_ungraded_next_to_a_graded_hand_tool`, `test_power_tool_without_train_images_is_not_a_model_type`, `test_ca11_extension_of_the_power_tools`, `test_power_tools_can_be_deferred`, `test_power_tools_come_after_every_other_item`, `test_external_power_tools_alone_write_the_registry`, erro em `test_ca12_evaluate_with_power_tools`) e `ml/tests/test_tools_split.py::test_invalid_type_lists_exit_2[extra0-unknown object type: hammer]` (usa `hammer` como tipo desconhecido; agora a CLI responde `object type is not new: hammer`).

A SPEC prevê exatamente isso (§1): a Parte B, com `POWER_TOOL_OBJECT_TYPES` explícito, deve devolver o `ml/` ao comportamento da SPEC-021.

- O que a Parte A já deixou pronto e a Parte B pode usar como referência: `qc_edge.collect.IDENTIFIED_TOOL_OBJECT_TYPES` (`hammer`, `wrench`, `spirit_level`, nessa ordem), `POWER_TOOL_OBJECT_TYPES` explícito com as 4 elétricas, `UNGRADED_DATASET_TYPES` = `other` + elétricas + as 3 novas e o prefixo `T` com as 12 ferramentas. A §3.1 da SPEC pede o mesmo no `qc_ml.data`, com `POWER_TOOL_OBJECT_TYPES` explícito (não mais derivado de `GRADE_FORBIDDEN_OBJECT_TYPES`).
- `edge/tests/test_importer.py::test_formats_equal_to_qc_ml` importa `qc_ml.data` (colunas do manifest e do `sources.csv` e `load_manifest`); continua passando com a Parte A.
- Rótulos PT-BR (para `qc_ml.plots`): `OBJECT_TYPE_LABELS_PT` do contrato já tem `martelo`, `chave de aperto` e `nível`.

### Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (contracts, infra, api, edge e dashboard)
- [x] `.env.example` atualizado (se houver variável nova): nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nada em `ml/` alterado (Parte B do ml-engineer)
