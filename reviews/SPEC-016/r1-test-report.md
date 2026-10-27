# SPEC-016 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-016](../../docs/specs/SPEC-016-ferramentas-manuais.md) |
| Rodada | r1 (Parte A do developer e Parte B do ml-engineer, com o adendo "Ajuste depois da reaprovação") |
| Tester | tester |
| Commit testado | `5e5745f` |
| **Veredicto** | **PASS** depois da correção do SPEC_ISSUE-T1 (ver o adendo no fim). Veredicto original desta rodada: **FAIL**: todos os CAs automatizados têm teste e passam, a suíte inteira passa e o ruff está limpo, mas o **CA-11 não pode ser verificado como está escrito** (SPEC_ISSUE-T1, abaixo). O CA-21 é manual e fica pendente para a dupla. |

Os testes foram escritos a partir do texto atual da SPEC (com as correções do architect em `83d64a1`, reaprovadas pelo humano em `be3d2ec`: §4.7, §4.8, CA-22 e CA-23), em caixa-preta, antes da leitura da implementação; a leitura veio depois, só para os exploratórios de borda.

- Datasets todos sintéticos (`make_synthetic_dataset` e imagens desenhadas no teste com Pillow), sempre em diretórios temporários; nada de `ml/data/` nem de `~/partqc-entrada/`; nenhuma imagem real.
- Chaves de dispositivo, tokens de sessão e marcadores gerados em tempo de execução (R-03); nenhum literal com cara de segredo.
- Fronteiras simuladas: só o HTTP do dashboard (`httpx.MockTransport`) e o relógio e o `sleep` do importador (os parâmetros que o `main` dele aceita). Banco real (`partqc_test`) na API, modelo dummy ONNX da SPEC-008 §6 (construído no teste) na borda e a fixture ONNX `tiny_model_tools` no ML, sem torch.
- O split roda pela CLI (`python -m qc_ml.split`, subprocesso); nenhum teste roda o pytest em subprocesso (`docs/architecture.md` §10).
- "Ferramentas acrescentadas" (CA-15, CA-20, CA-23): as versões do split ficam num único diretório; o `split_v1` lê o dataset gerado sem ferramentas e as versões seguintes leem o dataset gerado com os mesmos parâmetros mais as ferramentas. Cada fixture confere antes que todas as linhas (e os bytes das imagens) do dataset sem ferramentas estão no dataset com ferramentas.

## Arquivos e contagem

