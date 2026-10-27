# SPEC-021 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-021](../../docs/specs/SPEC-021-ferramentas-eletricas.md) |
| Rodada | r1 (Partes A e B) |
| Tester | tester |
| Commit testado | `fb1842c` (código de produção e testes do autor de `bf7e2a4`/`7e8a75f`; depois disso só `docs/` e este commit de testes) |
| **Veredicto** | **FAIL**: todos os CAs automatizados têm teste e passam (226 testes de aceite novos), o ruff está limpo e não há SPEC_ISSUE, mas a **suíte inteira não passa**: 2 testes de segredo falham por causa de uma linha do `reviews/SPEC-021/r1-dev-report.md` (bug T-01). O CA-14 é manual e fica pendente para a dupla. |

Os testes foram escritos a partir do texto da SPEC (§3.1, §4 e §5), em caixa-preta, antes da leitura da implementação; a leitura veio depois, só para os exploratórios de borda. Para os padrões de interface (fixtures de banco, modelo dummy, importador, `AppTest`, CLI do split), segui os aceites da SPEC-016, de que esta SPEC é extensão.

- Datasets todos sintéticos (`make_synthetic_dataset` e imagens geradas em memória), sempre em diretórios temporários; nada de `ml/data/` nem de `~/partqc-entrada/`; nenhuma imagem real (R-14).
- Chaves de dispositivo, tokens de sessão e marcadores gerados em tempo de execução (R-03).
- Fronteiras simuladas: só o HTTP do dashboard (`httpx.MockTransport`) e o relógio e o `sleep` do importador. Banco real (`partqc_test`) na API, modelo dummy ONNX da SPEC-008 §6 (construído no teste) na borda e a fixture ONNX `tiny_model_power_tools` no ML, sem torch.
- O split roda pela CLI (`python -m qc_ml.split`, subprocesso); nenhum teste roda o pytest em subprocesso.
- **Leitura do CA-07** (nota do orquestrador, vinda do architect, durante esta rodada): "a primeira linha entra e a segunda é recusada sem gravar nada" se lê pela SPEC-036 §4.2: o plano é validado inteiro; "entra" quer dizer "passa na validação" (nenhum problema reportado para ela) e, como a segunda linha tem problema, nada é gravado. O teste do CA verifica exatamente isso (saída 2, problemas só na linha 3, coluna `grade`, dataset igual ao de antes); dois testes de contraste cobrem o plano só com a primeira linha (sai com 0 e grava) e só com a segunda (sai com 2, nada gravado). Ver as Observações.

## Arquivos e contagem

