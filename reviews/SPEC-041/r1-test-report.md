# SPEC-041 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-041](../../docs/specs/SPEC-041-modelo-provisorio-e-piso-do-split.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `fab83c0` |
| **Veredicto** | **PASS** (CA-22 manual pendente, como a SPEC §9, resposta 3, permite) |

Testes escritos a partir da SPEC, antes de ler a implementação. Li o código de produção só depois, para procurar casos de borda.

## Cobertura dos critérios de aceite

`ML` = `ml/tests/acceptance/test_spec_041.py`. `Borda` = `edge/tests/acceptance/test_spec_041.py`. O resultado vale para o ambiente com o extra `train`. Sem torch, os CAs slow ficam `skipped`, e os demais passam.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `ML::test_ca01_dataset_at_the_floor_gives_11_items_33_images_per_split` | ✅ |
| CA-02 | `ML::test_ca02_missing_stratum_is_refused_and_nothing_is_written` | ✅ |
| CA-03 | `ML::test_ca03_allow_below_floor_records_the_warning`, `ML::test_ca03_existing_split_v1_ignores_the_floor` | ✅ |
| CA-04 | `ML::test_ca04_external_fraction_at_the_floor`, `ML::test_ca04_external_fraction_above_the_ceiling_is_refused` | ✅ |
| CA-05 | `ML::test_ca05_metrics_at_the_floor_are_defined`, `ML::test_ca05_ten_other_objects_have_no_warning` | ✅ |
| CA-06 (slow) | `ML::test_ca06_pipeline_at_the_floor_with_a_one_image_batch` | ✅ |
| CA-07 (slow) | `ML::test_ca07_smoke_writes_exactly_the_seven_files` | ✅ |
| CA-08 (slow, R-11) | `ML::test_ca08_no_split_function_is_called_and_no_split_is_created` | ✅ |
| CA-09 (slow) | `ML::test_ca09_report_has_exactly_the_keys_and_no_quality_metric` | ✅ |
| CA-10 | `ML::test_ca10_own_item_is_refused` | ✅ |
| CA-11 | `ML::test_ca11_paths_inside_a_git_repository_are_refused` (4 casos) | ✅ |
| CA-12 | `ML::test_ca12_official_version_name_is_refused`, `ML::test_ca12_non_empty_model_directory_is_refused_untouched` | ✅ |
| CA-13 | `ML::test_ca13_type_missing_is_refused`, `ML::test_ca13_grade_missing_is_refused`, `ML::test_ca13_tool_is_refused`, `ML::test_ca13_epochs_out_of_range_is_refused` | ✅ |
| CA-14 | `ML::test_ca14_without_torch_the_error_is_the_extra`, `ML::test_ca14_module_can_be_imported_without_torch` | ✅ |
| CA-15 | `ML::test_ca15_load_config_refuses_a_provisional_version`, `ML::test_ca15_official_steps_exit_2` (`pipeline`, `thresholds`, `evaluate` e, além do CA, `train`) | ✅ |
| CA-16 | `ML::test_ca16_changelog_refuses_and_writes_nothing`, `ML::test_ca16_release_notes_refuses_and_writes_nothing` (o mesmo `metrics.json` real é aceito com o nome oficial, como controle) | ✅ |
| CA-17 | `Borda::test_ca17_provisional_model_publishes_as_simulated` | ✅ |
| CA-18 | `Borda::test_ca18_official_model_stays_live_without_the_suffix` | ✅ |
| CA-19 | `Borda::test_ca19_console_and_log_say_the_model_is_provisional`, `Borda::test_ca19_official_model_has_neither` | ✅ |
| CA-20 | `ML::test_ca20_same_rule_in_both_packages`, `Borda::test_ca20_same_rule_in_both_packages` | ✅ |
| CA-21 | `Borda::test_ca21_published_payload_is_only_the_contract` | ✅ |
| CA-22 (manual) | Não executado. Depende da operação do §4.8, depois do merge | ⏳ pendente |
| CA-23 | `ML::test_ca23_manifest_line_is_refused_everywhere`, `ML::test_ca23_override_line_is_refused`, `ML::test_ca23_excluded_override_validates` | ✅ |
| CA-24 | `ML::test_ca24_official_steps_refuse_a_suggested_label`, `ML::test_ca24_pipeline_refuses_a_suggested_label` (slow) | ✅ |
| CA-25 | `ML::test_ca25_one_manifest_line_of_another_labeler`, `ML::test_ca25_one_override_line_of_another_labeler`, `ML::test_ca25_excluded_override_is_not_counted`, `ML::test_ca25_without_torch_the_error_is_not_about_the_labeler` | ✅ |
| CA-26 | `ML::test_ca26_constants_are_the_same_and_outside_the_collect_mode`, `Borda::test_ca26_constants_are_the_same_and_outside_the_collect_mode`, `Borda::test_ca26_collect_mode_refuses_the_suggestion` | ✅ |
| CA-27 | `Borda::test_ca27_without_the_option_the_labeler_is_invalid` | ✅ |
| CA-28 | `Borda::test_ca28_dataset_inside_a_repository_is_the_first_refusal` (6 casos: `ml/data` inexistente, a raiz e uma pasta existente, cada um com a entrada e o plano fora e dentro do repositório) | ✅ |
| CA-29 | `Borda::test_ca29_valid_plan_is_imported_and_a_second_run_adds_to_it` | ✅ |
| CA-30 | `Borda::test_ca30_another_labeler_in_the_plan`, `Borda::test_ca30_another_origin_in_the_plan`, `Borda::test_ca30_manifest_of_another_labeler` | ✅ |

