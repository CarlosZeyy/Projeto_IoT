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

## Parte B (ml-engineer)

| Campo | Valor |
|---|---|
| Autor | ml-engineer |
| Commits | `ed54ac2` (dados, rótulos do modelo, gerador, PNG e CHANGELOG), `011a49e` (split), `02c4104` (fixture `tiny_model_power_tools` e `make_tiny_fixture.py`), `b6cf891` (testes do autor), `0963435` (README), `bf7e2a4` (testes do autor da SPEC-016 com os 8 tipos fixos) e o commit desta seção |

### Resumo

- **Dados:** `POWER_TOOL_OBJECT_TYPES` (novo, em `qc_ml.data`) vem do contrato: os membros de `GRADE_FORBIDDEN_OBJECT_TYPES` menos `unknown`, na ordem do `ObjectType` (`angle_grinder`, `saw`, `drill`, `cordless_screwdriver`). `KNOWN_OBJECT_TYPES` passa a ter 12 tipos (as elétricas depois das manuais). O prefixo `T`/`XT` aceita uma ferramenta manual ou elétrica. O grau da elétrica é vazio obrigatório: `GRADE_FORBIDDEN_DATASET_TYPES` (`other` e as elétricas) dá `grade_on_other`, o mesmo código do `other` com grau (também por override). `TOOL_OBJECT_TYPES` e `tool_grade_coverage` continuam só com as 5 manuais.
- **Rótulos do modelo:** `derive_model_labels` põe as elétricas com imagens no treino depois das manuais e as lista **sempre** em `ungraded_object_types`, sem passar pelo critério; `grade_target` devolve `None` para elas.
- **Split:** a extensão (`--extend-test-types`) e o adiamento (`--defer-types`) da SPEC-016 §4.7 valem para as elétricas, com o estrato só por tipo (`extension_strata` devolve `(tipo, "none")` para uma elétrica). Uma elétrica com menos de 3 peças não externas dá saída 2 com `too few items to extend the test: <tipo>` (regra já existente).
- **Gerador:** `make_synthetic_dataset(…, power_tool_items_per_type=0, external_power_tool_items_per_type=0)`, com silhuetas sintéticas das 4 elétricas, sem grau, em `raw/<tipo>/_/`, depois de todas as outras peças; com os dois em 0, os arquivos são os mesmos, byte a byte.
- **Fixture:** `ml/tests/fixtures/tiny_model_power_tools/` (12 tipos, `ungraded_object_types` = as 4 elétricas, 853.462 bytes), gerada por `ml/scripts/make_tiny_fixture.py --with-power-tools`.
- **Avaliação, limiares e export:** sem código novo. Os mecanismos da SPEC-016 já tratam um tipo de `ungraded_object_types`: as elétricas entram no `FU(t)` do `type_threshold`, ficam fora dos outros dois limiares e de `tool_grade_metrics`, e a `type_confusion` tem todos os tipos do modelo. Ajustes de apresentação: rótulos PT-BR das elétricas nas matrizes em PNG (`plots.TYPE_LABELS_PT`) e a linha "Tipos do modelo" do CHANGELOG também para um modelo com elétricas (decisão 6).
- **README:** seção "Ferramentas elétricas (Fase 3)" no `ml/README.md`, com o passo a passo da dupla (§3.3 e CA-14), e as novas opções do gerador e da fixture.

### Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-09 | `ml/src/qc_ml/data.py` (`POWER_TOOL_OBJECT_TYPES`, `KNOWN_OBJECT_TYPES`, `GRADE_FORBIDDEN_DATASET_TYPES`, `ITEM_PREFIX_TYPES`, `_row_problems`), `ml/src/qc_ml/synthetic.py` | `ml/tests/test_power_tools.py::test_ca09_power_tools_load_without_error`, `::test_ca09_power_tool_with_grade_has_the_code_of_other` (4 elétricas, comparado com o `other` com grau), `::test_override_with_a_grade_on_a_power_tool_is_refused`, `::test_power_tool_with_s_prefix_is_a_prefix_mismatch`, `::test_item_prefix_matches_power_tools`, `::test_power_tools_are_the_grade_forbidden_types_of_the_contract_but_unknown`, `::test_power_tools_stay_out_of_the_grade_criterion`; `ml/tests/test_tools_data.py::test_tool_types_are_the_grade_optional_types_of_the_contract` |
| CA-10 | `ml/src/qc_ml/data.py` (`derive_model_labels`, `grade_target`) | `ml/tests/test_power_tools.py::test_ca10_power_tools_are_always_ungraded`, `::test_power_tools_are_ungraded_next_to_a_graded_hand_tool`, `::test_power_tool_without_train_images_is_not_a_model_type`, `::test_ungraded_power_tools_pass_the_labels_checks` |
| CA-11 | `ml/src/qc_ml/split.py` (`make_split`, `extension_strata`) | `ml/tests/test_power_tools.py::test_ca11_power_tools_need_a_decision`, `::test_ca11_extension_of_the_power_tools` (`split_v1` sem ferramentas, 6 peças por elétrica: 4/1/1 em cada uma, externas no treino, `split_v1` mantido), `::test_ca11_power_tool_with_two_items_is_refused`, `::test_power_tools_can_be_deferred`, `::test_power_tool_extension_stratum_is_the_whole_type` |
| CA-12 | `ml/tests/fixtures/tiny_model_power_tools/`, `ml/scripts/make_tiny_fixture.py` (`--with-power-tools`); `ml/src/qc_ml/evaluate.py` e `thresholds.py` sem mudança | `ml/tests/test_power_tools.py::test_ca12_evaluate_with_power_tools` (`type_confusion` 12×12, as 4 em `labels.ungraded_object_types`, nenhuma em `tool_grade_metrics`, `list(metrics) == METRIC_KEYS`), `::test_fixture_labels_have_the_12_types_and_the_4_power_tools_ungraded`, `::test_fixture_parity_with_onnxruntime`; com torch: `::test_make_tiny_fixture_with_power_tools` |
| CA-13 | `ml/src/qc_ml/synthetic.py` (`make_synthetic_dataset`, `TOOL_POLYGONS`, `POWER_TOOL_COLOR`) | `ml/tests/test_power_tools.py::test_ca13_defaults_are_byte_for_byte_the_same`, `::test_power_tools_come_after_every_other_item`, `::test_external_power_tools_alone_write_the_registry`, `::test_generator_checks_the_power_tool_counts`, `::test_add_synthetic_item_draws_a_power_tool` |
| Apresentação (PNG e CHANGELOG) | `ml/src/qc_ml/plots.py`, `ml/src/qc_ml/report.py` (`model_types_lines`) | `ml/tests/test_power_tools.py::test_confusion_labels_of_the_power_tools`, `::test_changelog_lists_a_model_with_power_tools_only` |
| CA-14 (manual) | `ml/README.md` (seção "Ferramentas elétricas (Fase 3)", passo a passo) | — (trabalho da dupla) |

### Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run --package qc-ml pytest ml/tests -q                         # ambiente do CI, sem torch
# com torch, num ambiente separado (não mexe no .venv do CI):
UV_PROJECT_ENVIRONMENT=$HOME/.cache/partqc-venv-train uv sync --all-packages --extra train --frozen
$HOME/.cache/partqc-venv-train/bin/python -m pytest ml/tests -q
```

Resultados (2026-10-27):

- `uv run ruff check .` e `uv run ruff format --check .`: limpos.
- `ml/tests`, ambiente do CI (sem torch): **1 failed, 969 passed, 28 skipped** (16 min). A falha é o aceite antigo da tabela abaixo.
- `ml/tests` com o extra `train` (inclui os testes *slow* e os aceites com torch): **1 failed, 1017 passed, 2 skipped** (20 min); a mesma falha.
- `make_tiny_fixture.py --with-tools` regenerado num diretório temporário reproduz a `tiny_model_tools` byte a byte (os 6 arquivos).
- Testes de `edge/` que importam `qc_ml.data` (`test_formats_equal_to_qc_ml`, CA-15 da SPEC-036): passam.
- Não rodei a suíte inteira com banco: a Parte B só muda `ml/`, e nenhum teste fora de `ml/` depende do que mudou, salvo os dois de `edge/` acima.
- Testes novos do autor: 45 em `ml/tests/test_power_tools.py` (1 com `pytest.importorskip("torch")`). Ajustados: `ml/tests/test_tools_data.py`, `test_tools_model.py` e `test_tools_torch.py` passam a montar os 8 tipos da SPEC-016 explicitamente (os 8 primeiros de `KNOWN_OBJECT_TYPES`).

### Testes de aceite antigos de `ml/` que passam a falhar por causa da Parte B (quem ajusta é o tester)

| Arquivo | Teste | O que falha | Requisito da SPEC-021 | Na §3.1? |
|---|---|---|---|---|
| `ml/tests/acceptance/test_spec_016.py` | `test_extra_criterion_constants` | `("screw", "nut", "other", *TOOLS) == KNOWN_OBJECT_TYPES`: `KNOWN_OBJECT_TYPES` tem 12 tipos (os 8 primeiros continuam na ordem da SPEC-016; `TOOL_OBJECT_TYPES` continua igual a `TOOLS`) | §3.1, Parte B ("os 4 tipos em `KNOWN_OBJECT_TYPES`"), CA-10 | não |

Nenhum outro aceite de `ml/` falha. Em particular, `test_spec_016.py` que regenera a fixture com `--with-tools` e confere 8 tipos continua passando (decisão 5), e as chaves de topo do `metrics.json` não mudam (CA-12).

### Decisões tomadas dentro do escopo da SPEC

1. **Grupos de tipos no `qc_ml`.** `POWER_TOOL_OBJECT_TYPES` é derivado do contrato (grau proibido, menos `unknown`), como `TOOL_OBJECT_TYPES` já era (grau opcional). `TOOL_OBJECT_TYPES` continua com as 5 manuais, porque é o grupo que pode ter grau: `tool_grade_coverage`, `tool_grade_metrics`, `GRADE_REQUIRED_DATASET_TYPES` e o `by_grade` das contagens dependem dele, e a SPEC manda o `tool_grade_coverage` continuar só com as manuais.
2. **Código do problema de grau.** Uma elétrica com grau dá `grade_on_other` (CA-09: "o mesmo código de problema que um `other` com grau"); a mensagem cita o tipo (`grade must be empty for drill, got 'good'`). Vale também para uma override que põe grau numa elétrica. É o mesmo código que a borda usa na importação (decisão 3 da Parte A).
3. **Estrato da extensão.** Sem grau, o `dominant_grade` de uma peça elétrica já é `"none"`, então o estrato só por tipo já saía sozinho. Deixei explícito em `extension_strata` (uma elétrica → `(tipo, "none")`) para não depender disso. No `split_v1` (sem versão anterior) as listas não são usadas, como na SPEC-016, e uma elétrica cai no estrato `(tipo, "none")` pelo mesmo motivo.
4. **Gerador.** As peças `T-` elétricas continuam a sequência `T-` depois das manuais (`T-026`… com `tool_items_per_stratum=1`), e as `XT-` elétricas continuam a sequência `XT-` depois das manuais externas. O teto de 999 peças `T-` (e 9.999 `XT-`) vale para manuais e elétricas juntas. As elétricas são desenhadas com cor de plástico (`POWER_TOOL_COLOR`, verde-azulado) e silhuetas próprias (disco e empunhadura lateral da esmerilhadeira, base e proteção da serra circular, corpo em pistola com bateria da furadeira e da parafusadeira), sem ferrugem. As origens seguem as das manuais: `capture` sem linha no `sources.csv`; `external` com a fonte `synthetic`.
5. **`make_tiny_fixture.py --with-tools`.** Antes, a opção usava `KNOWN_OBJECT_TYPES`, que agora tem 12 tipos; passei a montar os 8 tipos da SPEC-016 explicitamente (`MVP_OBJECT_TYPES` + `TOOL_OBJECT_TYPES`). Conferido: regenerada num diretório temporário, a `tiny_model_tools` sai igual byte a byte. `--with-tools` e `--with-power-tools` são mutuamente exclusivas (saída 2).
6. **CHANGELOG.** A SPEC-016 §4.8 pede a linha "Tipos do modelo" e a observação sobre a `type_accuracy` "quando o modelo tem ferramentas"; o código só olhava as manuais. Passei a considerar também as elétricas, porque um modelo com elétricas e sem manuais (manuais adiadas, por exemplo) tem a mesma não comparabilidade da `type_accuracy` (ADR-022), e o CA-14 pede a entrada do CHANGELOG. Conferir se o reviewer concorda com essa leitura.
7. **`ungraded_object_types` da fixture.** Li "(12 tipos; `ungraded_object_types` com as 4 elétricas)" como exatamente as 4 elétricas, sem o `allen_key` da `tiny_model_tools`.
8. **O que não mudou:** `false_unknown_rate` do `metrics.json` continua em `screw`/`nut`; `counts.<split>.by_class` das elétricas tem `by_grade = {}` (como o `other`); o relatório de dados ganha as 4 chaves em `counts` e `items_per_grade` (com zeros nos dados do MVP), como as manuais na SPEC-016. `agreement.py` não muda (só pareia `screw`/`nut`).
9. **Ambiente com torch.** Para gerar a fixture e rodar os testes com torch, usei um ambiente separado (`$HOME/.cache/partqc-venv-train`, `UV_PROJECT_ENVIRONMENT`), sem tocar no `.venv` do worktree, que continua no estado do CI (sem torch). Pode ser apagado depois. Nenhuma dependência nova; `uv.lock` sem mudança.

### SPEC_ISSUE

Nenhum.

### Observações para o architect (fora do escopo da Parte B, não bloqueiam os CAs)

- Pela Definição de pronto da SPEC, `docs/architecture.md` §3.1 e `docs/dataset-protocol.md` (captura das elétricas, §3.3 da SPEC) ficam com o architect. O `ml/README.md` já traz o passo a passo.

### Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes do autor passando (sem torch e com torch); a única falha em `ml/tests` é o aceite antigo listado acima
- [x] Seeds fixas: gerador (`seed`), split (`seed` da CLI; extensão com `default_rng(seed)` por tipo), fixture (`SEED = 0`)
- [x] Nenhuma métrica reportada: não houve treino real (CA-14 é manual)
- [x] Nenhuma imagem real, nenhum `.onnx` de modelo real; a fixture usa só entradas sintéticas e o `model.onnx` dela não é ignorado pelo `.gitignore` (conferido com `git check-ignore`), como o das outras fixtures
- [x] Nenhum arquivo fora de `ml/` alterado (salvo esta seção do relatório) e nenhum em `tests/acceptance/`