| Arquivo | Testes coletados | Itens de CA (`test_caNN_*`) | Exploratórios (`test_extra_*`, com parametrização) |
|---|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_021.py` | 130 | 7 | 123 |
| `api/tests/acceptance/test_spec_021.py` | 18 | 5 | 13 |
| `edge/tests/acceptance/test_spec_021.py` | 53 | 8 | 45 |
| `dashboard/tests/acceptance/test_spec_021.py` | 11 | 1 | 10 |
| `ml/tests/acceptance/test_spec_021.py` | 14 | 7 | 7 |
| **Total** | **226** | **28** | **198** |

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `packages/contracts/tests/acceptance/test_spec_021.py::test_ca01_contracts_version_is_0_6_0` (`__version__ == metadata.version == "0.6.0"`), `::test_ca01_last_four_object_types_are_the_power_tools_in_order`, `::test_ca01_power_tool_labels_pt`, `::test_ca01_grade_forbidden_group_is_unknown_and_the_power_tools`, `::test_ca01_pyproject_and_readme_history` | ✅ |
| CA-02 | `packages/contracts/.../test_spec_021.py::test_ca02_drill_without_grade_is_accepted`, `::test_ca02_drill_with_grade_is_rejected` | ✅ |
| CA-03 | `api/tests/acceptance/test_spec_021.py::test_ca03_database_accepts_exactly_the_contract_pairs` (12 tipos × 6 graus = 72 pares contra o `InspectionCreate` 0.6.0; 45 aceitos, os outros 27 com `23514`) | ✅ |
| CA-04 | `api/.../test_spec_021.py::test_ca04_post_drill_without_grade_is_201`, `::test_ca04_spc_leaves_the_drill_lot_out` (L-04 fora de `points` e de `excluded_lots`), `::test_ca04_spc_filter_by_drill_is_422`, `::test_ca04_openapi_spc_object_type_enum_is_the_spec016_one` | ✅ |
| CA-05 | `edge/tests/acceptance/test_spec_021.py::test_ca05_model_with_drill_and_empty_ungraded_list_is_refused`, `::test_ca05_model_with_drill_listed_as_ungraded_loads`, `::test_ca05_decision_of_a_drill_has_no_grade` | ✅ |
| CA-06 | `edge/.../test_spec_021.py::test_ca06_drill_without_grade_is_collected_into_the_no_grade_dir` (`raw/drill/_/T-010__1__…`, linha no manifest com grau vazio), `::test_ca06_drill_with_grade_is_422_and_nothing_written` | ✅ |
| CA-07 | `edge/.../test_spec_021.py::test_ca07_plan_with_both_rows_refuses_the_saw_and_writes_nothing` (o plano do CA), `::test_ca07_angle_grinder_row_alone_is_imported_without_grade` (contraste: `raw/angle_grinder/_/XT-0010__0__…` e a linha `external` no `sources.csv`), `::test_ca07_saw_row_with_grade_alone_is_refused` | ✅ (na leitura acima) |
| CA-08 | `dashboard/tests/acceptance/test_spec_021.py::test_ca08_history_row_of_a_drill_without_grade` | ✅ |
| CA-09 | `ml/tests/acceptance/test_spec_021.py::test_ca09_power_tools_load_with_12_t_items`, `::test_ca09_power_tool_with_grade_has_the_code_of_other_with_grade` (mesmo conjunto de códigos que um `other` editado para `good`: `grade_on_other`) | ✅ |
| CA-10 | `ml/.../test_spec_021.py::test_ca10_model_labels_end_with_the_power_tools_all_ungraded` | ✅ |
| CA-11 | `ml/.../test_spec_021.py::test_ca11_extend_the_test_with_the_power_tools` (saída 0; cada elétrica em `train`, `val` e `test`; linhas do `split_v1` mantidas), `::test_ca11_power_tool_with_two_items_is_refused` (`saw` com 2 peças: saída 2, `too few items to extend the test`, nada gravado) | ✅ |
| CA-12 | `ml/.../test_spec_021.py::test_ca12_evaluate_with_the_power_tools` (`thresholds` e `evaluate` sem torch: `type_confusion` 12×12, as 4 em `labels.ungraded_object_types`, nenhuma em `tool_grade_metrics`, chaves de topo = as da SPEC-016) | ✅ |
| CA-13 | `ml/.../test_spec_021.py::test_ca13_defaults_are_byte_for_byte_the_same` | ✅ |
| CA-14 | manual (unidades e fotos das elétricas, relatório de dados, split, treino no Colab, `metrics.json` e CHANGELOG, modelo na borda) | ⏳ pendente: trabalho da dupla; não bloqueia o merge (Definição de pronto) |

## Ajustes em testes de aceite de SPECs anteriores (`docs/architecture.md` §10)

Todos listados na §3.1 da SPEC ou no pedido do orquestrador (com o requisito da SPEC-021 que os motiva). Só as asserções afetadas mudaram; nenhum `test_caNN_` foi removido nem renomeado; nenhum teste extra foi removido nem renomeado. A intenção de cada CA antigo continua verificada para os tipos que ele cobria. O ajuste da versão e o do `ALLOWED_EXACT` estão no mesmo commit.

| Arquivo | Teste | Antes → depois | Requisito da SPEC-021 |
|---|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_018.py` | `test_ca01_contracts_version_is_0_5_0` | `__version__ == metadata.version == "0.5.0"` → forma de piso: `__version__ == metadata.version`, `X.Y.Z` e `(0, 5, 0) <= versão < (1, 0, 0)` (a mesma forma que o `test_spec_016.py` já usa) | §3.1 (contrato 0.6.0; "as asserções exatas de `0.5.0` … viram a forma de piso"), CA-01; "Expectativas de versão" da §10 |
| `api/tests/acceptance/test_spec_004.py` | `test_ca28_version_expectations_migrated` (constante `ALLOWED_EXACT`) | `(SPEC018_CONTRACTS, "qc_contracts", "0.5.0")` → `(SPEC021_CONTRACTS, "qc_contracts", "0.6.0")`, com a constante `SPEC021_CONTRACTS` nova ao lado das outras | §3.1 ("o `ALLOWED_EXACT` do CA-28 da SPEC-004 passa a apontar para `test_spec_021.py` com `0.6.0`, no mesmo commit"); `docs/architecture.md` §10 (arquivo vigente, `fb1842c`) |
| `packages/contracts/tests/acceptance/test_spec_016.py` | `test_ca01_object_type_members_in_order` | `[m.value for m in ObjectType] == ALL_TYPES` (8) → os 8 primeiros membros `== ALL_TYPES`, na mesma ordem | §3.1 ("os 8 primeiros valores, nessa ordem"; os 4 valores depois de `phillips_screwdriver`), CA-01 |
| `packages/contracts/tests/acceptance/test_spec_016.py` | `test_ca01_grade_groups_are_disjoint_and_cover_the_enum` | `sum(len(g)) == 8` → `== len(ObjectType)`; `GRADE_FORBIDDEN == {"unknown"}` → `"unknown" in GRADE_FORBIDDEN`. Continuam: grupos disjuntos, união = enum, obrigatório = `{screw, nut}`, opcional = as 5 manuais | §3.1 ("`unknown` no grupo"), §4 (os três grupos somam os 12), CA-01 |
| `packages/contracts/tests/acceptance/test_spec_002.py` | `test_ca17_labels_match_enums_and_are_immutable[object_type]` | tabela esperada com 8 rótulos → mais os 4 (`esmerilhadeira`, `serra`, `furadeira`, `parafusadeira`), como a SPEC-016 fez com as manuais; as checagens (mapa imutável, uma entrada por membro, rótulo de cada membro) não mudam | §3.1 (rótulos), CA-01 |
| `packages/preprocess/tests/acceptance/test_spec_023.py` | `test_ca12_spec002_acceptance_suites_still_pass` | nenhuma linha mudou: roda a suíte de aceite da SPEC-002 em subprocesso e volta a passar com o ajuste acima | indireto (§3.1) |
| `api/tests/acceptance/test_spec_005.py` | `test_ca08_summary_without_rows` | `len(by_object_type) == 3 + 5` → `== 3 + 5 + 4` (a igualdade com `{o: 0 for o in ObjectType}`, que é o que o CA-08 promete, não mudou) | §3.1 (`ObjectType` 0.6.0) |
| `api/tests/acceptance/test_spec_016.py` | `test_extra_tool_migration_keeps_mvp_rows_and_runs_again` | o filtro `"tool_object_types" in p.name` (que agora casa a 003 e a 006) → a 003, excluída a `*power_tool_object_types*`; a 006 também fica fora do conjunto "antigo" (ela alarga os mesmos `check`, e com ela o `pliers` seria aceito antes da 003); `len(applied) == 1` → `== 1 + len(power_files)` (pendentes: a 003 e a 006). O resto (linhas do MVP mantidas, 003 roda de novo sem erro, `check` estáveis, nada pendente no fim) não mudou | §3.1 (nome `NNN_power_tool_object_types.sql`) |
| `edge/tests/acceptance/test_spec_010.py` | `test_ca15_compute_coverage_counts_images_and_items` | `len(cells) == 11 + 25` → `11 + 25 + 4`; o conjunto de chaves ganha `(elétrica, None)` para as 4 (constante `POWER_021` nova ao lado da `TOOLS_016`). Contagens e metas das células do CA-15 não mudaram | §3.1 ("a tabela de cobertura do console ganha uma linha por tipo, sem grau") |
| `edge/tests/acceptance/test_spec_010.py` | `test_ca15_missing_manifest_is_an_empty_table` | `len(cells) == 11 + 25` → `11 + 25 + 4` | idem |
| `edge/tests/acceptance/test_spec_010.py` | `test_extra_compute_coverage_ignores_unknown_cells` | `len(cells) == 11 + 25` → `11 + 25 + 4` | idem |
| `edge/tests/acceptance/test_spec_016.py` | `test_extra_coverage_has_the_tool_rows` | `len(cells) == 11 + 25` → `11 + 25 + 4` (as 25 células das manuais continuam verificadas uma a uma) | idem |
| `dashboard/tests/acceptance/test_spec_016.py` | `test_extra_object_type_order_and_colors` | `order == ["screw", "nut", *TOOLS, "unknown"]` → a ordem cobre o enum inteiro e, sem as 4 elétricas, é exatamente essa lista (ordem relativa da SPEC-016 mantida); cores distintas, sem mudança | §3.1 (dashboard: rótulos e cores) |
| `dashboard/tests/acceptance/test_spec_013.py` | `test_extra_by_object_type_and_series_charts` | conjunto das barras com 8 rótulos → mais os 4 das elétricas | §3.1 (dashboard: rótulos e cores) |
| `dashboard/tests/acceptance/test_spec_029.py` | `test_ca01_spec013_suite_passes_and_hides_key_with_local_secrets` | nenhuma linha mudou: roda a suíte de aceite da SPEC-013 em subprocesso e volta a passar com o ajuste acima | indireto (§3.1) |
| `ml/tests/acceptance/test_spec_016.py` | `test_extra_criterion_constants` | `("screw", "nut", "other", *TOOLS) == KNOWN_OBJECT_TYPES` → `== KNOWN_OBJECT_TYPES[:8]`; `TOOL_OBJECT_TYPES == TOOLS` e as constantes do critério não mudaram | §3.1, Parte B ("os 4 tipos em `KNOWN_OBJECT_TYPES`"; `tool_grade_coverage` continua só com as manuais) |

