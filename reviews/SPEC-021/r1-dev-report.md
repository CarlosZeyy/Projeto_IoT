# SPEC-021 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-021](../../docs/specs/SPEC-021-ferramentas-eletricas.md) |
| Rodada | r1 |
| Autor | developer (Parte A); a Parte B (ml-engineer) é acrescentada no fim deste arquivo |
| Branch | `spec/SPEC-021-ferramentas-eletricas` |
| Commits | `d2db2b4` (contracts), `991b144` (infra), `de3804f` (api), `ee20bc8` (edge), `bb82089` (dashboard) e o commit deste relatório |

## Parte A (developer)

### Resumo

- `qc-contracts` **0.6.0** (minor, ADR-021): `ObjectType` ganha `angle_grinder`, `saw`, `drill` e `cordless_screwdriver`, depois de `phillips_screwdriver` e nessa ordem, com os rótulos `esmerilhadeira`, `serra`, `furadeira` e `parafusadeira`; as 4 entram em `GRADE_FORBIDDEN_OBJECT_TYPES`. A invariante não muda de código (já segue os grupos). `pyproject.toml`, `__version__`, `uv.lock` e o histórico do `README.md` atualizados.
- Banco: `infra/migrations/006_power_tool_object_types.sql` (idempotente, um bloco `DO`, como a 003) troca o `check` de `object_type` pelos 12 valores e põe as 4 elétricas no ramo "sem grau" do `check` de grau. `is_defective` não muda.
- API: nenhum código novo (SPEC §3.1). Testes do autor provam que a escrita aceita a elétrica sem grau e recusa com grau, que o SPC e a taxa de defeito a deixam de fora (regra `grade is not null` da SPEC-016) e que o `SpcObjectType` (e o `openapi.json`) é o da SPEC-016; `object_type=drill` no SPC dá 422.
- Borda: coleta e importação aceitam as 4 com `T-`/`XT-` e **grau vazio** obrigatório (com grau: 422 na coleta, `grade_on_other` no plano); foto em `raw/<tipo>/_/` (`NO_GRADE_DIR`); a regra do carregamento da SPEC-016 §4.4 (tipo de `GRADE_FORBIDDEN_OBJECT_TYPES` presente no modelo tem de estar em `ungraded_object_types`) já derivava do contrato e passa a valer para elas; a tabela de cobertura do console ganha uma linha por elétrica, sem grau (40 células). `capture.js` deixa o grau vazio e desabilitado para as elétricas. `edge/README.md` atualizado.
- Dashboard: ordem e cores das 4 no gráfico por tipo (depois das manuais, antes de desconhecido); "sem grau" no histórico e no CSV (já vinha da SPEC-016); o filtro da carta p continua com os membros do `SpcObjectType`.

### Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `packages/contracts/src/qc_contracts/{enums,labels,__init__}.py`, `packages/contracts/pyproject.toml`, `packages/contracts/README.md`, `uv.lock` | `packages/contracts/tests/test_smoke.py::test_import_and_version`, `::test_readme_has_version_history_row`; `test_enums.py::test_enum_values`, `::test_grade_groups`, `::test_grade_groups_partition_object_type`, `::test_power_tools_come_last_in_order`, `::test_power_tools_are_never_graded`; `test_labels.py::test_one_label_per_member` |
| CA-02 | `packages/contracts/src/qc_contracts/enums.py` (`GRADE_FORBIDDEN_OBJECT_TYPES`; a invariante de `schemas.py` não muda) | `packages/contracts/tests/test_schemas.py::test_power_tool_without_grade_accepted`, `::test_power_tool_with_grade_rejected`, `::test_power_tool_with_only_score_or_confidence_rejected`, `::test_power_tool_message_carries_no_values`, `::test_inspection_read_of_a_power_tool`, `::test_power_tool_round_trip`, `::test_invariant_follows_the_grade_groups` (12 tipos × 6 graus) |
| CA-03 | `infra/migrations/006_power_tool_object_types.sql` | `infra/tests/test_schema_db.py::test_grade_groups_check_mirrors_the_contract` (72 pares contra `InspectionCreate` 0.6.0), `::test_grade_check_equals_the_spec_expression_on_the_enum` (72 pares), `::test_power_tool_is_accepted_only_without_grade`, `::test_power_tool_check_values`, `::test_power_tool_migration_runs_again_without_error`, `::test_power_tool_migration_keeps_older_rows_valid`, `::test_power_tool_migration_is_the_latest_grade_check_migration`, `::test_values_outside_the_contract_are_refused`; `infra/tests/test_migrate_db.py::test_running_sql_file_again_changes_nothing`, `::test_power_tool_migration_supersedes_the_hand_tool_checks`; `infra/tests/test_migration_files.py::test_repository_migrations_are_valid` |
| CA-04 | (sem código novo na API: contrato 0.6.0 e migração 006) | `api/tests/test_power_tools.py::test_post_power_tool_without_grade_is_created_and_listed`, `::test_post_power_tool_with_a_grade_is_422`, `::test_batch_with_power_tools`, `::test_batch_with_one_graded_power_tool_is_refused_whole`, `::test_read_filters_accept_a_power_tool`, `::test_spc_leaves_out_a_lot_of_power_tools` (cenário do CA), `::test_spc_filter_by_a_power_tool_is_422`, `::test_lot_selection_leaves_out_power_tools`, `::test_power_tools_inside_a_screw_lot_do_not_change_n`, `::test_spc_object_type_is_unchanged`, `::test_openapi_spc_enum_is_unchanged`, `::test_no_grade_forbidden_type_enters_the_spc_filter`, `::test_summary_leaves_power_tools_out_of_the_defect_rate`, `::test_summary_of_power_tools_only_has_null_rate`, `::test_health_shows_the_contract_0_6_0` |
| CA-05 | `edge/src/qc_edge/onnx_inferencer.py` (sem mudança: `GRADE_FORBIDDEN_VALUES` vem do contrato), `edge/src/qc_edge/decision.py` (só docstring) | `edge/tests/test_power_tools.py::test_model_with_a_power_tool_needs_it_in_ungraded` (ausente e `[]` → `ModelLoadError`; `["drill"]` carrega), `::test_model_with_every_power_tool_must_list_all_of_them`, `::test_power_tool_outside_object_types_is_refused`, `::test_decided_power_tool_has_no_grade`, `::test_capture_of_a_power_tool_goes_to_the_outbox_without_grade`, `::test_power_tool_verdict`, `::test_console_row_of_a_power_tool` |
| CA-06 | `edge/src/qc_edge/collect.py` (`DatasetObjectType`, `POWER_TOOL_OBJECT_TYPES`, `UNGRADED_DATASET_TYPES`, `ITEM_PREFIX_TYPES`, `_parse_grade`, cobertura), `edge/src/qc_edge/app.py` (seletor, cobertura), `edge/src/qc_edge/static/capture.js` | `edge/tests/test_power_tools.py::test_collect_of_a_power_tool_through_the_route` (cenário do CA), `::test_power_tool_with_empty_grade_is_valid`, `::test_power_tool_with_a_grade_is_refused`, `::test_power_tool_needs_the_t_prefix`, `::test_t_prefix_admits_the_power_tools`, `::test_power_tools_mirror_the_contract`, `::test_collect_selector_lists_the_power_tools`, `::test_capture_script_knows_the_power_tools`, `::test_coverage_counts_power_tools_in_one_row_each`, `::test_console_coverage_has_a_row_per_power_tool`; `edge/tests/test_collect.py::test_coverage_of_a_missing_manifest`, `::test_tool_types_mirror_the_contract`; `edge/tests/test_collect_route.py::test_console_coverage_without_manifest`; `edge/tests/test_tools.py::test_collect_selector_offers_the_tools` |
| CA-07 | `edge/src/qc_edge/importer.py` (`_grade_problem`, `_UNGRADED_TYPES`) | `edge/tests/test_importer.py::test_power_tools_are_imported_without_grade`, `::test_every_power_tool_is_accepted_with_t_and_no_grade`, `::test_graded_power_tool_refuses_the_whole_plan` (cenário do CA), `::test_power_tools_count_in_their_coverage_row`, `::test_contributor_row_problems` (casos `power-tool-grade`, `screw-prefix-power-tool`, `other-prefix-power-tool`), `::test_external_row_problems` (casos `ext-power-tool-grade`, `ext-power-tool-xs`) |
| CA-08 | `dashboard/src/qc_dashboard/charts.py` (`OBJECT_TYPE_ORDER`, `OBJECT_TYPE_COLORS`), `dashboard/src/qc_dashboard/formatting.py` (só docstring; `inspection_grade_label` já cobria) | `dashboard/tests/test_power_tools.py::test_history_rows_of_a_drill_without_grade` (cenário do CA), `::test_history_rows_of_every_power_tool`, `::test_object_type_label_of_the_power_tools`, `::test_history_csv_writes_sem_grau_for_a_power_tool`, `::test_chart_order_puts_the_power_tools_before_unknown`, `::test_by_object_type_counts_power_tools`, `::test_spc_filter_never_offers_a_power_tool`, `::test_history_type_filter_offers_the_power_tools`; `dashboard/tests/test_charts.py::test_by_object_type_is_horizontal`, `::test_object_type_order_and_colors_cover_every_type` |
| CA-14 (manual) | — | Trabalho humano (§3.3): unidades e fotos das 4 elétricas, relatório de dados, split com `--extend-test-types`/`--defer-types`, treino no Colab, `metrics.json` com a `type_confusion` completa e o CHANGELOG, e o modelo na borda com 4 elétricas fotografadas pela página. Não bloqueia o merge da Parte A (como o CA-21 da SPEC-016). |

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