| Arquivo | Testes | Itens de CA (`test_caNN_*`, com parametrização) | Exploratórios (`test_extra_*`) |
|---|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_016.py` | 86 | 11 | 75 |
| `api/tests/acceptance/test_spec_016.py` | 17 | 7 | 10 |
| `edge/tests/acceptance/test_spec_016.py` | 78 | 18 | 60 |
| `dashboard/tests/acceptance/test_spec_016.py` | 19 | 2 | 17 |
| `ml/tests/acceptance/test_spec_016.py` | 45 | 20 | 25 |
| **Total** | **245** | **58** | **187** |

Um dos 45 do ML (`test_extra_export_with_tools_writes_ungraded_types`) usa `pytest.importorskip("torch")`: é pulado no ambiente do CI e foi executado com o extra `train` (seção "Suíte completa").

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `packages/contracts/tests/acceptance/test_spec_016.py::test_ca01_contracts_version_is_0_4_0`, `::test_ca01_object_type_members_in_order`, `::test_ca01_tool_labels_pt`, `::test_ca01_grade_groups_are_disjoint_and_cover_the_enum`, `::test_ca01_pyproject_and_readme_history` | ✅ |
| CA-02 | `packages/contracts/.../test_spec_016.py::test_ca02_case_a_tool_without_grade_is_accepted`, `::test_ca02_case_b_tool_with_grade_is_accepted`, `::test_ca02_case_c_screw_without_grade_is_rejected`, `::test_ca02_case_d_unknown_with_grade_is_rejected`, `::test_ca02_case_e_tool_with_grade_and_null_score_is_rejected`, `::test_ca02_inspection_read_with_tool_without_grade` | ✅ |
| CA-03 | `api/tests/acceptance/test_spec_016.py::test_ca03_database_accepts_exactly_the_contract_pairs` (48 pares inseridos direto no banco, comparados com o `InspectionCreate` 0.4.0; 41 aceitos, os demais com `23514`), `::test_ca03_hammer_is_refused_with_23514` | ✅ |
| CA-04 | `api/.../test_spec_016.py::test_ca04_post_tool_without_grade_and_read_it_back` (201; listagem `object_type=pliers` com `grade` nulo e `is_defective=false`; `object_type=hammer` → 422) | ✅ |
| CA-05 | `api/.../test_spec_016.py::test_ca05_spc_counts_only_graded_inspections` (`L-01`…`L-03` com `n == 10`, `L-04` fora de `points` e de `excluded_lots`, `p_bar == 0.2`), `::test_ca05_spc_filter_by_ungraded_tool_and_unknown` (`pliers` → 200 e `points == []`; `unknown` → 422), `::test_ca05_openapi_declares_the_spc_object_type_enum` | ✅ |
| CA-06 | `api/.../test_spec_016.py::test_ca06_defect_rate_uses_only_graded_inspections` (`total 18`, `defective 2`, `unknown_count 3`, `defect_rate 0.2`) | ✅ |
| CA-07 | `edge/tests/acceptance/test_spec_016.py::test_ca07_valid_ungraded_lists_load` (ausente, `["pliers"]`), `::test_ca07_invalid_ungraded_lists_are_refused` (`["screw"]`, `["other"]`, `["allen_key"]`, `["pliers","pliers"]`, `"pliers"` → `ModelLoadError`) | ✅ |
| CA-08 | `edge/.../test_spec_016.py::test_ca08_ungraded_tool_has_no_grade_and_no_review`, `::test_ca08_ungraded_tool_with_low_margin_needs_review`, `::test_ca08_graded_tool_follows_the_grade_rule` | ✅ |
| CA-09 | `edge/.../test_spec_016.py::test_ca09_capture_of_ungraded_tool_reaches_the_outbox` (modelo dummy + `SqliteOutbox` real; `approved` nulo, `labels_pt.verdict == "sem grau"`, `labels_pt.grade` nulo; o `payload` do outbox valida como `InspectionCreate` com `pliers` e `grade` nulo) | ✅ |
| CA-10 | `edge/.../test_spec_016.py::test_ca10_tool_is_collected_into_its_grade_directory`, `::test_ca10_invalid_tool_collects_are_422_and_nothing_written` (3 casos: `T-001`+`screw`, `T-002`+`allen_key` sem grau, `S-001`+`pliers`) | ✅ |
| CA-11 | `edge/.../test_spec_016.py::test_ca11_t_and_xt_tool_rows_are_imported` (plano com as duas primeiras linhas: entram no manifest e no `sources.csv`), `::test_ca11_xt_with_screw_is_refused_with_the_prefix_problem` (plano com a terceira linha: saída 2, `plan line 2: item_prefix_mismatch (object_type)`, nada gravado), `::test_ca11_three_line_plan_follows_the_whole_plan_rule_of_spec036` (o plano literal do CA, com as 3 linhas: saída 2, `plan line 4: item_prefix_mismatch (object_type)`, **nada gravado**, nem das duas primeiras) | ⚠️ SPEC_ISSUE-T1: o comportamento do CA escrito ("as duas primeiras linhas entram" no mesmo plano em que a terceira é recusada) contradiz a SPEC-036 §4.2, que a SPEC-016 não muda |
| CA-12 | `dashboard/tests/acceptance/test_spec_016.py::test_ca12_history_rows_type_and_grade_columns`, `::test_ca12_object_type_label_of_each_tool` | ✅ |
| CA-13 | `ml/tests/acceptance/test_spec_016.py::test_ca13_tools_load_with_25_t_items`, `::test_ca13_t_item_edited_to_screw_is_a_prefix_mismatch`, `::test_ca13_tool_row_without_grade_is_missing_grade` | ✅ |
| CA-14 | `ml/.../test_spec_016.py::test_ca14_tool_grade_criterion` (pela CLI `python -m qc_ml.data report`: `pliers` graduado com 60/5 em cada grau, `allen_key` com 59 num grau → sem grau, 30 imagens `XT-` de `flat_screwdriver` → `by_grade` só com zeros, 5 ferramentas × 5 graus) | ✅ |
| CA-15 | `ml/.../test_spec_016.py::test_ca15a_new_tools_need_a_decision`, `::test_ca15b_defer_the_tools`, `::test_ca15c_extend_the_test_with_the_tools`, `::test_ca15d_new_item_of_an_extended_type_is_not_in_test`, `::test_ca15e_too_few_items_to_extend` | ✅ |
| CA-16 | `ml/.../test_spec_016.py::test_ca16_model_labels_with_tools` (com uma imagem de `allen_key` apagada e registrada em `exclusions.csv`), `::test_ca16_model_labels_of_the_mvp`, `::test_ca16_grade_target` | ✅ |
| CA-17 | `ml/.../test_spec_016.py::test_ca17_false_unknown_counts_the_tools` (`type_threshold == 0.55`, o maior `t` da grade com `FU(t) <= 0.05` nas 20 imagens, recalculado no teste com `Fraction`) | ✅ |
| CA-18 | `ml/.../test_spec_016.py::test_ca18_evaluate_with_tools` (`thresholds` e `evaluate` sem torch, com a `tiny_model_tools` e o split estendido do CA-23: chaves da SPEC-012 §4.7 mais `tool_grade_metrics`, `type_confusion` 8×8, `labels.ungraded_object_types == ["allen_key"]`, `tool_grade_metrics` sem `allen_key` e com as 5 chaves em cada ferramenta graduada do modelo), `::test_ca18_fixture_labels_json_has_the_ungraded_types` | ✅ |
| CA-19 | `ml/.../test_spec_016.py::test_ca19_defaults_are_byte_for_byte_the_same` | ✅ |
| CA-20 | `ml/.../test_spec_016.py::test_ca20_no_item_in_two_splits_and_no_xt_in_val_or_test` (split (c) do CA-15 com `external_tool_items_per_type=2`: 10 imagens `XT-`, todas em `train`) | ✅ |
| CA-21 | manual (treino real com fotos das ferramentas, dupla) | ⏳ pendente: depende da coleta (§3.3); não bloqueia o merge (Definição de pronto) |
| CA-22 | `ml/.../test_spec_016.py::test_ca22_review_threshold_counts_screw_nut_and_other` (`type_threshold == 0.85`, `grade_review_threshold == 0.60`, nenhuma nota `review_adjusted`) | ✅ |
| CA-23 | `ml/.../test_spec_016.py::test_ca23_ungraded_tool_is_one_stratum` (3/1/1 peças por ferramenta), `::test_ca23_graded_tool_is_split_by_grade` (3/1/1 em cada um dos 5 graus de cada ferramenta) | ✅ |

## Suíte completa

Ambiente do CI (`uv sync --all-packages --locked`, sem torch), banco `partqc_test` (contêiner `partqc-pg`), nenhuma outra suíte com banco rodando:

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
7293 passed, 75 skipped, 1 warning in 622.54s (0:10:22)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
251 files already formatted
```