Nenhum desses ajustes muda o que um CA antigo garante; por isso não há SPEC_ISSUE por ajuste.

O ambiente com torch (`$HOME/.cache/partqc-venv-train`) não foi usado: nenhum teste de aceite novo depende de torch, e nenhum aceite antigo com torch foi ajustado.

## Suíte completa

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
FAILED infra/tests/acceptance/test_spec_015.py::test_ca05_no_secret_material_outside_docs
  - reviews/SPEC-021/r1-dev-report.md:87: postgres URL with a password outside the rules
FAILED infra/tests/test_deploy_files.py::test_no_secret_material_in_tracked_files
  - reviews/SPEC-021/r1-dev-report.md: <URL postgres de exemplo com usuário e senha>
2 failed, 8952 passed, 143 skipped, 1 warning in 1889.40s (0:31:29)

(ambiente do CI, sem o extra train; os 143 skipped são os testes de Docker, os que
precisam de torch e os demais marcados para ambiente específico)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
291 files already formatted

Arquivos de aceite antigos ajustados, rodados juntos antes da suíte inteira (com banco):
1062 passed (contracts/acceptance, preprocess test_spec_023, api test_spec_004/005/016,
edge test_spec_010/016, dashboard test_spec_013/016/029)
```

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | média (bloqueia o CI e o portão R-09; não afeta código) | Definição de pronto ("CI verde"); CA-05 da SPEC-015 e o teste de segredo do autor da SPEC-015 | 1. Na branch, `CI=true TEST_DATABASE_URL=… uv run pytest -q infra/tests/acceptance/test_spec_015.py::test_ca05_no_secret_material_outside_docs infra/tests/test_deploy_files.py::test_no_secret_material_in_tracked_files`. | Os 2 passam (nenhum arquivo versionado fora das regras com URL Postgres com senha). | Os 2 falham, acusando `reviews/SPEC-021/r1-dev-report.md` linha 87: a "Observação fora do escopo" da Parte A cita, entre crases, o mesmo exemplo de URL Postgres com usuário e senha que fazia o relatório da SPEC-020 falhar. O relatório da SPEC-020 já foi corrigido (merge da 020 em `de2afcc`), mas a citação literal no dev-report da 021 faz o scanner acusar este arquivo. **Correção sugerida (developer, dono do arquivo):** reescrever a linha 87 sem o literal (por exemplo, "acusa uma URL Postgres de exemplo com usuário e senha") ou remover a observação, que já não vale depois do merge da 020. O tester não altera o arquivo (R-07). |

## Testes exploratórios (além dos critérios)

Cobertos por testes `test_extra_*` (passam):

- **Contrato:** matriz completa de 12 tipos × 6 graus (as 8 antigas com a regra da SPEC-016, as elétricas só sem grau) no `InspectionCreate` e as 4 elétricas × 6 no `InspectionRead`; elétrica com só `grade_score` ou só `grade_confidence` recusada; mensagens de erro sem valores (marcador no `lot_id`, grau e tipo ausentes da mensagem); variantes (`Drill`, `drill `, `angle-grinder`, `circular_saw`, `furadeira`, `lathe`) recusadas; round trip JSON; grupos disjuntos somando 12; rótulos antigos iguais e 12 rótulos distintos.
- **Banco e API:** **migração 006 repetida** num banco próprio (`partqc_test_spec021_*`, criado e apagado): aplicada sobre um banco nas 001–005 com linhas de `screw`, `pliers` (com e sem grau) e `unknown`, mantém as 12 linhas e os 4 `is_defective`; rodada mais duas vezes sem erro; depois aceita as 4 elétricas só sem grau, recusa `nut` sem grau, `unknown` com grau e `lathe`; o número de `check` não muda e `apply_migrations` de novo não aplica nada. POST de elétrica com grau (4 tipos) e com só `grade_score`/`grade_confidence` → 422, nada gravado; lote com uma elétrica com grau recusado inteiro; batch das 4 idempotente (R-05); filtro do SPC por cada elétrica → 422 sem traceback; resumo e série temporal com elétricas fora do denominador de `defect_rate` (e `unknown_count` sem elas); elétricas dentro de um lote de parafusos não mudam o `n` do SPC, e um lote com 4 parafusos e 6 elétricas fica em `excluded_lots` com `n = 4`; elétrica simulada continua `simulated` (R-06); filtros da listagem por cada elétrica; `/health` com contrato >= 0.6.0.
- **Borda:** cada elétrica sozinha no modelo exige estar em `ungraded_object_types` (ausente ou `[]` → `ModelLoadError`); modelo com os 12 tipos aceita as 4 elétricas (com ou sem `allen_key`) e recusa só 3 delas; listas inválidas (tipo fora do modelo, repetido, caixa, com `screw`/`other`) recusadas, sem eco do valor; decisão da furadeira ignora as probabilidades de grau e o limiar de `unusable`, vai para revisão com margem baixa e vira `unknown` abaixo do limiar; captura de furadeira: `approved = null`, `verdict = "sem grau"`, rótulo `furadeira`, payload válido no outbox (§4); coleta das 4 elétricas em `raw/<tipo>/_/`; coleta com grau (`perfect`, `unusable`, espaço, texto), prefixo `S`/`N`/`O`/`XT`, código com caixa ou espaço ou o rótulo PT-BR → 422 sem gravar; troca de tipo de um `T-` já registrado → 409; página de captura oferece as 4 com os rótulos; cobertura com uma linha por elétrica (sem célula com grau), contando imagens e peças, na ordem do enum, e o console mostrando os rótulos PT-BR; importação: elétrica com grau (`T-` e `XT-`), prefixo `S`/`O`/`XS`, caixa errada → saída 2 sem gravar; o problema de grau é o mesmo do `other` com grau; as 4 importam com `T-` e `XT-` sem grau; `--dry-run` não grava e a reimportação é idempotente.
- **Dashboard:** as 4 elétricas no histórico (`sem grau`, `Defeituosa = Não`) e no `object_type_label`; CSV com `serra` e o grau vazio ou `sem grau`, sem o código; ordem do gráfico com as 4 juntas depois das manuais e cores distintas; barras com zeros para as elétricas sem dados; página de histórico com os tipos novos e a origem simulada visível (R-06); filtro da carta p sem nenhuma elétrica.
- **ML:** `KNOWN_OBJECT_TYPES` com 12 e `TOOL_OBJECT_TYPES` só com as manuais; `tool_grade_coverage` só com as manuais; elétrica editada para `screw` → `item_prefix_mismatch`; externas `XT-` sem grau em `raw/<tipo>/_/`; as linhas das elétricas vêm depois de todas as outras (o dataset sem elas é prefixo exato do manifest); elétrica sem imagens no treino fica fora de `object_types` e de `ungraded_object_types`; `labels.json` da fixture com os 12 tipos e as 4 sem grau.

Verificados à mão (scripts no diretório temporário da sessão, sem arquivo no repositório):

| Caso | Resultado |
|---|---|
| Coleta de `drill` sem o campo `grade` no formulário | 200, gravada em `raw/drill/_/` com grau vazio; mesmo comportamento do `other` sem o campo (coerente com a SPEC-010) |
| Coleta de `drill` com `good` | 422 `grade must be empty for a power tool` |
| Coleta com `notes` em unicode (`ção 🔧`) | 200; texto preservado no manifest |
| `T-999` com `saw` / `T-1000` | 200 / 422 `missing or invalid item_id` |
| `qc_ml`: `drill` com grau `good` / `other` com `good` | os dois dão um único problema `grade_on_other`, com a mensagem citando o tipo |
| `qc_ml`: grau `" "` numa elétrica | `invalid_grade` e `grade_on_other` |
| `qc_ml`: `object_type = "Saw"` | `invalid_object_type` e `item_type_conflict` |
| Gerador com `power_tool_items_per_type=-1`, `external_power_tool_items_per_type=-1` ou `1000` | `ValueError` com mensagem clara (>= 0; teto de 999 peças `T-`) |

## SPEC_ISSUE (se houver)

Nenhum.

## Observações (não bloqueiam)

- **Texto do CA-07:** é o mesmo padrão de texto do CA-11 da SPEC-016 antes da correção do SPEC_ISSUE-T1 (um plano com uma linha válida e uma inválida, "a primeira entra"). Nesta rodada o architect esclareceu a leitura (o plano é validado inteiro; "entra" = passa na validação), e o teste segue essa leitura. Sugestão para o architect, sem urgência: deixar isso escrito no CA-07 (por exemplo, "a primeira linha não tem problema reportado, a segunda é recusada e nada é gravado"), para o texto não depender da nota.
- **Código do problema de grau da elétrica na importação:** `grade_on_other` (decisão 3 da Parte A), o mesmo do `qc_ml` (CA-09). O nome cita `other`, mas a SPEC-036 tem lista fechada de códigos; o teste exploratório confere só que o código é o mesmo do `other` com grau.
- **CA-14** continua manual e pendente para a dupla.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