Resultado da suíte completa (sem o extra `train`, com o `partqc_test`, `CI=true`): **16 failed, 8668 passed, 142 skipped** (30 min 52 s). Das 16 falhas, 14 são testes de aceite antigos que esta SPEC invalida de propósito (tabela abaixo) e 2 já falham no commit base da branch (`70ee820`), por causa de `reviews/SPEC-020/r1-review-report.md` (ver "Observação fora do escopo"). Todos os testes do autor da Parte A passam. Os testes de `ml/` (Parte B, ainda não implementada) passam com o contrato 0.6.0.

### Testes de aceite antigos que precisam de ajuste (`docs/architecture.md` §10; quem ajusta é o tester)

| Arquivo | Teste | O que falha | Requisito da SPEC-021 | Na §3.1? |
|---|---|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_018.py` | `test_ca01_contracts_version_is_0_5_0` | `'0.6.0' == '0.5.0'`; junto, no mesmo commit, o par do `qc-contracts` no `ALLOWED_EXACT` do CA-28 da SPEC-004 (`api/tests/acceptance/test_spec_004.py`, ainda passa) passa a apontar para `test_spec_021.py` com `0.6.0` | §3.1 (contrato 0.6.0), CA-01; "Expectativas de versão" da §10 | sim |
| `packages/contracts/tests/acceptance/test_spec_016.py` | `test_ca01_object_type_members_in_order` | a lista completa do `ObjectType` tem 12 valores, não 8 (os 8 primeiros continuam na ordem da SPEC-016) | §3.1 (os 4 valores depois de `phillips_screwdriver`), CA-01 | sim |
| `packages/contracts/tests/acceptance/test_spec_016.py` | `test_ca01_grade_groups_are_disjoint_and_cover_the_enum` | `12 == 8` (os grupos continuam disjuntos e somam o enum inteiro; `GRADE_FORBIDDEN_OBJECT_TYPES` tem `unknown` e as 4 elétricas) | §3.1 (as 4 em `GRADE_FORBIDDEN_OBJECT_TYPES`), §4 (os três grupos somam os 12), CA-01 | sim |
| `packages/contracts/tests/acceptance/test_spec_002.py` | `test_ca17_labels_match_enums_and_are_immutable[object_type]` | `KeyError: 'angle_grinder'` (a tabela esperada tem os 8 rótulos anteriores) | §3.1 (rótulos `esmerilhadeira`, `serra`, `furadeira`, `parafusadeira`), CA-01 | não (mesmo caso que a SPEC-016 listou no dev-report dela) |
| `packages/preprocess/tests/acceptance/test_spec_023.py` | `test_ca12_spec002_acceptance_suites_still_pass` | roda a suíte de aceite da SPEC-002 em subprocesso e herda a falha acima; volta a passar quando o `test_spec_002.py` for ajustado | §3.1 (indireto) | não |
| `api/tests/acceptance/test_spec_005.py` | `test_ca08_summary_without_rows` | `len(by_object_type) == 3 + 5`: o resumo tem as 12 chaves do enum (a SPEC-005 exige toda chave do enum, com 0) | §3.1 (`ObjectType` 0.6.0) | não |
| `api/tests/acceptance/test_spec_016.py` | `test_extra_tool_migration_keeps_mvp_rows_and_runs_again` | procura `"tool_object_types"` no nome dos arquivos e espera exatamente 1; o nome `006_power_tool_object_types.sql` vem da SPEC-021 §3.1 (`NNN_power_tool_object_types.sql`), e agora são 2 | §3.1 (nome da migração) | não |
| `edge/tests/acceptance/test_spec_010.py` | `test_ca15_compute_coverage_counts_images_and_items`, `test_ca15_missing_manifest_is_an_empty_table`, `test_extra_compute_coverage_ignores_unknown_cells` | a tabela de cobertura tem 40 células (11 + 25 + 4 elétricas), não 36 | §3.1 ("a tabela de cobertura do console ganha uma linha por tipo, sem grau") | não |
| `edge/tests/acceptance/test_spec_016.py` | `test_extra_coverage_has_the_tool_rows` | `40 == 11 + 25` (as linhas das manuais continuam todas lá) | §3.1 (cobertura) | não |
| `dashboard/tests/acceptance/test_spec_016.py` | `test_extra_object_type_order_and_colors` | `OBJECT_TYPE_ORDER` tem as 4 elétricas entre as manuais e `unknown` | §3.1 (dashboard: rótulos e cores) | não |
| `dashboard/tests/acceptance/test_spec_013.py` | `test_extra_by_object_type_and_series_charts` | as barras do gráfico por tipo incluem as 4 elétricas | §3.1 (dashboard: rótulos e cores) | não |
| `dashboard/tests/acceptance/test_spec_029.py` | `test_ca01_spec013_suite_passes_and_hides_key_with_local_secrets` | roda a suíte de aceite da SPEC-013 em subprocesso e herda a falha acima | §3.1 (indireto) | não |

Os testes de `ml/tests/acceptance/` não falham agora, porque a Parte B ainda não mudou o `qc-ml`. As asserções da SPEC-016 sobre `GRADE_FORBIDDEN_OBJECT_TYPES == {unknown}` nos outros componentes não falharam nesta rodada (só as duas do `packages/contracts` acima).

### Decisões tomadas dentro do escopo da SPEC

1. **Migração 006 e o nome da restrição.** Como na 003, o `check` de grau mantém o nome `inspections_grade_null_iff_unknown` e é escrito como duas implicações: `(object_type not in ('screw','nut') or grade is not null) and (object_type not in ('unknown', <as 4 elétricas>) or grade is null)`. No domínio que o `check` de `object_type` admite, é a expressão "três ramos" com as elétricas no ramo sem grau (o teste `test_grade_check_equals_the_spec_expression_on_the_enum` compara as duas no Postgres para os 72 pares); um valor fora do enum continua recusado só por `inspections_object_type_check` (CA-06 da SPEC-003).
2. **Rodar a 003 de novo depois da 006.** A 003 troca os dois `check` pela versão de 8 valores; rodá-la de novo sozinha, num banco já na 006, traz de volta o `check` antigo (é o comportamento de qualquer migração que substitui um `check` de outra). Dois testes do autor rodavam a 003 de novo no banco compartilhado da sessão e deixariam os testes seguintes com o `check` de 8 valores. Ajustei: `infra/tests/test_schema_db.py` ganhou a fixture `rerun_003`, que roda a 006 de novo no fim; e `infra/tests/test_migrate_db.py::test_running_sql_file_again_changes_nothing` passa a rodar, depois do arquivo repetido duas vezes, os arquivos posteriores, também de novo (para a última migração, é o "roda de novo e não muda nada" de antes). Um teste novo (`test_power_tool_migration_supersedes_the_hand_tool_checks`) documenta a substituição. A orientação para quem roda à mão no SQL Editor fica no cabeçalho da 006: rodar as migrações em ordem.
3. **Problema de importação de uma elétrica com grau.** A SPEC-036 §4.2 tem uma lista fechada de códigos para `grade` (`invalid_grade`, `missing_grade`, `grade_on_other`), e o CA-09 desta SPEC pede no `qc-ml` "o mesmo código de problema que um `other` com grau preenchido". Para não inventar código, a importação dá `grade_on_other (grade)` também para uma elétrica com grau (documentado no `edge/README.md`). Na coleta, a resposta é 422 com `detail = "grade must be empty for a power tool"` (a mensagem do `other` citaria o tipo errado).
4. **Cobertura das elétricas.** Uma célula por elétrica (`grade` nulo), com a meta de identificação da §3.3: 90 imagens e 6 peças (mínimo 3, só no texto do console), constantes `POWER_TOOL_TARGET_*` e `POWER_TOOL_MIN_ITEMS` em `qc_edge.collect`. Uma linha do manifest de elétrica com grau não cabe em nenhuma célula (não é contada), como uma linha de parafuso sem grau. Na coluna "Grau" da tabela, as elétricas mostram `sem grau` (o "outro" continua com `—`). Ordem: parafuso, porca, as 5 manuais × 5 graus, as 4 elétricas, outro.
5. **`DatasetObjectType`** ganha as 4 depois das manuais (ordem do `ObjectType`); `TOOL_OBJECT_TYPES` continua só com as manuais (é o grupo de grau opcional, usado nas metas de grau) e o novo `POWER_TOOL_OBJECT_TYPES` tem as elétricas; o prefixo `T` admite os dois grupos. `UNGRADED_DATASET_TYPES` (`other` e as elétricas) é a regra de grau vazio da coleta e da importação.
6. **`capture.js`** (200 linhas, no limite dos testes das SPECs 007 e 010): `POWER` e `NO_GRADE` declarados; o grau fica vazio e desabilitado para `other` e as elétricas, e a checagem do celular só pede grau para os outros tipos. Para caber, `STORE_PREFIX` foi para a mesma declaração de `MAX_SIDE`.
7. **Cores do gráfico por tipo:** `#F58518` (esmerilhadeira), `#54A24B` (serra), `#EECA3B` (furadeira) e `#17BECF` (parafusadeira), distintas das 8 anteriores (teste existente `test_object_type_order_and_colors_cover_every_type`).
8. **API sem código novo.** O `SpcObjectType` e a docstring dele não mudaram (SPEC §3.1: "nada além do contrato e da migração"). O `/api/v1/health` passa a mostrar `contract_version = 0.6.0`. A versão da `qc-api` não muda.
9. `edge/README.md`: a linha do `labels.json` na tabela de artefatos estava desatualizada desde a SPEC-016 (não citava `ungraded_object_types`); atualizei junto com a regra das elétricas.
10. Nenhuma dependência nova; nenhuma variável de ambiente nova (`.env.example` sem mudança). Nada em `ml/` foi alterado (Parte B).

### SPEC_ISSUE (se houver)

Nenhum.

### Observação fora do escopo (não é desta SPEC)

`infra/tests/test_deploy_files.py::test_no_secret_material_in_tracked_files` falha já no commit base da branch (`70ee820`): acusa `postgres://u:p@` em `reviews/SPEC-020/r1-review-report.md` (relatório do reviewer da SPEC-020, um exemplo, não um segredo). Não toquei no arquivo (relatório de outro agente).

### Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (contracts, infra, api, edge e dashboard)
- [x] `.env.example` atualizado (se houver variável nova): nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nada em `ml/` alterado (Parte B do ml-engineer)