Contagem dos arquivos novos: 193 testes (134 em `ml/`, 59 em `edge/`), dos quais 12 são `slow`.

## Suíte completa

Banco: `CI=true` e `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`, sem outra suíte com banco ao mesmo tempo (conferido com `pgrep` antes de cada execução).

| Ambiente | Preparação | Comando | Resultado |
|---|---|---|---|
| Como o CI, sem torch | `uv sync --all-packages --locked` (`torch` e `timm` ausentes, conferido) | `uv run --no-sync pytest -q` | `9818 passed, 166 skipped, 1 warning in 985.87s` |
| Com o extra `train` (torch 2.14.1, CPU), incluindo os *slow* | `uv sync --all-packages --locked --extra train` | `uv run --no-sync pytest -q` | `9889 passed, 117 skipped in 1191.79s` (ver a nota) |
| Arquivos desta SPEC, com o extra `train`, na versão final | a mesma | `uv run --no-sync pytest -q ml/tests/acceptance/test_spec_041.py edge/tests/acceptance/test_spec_041.py` | `193 passed in 164.82s` |

```text
ruff check .           All checks passed!
ruff format --check .  306 files already formatted
```

- **Nota sobre a suíte com torch:** ela rodou antes do ajuste de `test_ca15_official_steps_exit_2` descrito na O-01. Depois do ajuste, repeti só os dois arquivos desta SPEC nesse ambiente (terceira linha da tabela). A suíte sem torch rodou inteira na versão final.
- **O que é pulado:** em ambos os ambientes, os testes `docker` (sem `PARTQC_DOCKER_TESTS=1`). Sem torch, também os que pedem torch, inclusive os 12 *slow* e `test_extra_export_with_the_train_extra_exits_2`, desta SPEC. O aviso é o da importação em `fastapi/testclient.py`, que não vem desta SPEC e também aparece no dev-report.
- **Não rodei** o portão de cobertura de `qc_api.services` do CI (`pytest api/tests -m "not db" --cov...`): a branch não toca em `api/`.
- **`uv.lock`:** sem alteração. O `git status` só lista os dois arquivos novos, e a worktree terminou com o extra `train` instalado de novo.

### Ajustes em testes de aceite de SPECs anteriores

Nenhum. Nenhum teste anterior precisou de `--allow-below-floor` (SPEC §7).

## Bugs encontrados

Nenhum.

## Observações (não são bugs)

| ID | Observação | Por que não é bug | Para quem |
|---|---|---|---|
| O-01 | Sem torch, `python -m qc_ml.export --config <provisória>` sai com **1** e um traceback de `ModuleNotFoundError`, e não com 2. O §4.5 diz que `train`, `export`, `thresholds`, `evaluate` e `pipeline` "saem com 2, sem mudança neles". | `export.py` importa torch no topo desde a SPEC-012 e não mudou nesta branch (`git diff main` vazio). A falha é a mesma com qualquer versão, e nada é exportado. O CA-15 não cita o `export`. Com o extra `train`, ele sai com 2 e a mensagem certa (`test_extra_export_with_the_train_extra_exits_2`). Li o §4.5 como válido onde o módulo pode rodar. | Orquestrador: se preferir ler o §4.5 ao pé da letra, a frase precisa de uma correção de SPEC, como no SPEC_ISSUE-05. Na minha primeira versão, o teste do CA-15 incluía o `export` sem torch e falhou; restringi o parâmetro aos passos que o CA cita, mais o `train`, e movi o `export` para esse teste com torch. |
| O-02 | `labeler` quase igual (`Agent-Suggestion`, ` agent-suggestion`, `agent_suggestion`) passa pelo `load_manifest` padrão, porque o `labeler` do manifest é texto livre e a comparação é exata. | O §4.9 fixa a comparação exata. Só uma edição à mão produz esse valor, porque o importador e o modo coleta recusam, e é da mesma classe do limite conhecido do §4.9 (`a`/`b` à mão). O `qc_ml.provisional` conta esses valores como `other labelers`, e o importador como `invalid_labeler`, ambos com teste. | security-devops |
| O-03 | `--seed -1` e `--seed 99999999999` saem com 2 e sem diretório, mas com traceback na stderr, vindo do `report_step_error`, depois do texto do erro. | O §4.2 pede saída 2 e mensagem na stderr, e isso é cumprido. | Só registro |
| O-04 | `--models-root` apontando para um arquivo só falha depois do treino: sai com 2, com `provisional failed: [Errno 20] Not a directory`, e o arquivo fica intacto. | Nenhuma recusa do §4.3 trata esse caso, e nada é gravado. O custo é só o treino perdido. | Só registro |