Antes dos testes e dos ajustes deste relatório, no mesmo commit: `18 failed, 7031 passed, 74 skipped`. As 18 falhas eram exatamente os aceites antigos listados pelos autores (tabela de ajustes abaixo); os 75 pulados são os de Docker, MQTT, modelo real e torch, como na `main`.

Com o extra `train` (torch 2.14.1), só a parte de ML:

```text
$ uv sync --all-packages --extra train
$ uv run pytest -q ml/tests/acceptance ml/tests/test_tools_torch.py
452 passed, 1 skipped in 231.46s (0:03:51)
```

(inclui os dois testes de fumaça da SPEC-012 que comparam as chaves do `metrics.json` e o `test_extra_export_with_tools_writes_ungraded_types`; o pulado é o de modelo real do `test_spec_012.py`). O ambiente voltou ao estado do CI com `uv sync --all-packages --locked` (`torch` não instalado; `uv.lock` sem mudança).

## Ajustes em testes de aceite de SPECs anteriores (`docs/architecture.md` §10)

Só as asserções afetadas mudaram; nenhum `test_caNN_` foi removido nem renomeado, e a contagem de testes coletados em cada arquivo é a mesma de antes. Cada linha alterada leva um comentário com o requisito da SPEC-016.

| Arquivo | Teste | Antes → depois | Requisito da SPEC-016 | Na §3.1? |
|---|---|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_026.py` | `test_ca01_contracts_version_is_0_3_0` | `__version__ == "0.3.0"` e `version("qc-contracts") == "0.3.0"` → coerência `__version__ == importlib.metadata.version(...)`, formato `\d+\.\d+\.\d+` e piso `(0, 3, 0) <= v < (1, 0, 0)` (o nome do teste fica, porque um `test_caNN_` não se renomeia) | §4.1 (versão 0.4.0) e "Expectativas de versão" | sim |
| `api/tests/acceptance/test_spec_004.py` | `ALLOWED_EXACT` do `test_ca28_version_expectations_migrated` | par `(test_spec_026.py, qc_contracts, "0.3.0")` → `(test_spec_016.py, qc_contracts, "0.4.0")`, com a constante `SPEC016_CONTRACTS`; no mesmo commit que cria o `test_spec_016.py` | §3.1 e "Expectativas de versão" (precedente: SPEC-026) | sim |
| `packages/contracts/tests/acceptance/test_spec_002.py` | `test_ca02_enum_values_grade_order_and_patterns` | `[m.value for m in ObjectType] == ["screw","nut","unknown"]` → `[...][:3] == ["screw","nut","unknown"]` (os membros do MVP continuam os primeiros, na mesma ordem) | §4.1 (as 5 ferramentas entram **depois** dos membros atuais) | não (§10, regra geral) |
| `packages/contracts/tests/acceptance/test_spec_002.py` | `test_ca17_labels_match_enums_and_are_immutable[object_type]` | tabela esperada `{"screw","nut","unknown"}` → a mesma mais os 5 rótulos das ferramentas (`alicate`, `chave inglesa`, `chave Allen`, `chave de fenda`, `chave Phillips`); a checagem 1:1 com o enum e a imutabilidade continuam | §4.1 (`OBJECT_TYPE_LABELS_PT`) | não (§10) |
| `api/tests/acceptance/test_spec_005.py` | `test_ca06_summary_without_filters` | `by_object_type == {"screw":4,"nut":3,"unknown":1}` → `{o.value: 0 for o in ObjectType} \| {"screw":4,"nut":3,"unknown":1}` (toda chave do enum, 0 quando ausente, a regra da SPEC-005 §4) | §4.1 (`ObjectType` 0.4.0) | não (§10) |
| `api/tests/acceptance/test_spec_005.py` | `test_ca08_summary_without_rows` | `len(by_object_type) == 3` → `== 3 + 5` | §4.1 | não (§10) |
| `edge/tests/acceptance/test_spec_008.py` | `test_ca10_invalid_labels[pliers]` | caso `("screw","pliers","other")`, id `pliers` → `("screw","hammer","other")`, id `hammer` (valor ainda fora do contrato) | §3.1 / §4.4 | sim |
| `edge/tests/acceptance/test_spec_010.py` | `test_ca15_compute_coverage_counts_images_and_items` | `len(cells) == 11` → `11 + 25`; conjunto de chaves → o do MVP mais (5 ferramentas × 5 graus); a conferência das metas (120/12 e 150/30) fica restrita às células do MVP (a meta das células de ferramenta não faz parte deste CA) | §4.4 ("a tabela de cobertura do console ganha as linhas das ferramentas, 5 graus cada") | não (§10) |
| `edge/tests/acceptance/test_spec_010.py` | `test_ca15_missing_manifest_is_an_empty_table` | `len(cells) == 11` → `11 + 25` | §4.4 | não (§10) |
| `edge/tests/acceptance/test_spec_010.py` | `test_extra_compute_coverage_ignores_unknown_cells` | linha `T-001`/`pliers` (célula desconhecida antes) → `T-001`/`hammer` (continua desconhecida); `len(cells) == 11` → `11 + 25` | §3.1 / §4.4 | sim (caso `T-001` com `pliers`) |
| `edge/tests/acceptance/test_spec_036.py` | `test_ca04_invalid_plan_is_refused_and_nothing_written[item_tool]` e `[item_external_tool]` | código esperado `tools_not_supported (item_id)` → `item_prefix_mismatch (object_type)` (`T-001`/`XT-0001` com `other`); saída 2 e `DATASET_DIR` intacto continuam | §4.4 (a importação aceita as ferramentas com `T-`/`XT-`) e CA-11 ("o problema de prefixo da SPEC-036") | não (§10) |
| `dashboard/tests/acceptance/test_spec_013.py` | `test_extra_spc_controls_never_offer_all_or_unknown` | opções do filtro `["Todos","parafuso","porca"]` → as mesmas mais os rótulos das 5 ferramentas (continua sem `desconhecido`) | §4.5 (filtro com os membros de `SpcObjectType`) | não (§10) |
| `dashboard/tests/acceptance/test_spec_013.py` | `test_extra_by_object_type_and_series_charts` | barras `{"parafuso","porca","desconhecido"}` → mais as 5 ferramentas | §4.5 (`OBJECT_TYPE_ORDER` e cores com as ferramentas) | não (§10) |
| `ml/tests/acceptance/test_spec_012.py` | `test_ca22_metrics_json_contents` e `test_extra_test_split_without_unusable_reports_null` (pelo ajudante `_check_metrics`) | `set(metrics) == METRIC_KEYS` → `== METRIC_KEYS \| {"tool_grade_metrics"}` | §4.8 (chave de topo nova) | sim |
| `ml/tests/acceptance/test_spec_012.py` (com torch) | `test_extra_smoke_metrics_json_is_complete`, `test_extra_corn_smoke_pipeline_exports_probabilities` | a mesma troca | §4.8 | sim |
| `ml/tests/acceptance/test_spec_035.py` | `test_ca12_metrics_counts_by_origin` | a mesma troca | §4.8 | sim |

Dependências indiretas, sem edição: `packages/preprocess/tests/acceptance/test_spec_023.py::test_ca12_spec002_acceptance_suites_still_pass` e `dashboard/tests/acceptance/test_spec_029.py::test_ca01_spec013_suite_passes_and_hides_key_with_local_secrets` rodam as suítes de aceite da SPEC-002 e da SPEC-013 em subprocesso e voltaram a passar com os ajustes acima.

Itens da §3.1 que não precisaram de ajuste: `ml/tests/acceptance/test_spec_011.py` e os casos de `T-`/`XT-` do `test_spec_035.py` (os testes existentes usam `T-001`/`XT-0001` com `screw`, que continuam recusados com `item_prefix_mismatch`), e `api/tests/acceptance/test_spec_006.py` (não fixa os membros do enum do filtro; o caso `object_type=unknown` → 422 continua valendo). Nenhum ajuste contraria a SPEC-016.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Todos passam (os nomes estão nos arquivos; resumo por área):

**Contrato** (`packages/contracts`, 75): matriz completa 8 tipos × (5 graus + nulo) nos dois schemas (`InspectionCreate` e `InspectionRead`) contra os grupos; ferramenta sem grau com só `grade_score` ou só `grade_confidence` preenchido → recusada; ferramenta com grau e `grade_confidence` nulo → recusada; mensagens da invariante sem valores (lote marcador, tipo e grau não aparecem); grupos são `frozenset` de `ObjectType`, exportados na raiz e em `__all__`; membros novos são `StrEnum` com o valor de código e serializam como texto; `hammer`, `Pliers`, `PLIERS`, `pliers` com espaço no fim, `allen-key`, `other` e vazio não são `ObjectType`; `is_defective` inalterado; ida e volta JSON de ferramentas; campos extras continuam proibidos.

**Banco e API** (10): a migração nova num banco à parte (nome com `test`, apagado no fim): 001+002 aplicadas, 11 linhas do MVP (5 graus × parafuso e porca e um `unknown`) e `pliers` recusado antes; depois da 003, as 11 linhas continuam, `is_defective` igual, o arquivo da 003 roda **mais duas vezes** sem erro, o conjunto completo reaplicado não aplica nada e o número de `check` não muda; `pliers` sem grau e `allen_key` `poor` aceitos (`is_defective` verdadeiro na ferramenta graduada), `screw` sem grau, `unknown` com grau e `hammer` recusados. Resumo com ferramentas (`by_object_type` com as 8 chaves; `by_grade` sem as ferramentas sem grau; uma ferramenta `poor` conta como defeituosa e entra no denominador); resumo só de ferramentas sem grau → `defect_rate` e `mean_grade_score` nulos; série temporal com denominador só das inspeções com grau e balde só de ferramentas sem grau com `defect_rate` nulo; SPC filtrado por uma ferramenta graduada (`p_bar = 5/18`) e, sem filtro, a ferramenta graduada entra na carta junto com os parafusos; os 7 valores do filtro → 200 e `unknown`, `other`, `hammer`, `Pliers`, `pliers` com espaço no fim e vazio → 422 sem stack trace; `POST` de cada ferramenta com e sem grau, lote com as 5 e reenvio idempotente (`duplicate`, R-05); 5 combinações inválidas (inclusive no lote) → 422 e nada gravado; `/health` com `contract_version = 0.4.0`; filtros de listagem por cada ferramenta, por grau e por `defective`.

**Borda** (60): `ungraded_object_types` com cada ferramenta, com as 5 e vazio explícito; `null`, `["nut"]`, `["unknown"]`, `[1]`, lista aninhada, objeto, `["PLIERS"]` e `[""]` → `ModelLoadError`; a mensagem não ecoa o valor (marcador aleatório); inferência pelo `OnnxInferencer` devolve `pliers` sem grau. Decisão: ferramenta sem grau abaixo do `type_threshold` vira `unknown` com revisão; ferramenta sem grau ignora `unusable` e confiança de grau baixa; borda da margem (0,60 exato não revisa, 0,59 revisa); parafuso não muda com uma ferramenta sem grau nos rótulos. Captura de ferramenta graduada (`approved` verdadeiro, rótulos `alicate`/`mediano`/`aprovada`); ferramenta sem grau com margem baixa (`needs_review` no payload); `unknown` continua `desconhecido`. Coleta: cada ferramenta com cada grau no diretório certo; `XT-0001` pela página, `T-` com `other` ou `nut`, `T-01`, `t-001`, `N-`/`O-` com ferramenta, grau ausente ou inválido, `hammer`, `Pliers` e `unknown` → 422 sem gravar; mesma peça `T-` com outro tipo → 409; tabela de cobertura com as 25 células das ferramentas (36 no total), contando 3/3 em `pliers`/`good`; página `/capture` com as 5 opções e os rótulos PT-BR. Importação: `T-` com `screw`, `S-` com ferramenta, `XT-` com `nut`/`other` → `item_prefix_mismatch (object_type)`; ferramenta sem grau → `missing_grade (grade)`; `T-0001`/`XT-001` → `invalid_item_id`; `contributor` com `XT-` e `external` com `T-` → `origin_item_mismatch`; cada ferramenta importada com `T-` e `XT-`; `--dry-run` não grava nada; peça `T-` já registrada com outra ferramenta → `item_type_conflict`.

**Dashboard** (17): `object_type_label` nos 8 tipos; cada ferramenta com e sem grau no histórico (`sem grau` e `bom`); CSV do histórico com ferramenta sem grau (o `unknown` continua com célula vazia, CA-20 da SPEC-013); `OBJECT_TYPE_ORDER` = parafuso, porca, as 5 ferramentas e desconhecido, com cores distintas; gráfico por tipo com as ferramentas e os valores; página "Histórico" com `sem grau`; página da carta p com o filtro `Todos` + `SpcObjectType` em PT-BR; cada rótulo de ferramenta envia o código certo (`object_type=pliers` …) com `source=live`; nenhum código cru na tela.

**ML** (25): constantes do critério e da ordem de tipos; critério com 60 imagens de só 4 peças → sem grau; imagem excluída não conta (59 → sem grau); relatório de dados do MVP com as 5 ferramentas zeradas; `derive_model_labels` com tipos só do `train_rows` e critério do `df` inteiro; caso de contraste do CA-22 (sem as imagens de `other`, a fração é 20% e a nota `review_adjusted` aparece; o valor continua 0,60 pelo desempate da SPEC-012 §4.6); `unusable_threshold` igual com ou sem 10 ferramentas `unusable` mal previstas; limiares com val só de ferramentas (sem erro, valores na grade); decisão vetorizada do `qc_ml` igual à da borda em 400 vetores aleatórios com 8 tipos e `allen_key` sem grau (tipo, grau e `needs_review`); `type_confusion` soma todas as imagens de teste; `tool_grade_metrics` com `n_images_test`/`n_items_test` iguais às contagens do split; aviso `few test items for <tipo>: <n>` exatamente para os tipos com menos de 2 peças no teste; `grade_confusion` só com parafuso e porca (ADR-022, decisão 6); `report changelog` com a linha `- Tipos do modelo: …; sem grau: allen_key.` antes da tabela e a observação sobre a `type_accuracy`; `decision.json` com as 3 chaves; numeração do gerador (`T-001`…`T-100`, `XT-0001`…`XT-0010`, 3 imagens por `T-`, 1 por `XT-`, `XT-` com origem `external` e fonte `synthetic`, `T-` sem linha no `sources.csv`, 2 `XT-` por ferramenta); valor desconhecido, `unknown`, tipo listado que não é novo, tipo nas duas listas e decisão parcial → saída 2 sem gravar (a parcial com `new object type without decision: allen_key`); `split_v1` ignora as listas (JSON com listas vazias); `rows_for` ignora o tipo adiado com o aviso `deferred type images: pliers: <n>`; uma peça nunca em dois splits depois da extensão; export pelo script da fixture (`--with-tools`, com torch) grava `ungraded_object_types`.

## SPEC_ISSUE

- **SPEC_ISSUE-T1 (CA-11 impossível de verificar como está escrito; baixa).** O CA-11 diz: "*Dado* um plano com, em linhas separadas, `T-501` …, `XT-0001` … e `XT-0002` `screw` `good` `external`, *quando* `python -m qc_edge.importer … --privacy-checked` roda, *então* as duas primeiras linhas entram no manifest e no `sources.csv`, e a terceira é recusada com o problema de prefixo da SPEC-036, sem gravar nada dela". A SPEC-036 §4.2 (que a SPEC-016 §4.4 só estende, "com as mesmas regras") manda a fase 1 validar o plano **inteiro** antes de gravar: "Qualquer problema → código 2, nada gravado". Com as três linhas no mesmo plano, nada entra (comportamento observado e correto pela SPEC-036, `test_ca11_three_line_plan_follows_the_whole_plan_rule_of_spec036`). O resultado esperado pelo CA só acontece em execuções separadas, que é o que os outros dois testes do CA-11 verificam (e o que o teste do autor faz). **Evidência:** `docs/specs/SPEC-036-importacao-de-fotos.md` linha 72 e CA-04 dela; `edge/tests/acceptance/test_spec_016.py::test_ca11_*`. **Correção sugerida (architect):** reescrever o CA-11 como "em casos separados" (plano só com as duas primeiras linhas: entram; plano só com a terceira: saída 2, `plan line 2: item_prefix_mismatch (object_type)`, nada gravado) ou acrescentar que o plano com as três linhas sai com 2 sem gravar nada. Nenhuma mudança de código; os três testes atuais já cobrem as duas leituras.

## Observações (não bloqueiam)

- **`docs/architecture.md` §10, "Arquivos vigentes":** a linha ainda cita `packages/contracts/tests/acceptance/test_spec_026.py` (`qc-contracts` 0.3.0). Com o `ALLOWED_EXACT` atualizado neste commit, o arquivo vigente do `qc-contracts` passa a ser `test_spec_016.py` (0.4.0); a regra diz que "quando ele muda, esta linha muda junto". É texto do architect (está na Definição de pronto da SPEC). O mesmo vale para o §3 ("Contrato v0 (`qc-contracts` 0.3.0)") e a tabela de enums do §3.1.
- **Nota da rodada no §6 da SPEC:** o texto diz "Rodada r2 (correção dos SPEC_ISSUE-1 e 2 da r1)", mas o loop registrou o ajuste dentro da r1 (adendo do dev report, cabeçalho "Rodada atual r1"). Este relatório segue a r1, como pedido pelo orquestrador.
- **Limiar de revisão sem imagens de parafuso, porca nem `other` na validação:** com só ferramentas na val, o `grade_review_threshold` fica 0,60 sem a nota `review_adjusted` (fração indefinida, `n_images = 0` no relatório). A SPEC não trata esse caso; não é bug, mas a dupla pode querer um aviso (não acontece com dados reais, porque o `split_v1` sempre tem parafuso e porca).
- **Metas das células de ferramenta na cobertura do console** (decisão 2 do developer: 60 imagens e 5 peças por grau): a SPEC não define a meta por célula; os testes não fixam esse valor.

## Conferência depois da correção do SPEC_ISSUE-T1

| Campo | Valor |
|---|---|
| Correção | `6d25aaf` (architect: CA-11 em casos separados (a), (b) e (c), na regra da SPEC-036 §4.2), reaprovada pelo orquestrador sob o ADR-019; `c2c337a` (architect: `docs/architecture.md` §3, §3.1 e §10 com o `qc-contracts` 0.4.0) |
| Commit conferido | `f564584` |
| **Veredicto final** | **PASS** |

Desde o commit `d7d1810` deste relatório, só mudaram `docs/architecture.md`, `docs/plan.md` e a SPEC (`git diff --stat d7d1810 f564584`); nenhum código de produção nem teste do autor mudou. Por isso a suíte completa registrada acima (`7293 passed, 75 skipped`) continua valendo.

O texto novo do CA-11 corresponde aos três testes que já existiam. Nenhuma asserção mudou: só as docstrings, para citar o caso de cada um.

| Caso do CA-11 (texto novo) | Teste | O que verifica | Resultado |
|---|---|---|---|
| (a) plano só com as duas primeiras linhas | `edge/tests/acceptance/test_spec_016.py::test_ca11_t_and_xt_tool_rows_are_imported` | saída 0; `T-501` (`flat_screwdriver`/`good`) e `XT-0001` (`pliers`/`fair`) no manifest, com as imagens em `raw/<tipo>/<grau>/`; as duas linhas no `sources.csv` (`contributor` `c01` e `external` com a fonte registrada) | ✅ |
| (b) plano só com a terceira | `::test_ca11_xt_with_screw_is_refused_with_the_prefix_problem` | saída 2; a linha `plan line 2: item_prefix_mismatch (object_type)` na saída de erro; `DATASET_DIR` igual (nomes e bytes) | ✅ |
| (c) plano com as três | `::test_ca11_three_line_plan_follows_the_whole_plan_rule_of_spec036` | saída 2; a linha `plan line 4: item_prefix_mismatch (object_type)`; `DATASET_DIR` igual, sem nada das duas primeiras linhas | ✅ |

```text
$ uv run pytest -q edge/tests/acceptance/test_spec_016.py
78 passed, 1 warning
$ uv run pytest -q api/tests/acceptance/test_spec_004.py -k ca28
1 passed
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
251 files already formatted
```

- **SPEC_ISSUE-T1:** resolvido. Não há outro SPEC_ISSUE aberto.
- **Bugs:** nenhum.
- **Observações:** a primeira observação acima (`docs/architecture.md` §3, §3.1 e §10) foi atendida pelo `c2c337a`. A nota de rodada do §6 também foi corrigida, no `6d25aaf`.
- **CA-21:** continua manual e pendente para a dupla; não bloqueia o merge.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