**O que não foi testado:**

- **Treino real, sem `--smoke`:** os pesos pré-treinados não estão em cache, e os testes não usam internet. Com `HF_HUB_OFFLINE=1`, o comando sai com 2 e não grava nada. Por isso, o gap da paridade com o MobileNetV3-Large continua sem medição, como o dev-report já avisa. O primeiro teste real é o passo 6 do §4.8, antes do CA-22.
- **Seed padrão nos CAs:** o CA-07 fixa `--seed 0` (SPEC_ISSUE-06). O `test_extra_default_seed_either_works_or_leaves_no_directory` aceita 0 ou 2 com a seed 42, e, se sair 2, exige que o diretório não exista (§4.3).

## Testes exploratórios (além dos critérios)

**Automatizados (`test_extra_*`), todos passando:**

| Tema | Casos |
|---|---|
| Ordem do §4.3 | 10 pares de recusas consecutivas, em que a primeira sempre vence |
| `--epochs` | 0, -1, 4 e 11 recusados; 5 e 10 aceitos; `--smoke` não sofre o limite |
| `--model-version` inválido | sem `-v<N>`, só `-provisional-`, maiúsculas, `../`, `/`, `\n`, espaço, não ASCII, longo demais, vazio |
| Linha de comando | texto em `--epochs` e `--seed`, opção desconhecida, valor faltando, sem argumentos: saída 2, sem gravar |
| Entradas quebradas | dataset ausente, imagem corrompida, manifest corrompido, registro ausente, `--models-root` como arquivo: saída 2 |
| Caminhos | link simbólico para dentro de repositório (ML e borda), `.git` como arquivo (worktree), caminhos com acento e espaço |
| Diretório do modelo | vazio é aceito; a execução não grava mais nada e não altera o dataset; os valores do relatório conferem (hashes, contagens, `created_at` em UTC) |
| Piso | vários estratos em ordem lexicográfica; só externas lista os 11 estratos; externas não contam; colaboradores contam; peça excluída conta como ausente; grau dominante decide (§7); 1 foto por peça não é conferida; flag sem efeito acima do piso e a partir do `split_v2`, com aviso no log; repetir com os mesmos dados não cria versão |
| `labeler` | `other labelers` soma os dois arquivos; linha excluída não conta; override de `agent-suggestion` aceito no conjunto provisório; `data report` e `train` também recusam; mensagem fixa do §4.9 |
| Relatórios | `qc_ml.report` recusa com `metrics.json` ausente ou corrompido (antes de ler) |
| Borda | sufixo em todos os vereditos, inclusive `sem grau`, sem mudar `approved`, tipo, grau nem confianças; nome oficial em link para diretório provisório e `MODEL_DIR` relativo saem `simulated`; `/api/status` sem campo novo; `--stub-model` sem mudança; console sem modelo sem aviso; a nuvem falsa recebe `simulated` e nenhuma imagem; modelo real do `qc_ml.provisional` carregado na borda sai `simulated` |
| Importador | `--dry-run` não grava; manifest só com cabeçalho é aceito; repetir o plano não muda nada; `labeler` quase igual é recusado; `--privacy-checked` continua obrigatório; sem a opção, dataset em repositório continua aceito; item próprio com origem externa é recusado; o conjunto importado passa no `qc_edge.privacy` e só é aceito com `allow_agent_suggestion=True` |

**Manuais, uma vez, com scripts fora do repositório e imagens sintéticas:**

| Verificação | Resultado |
|---|---|
| §4.8, passos 4 a 7, com o registro real e 44 imagens sintéticas | `--dry-run`: `would import 44, skipped 0, failed 0`, sem gravar. Importação: `imported 44`. Privacidade: `checked 44 images, 0 with private data`. `qc_ml.data validate` e `qc_ml.split` recusam com `agent_suggestion_label` e saída 2. `--smoke` com a seed padrão e com a seed 0 gerou o modelo nesse conjunto. `qc_ml.report changelog`: `provisional model: no official report`, saída 2 |
| `qc-edge` real, na porta local, com esse modelo | Log com `WARNING … provisional model loaded…`; captura com `simulated` e `desconhecido (modelo provisório)`; console com `PROVISÓRIO` |
| `make_synthetic_dataset`, `main` contra esta branch, 4 combinações de argumentos | Arquivos idênticos byte a byte (§3.1) |
| Escopo no diff contra a `main` | Sem mudança em `uv.lock`, nos `pyproject.toml`, em `packages/`, `api/`, `dashboard/` nem em `edge/src/qc_edge/static/` (`capture.js` continua com 200 linhas) |
| `ml/README.md` | Tem o procedimento do §4.8 |

## SPEC_ISSUE

Nenhum. A O-01 é a única frase da SPEC que não vale em todos os ambientes. Não a registrei como `SPEC_ISSUE` porque nenhum CA depende dela e porque o módulo declara o extra `train` como requisito desde a SPEC-012.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
