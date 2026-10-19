# SPEC-012 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-012](../../docs/specs/SPEC-012-ml-treino-export.md) |
| Rodada | r1 |
| Autor | ml-engineer |
| Branch | `spec/SPEC-012-ml-treino-export` |
| Commits | `2957070` (código, testes e fixture), `35d14aa` (config, notebook, CHANGELOG, README), mais o commit deste relatório |

## Resumo

- **Modelo e treino (torch):** `qc_ml.model` (backbone timm + cabeças `type`/`grade`, CORN, `ProbabilityWrapper`) e `qc_ml.train` (2 fases, loss mascarada, pesos de classe, early stopping pelo QWK de validação, seeds, `last.pt`/`best.pt`, `--resume`, `training_config.json`).
- **Export (torch):** `qc_ml.export` (ONNX opset 17 com batch dinâmico, `onnx.checker`, `model.sha256`, `labels.json`, `preprocessing.json` e `parity_fixture.npz` com 8 entradas sintéticas). Se a paridade falha, o `model.onnx` é apagado.
- **Sem torch:** `predict`, `decision`, `thresholds` (só validação), `evaluate` (único consumidor do teste), `parity`, `report` (entrada do CHANGELOG) e `pipeline`, mais 4 módulos internos de apoio (`config`, `artifacts`, `plots`, `steps`).
- **Fixture do CI:** `ml/tests/fixtures/tiny_model/`, com 852.546 bytes, gerada por `ml/scripts/make_tiny_fixture.py`.
- **Distribuição:** `ml/configs/partqc-mnv3-v1.json`, `ml/models/CHANGELOG.md` (só o cabeçalho), `ml/notebooks/train_colab.ipynb` (sem saídas e sem token) e o fluxo Colab → artefatos → Release no `ml/README.md`.
- **Treino real:** não houve. Não há fotos reais, e o CA-28 é manual e fica com a dupla. **Nenhuma métrica de modelo é reportada aqui.** As execuções de treino foram só de *smoke*, com o dataset sintético em `tmp_path`.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `ml/src/qc_ml/model.py` (`build_model`, `PartQCNet`, `ProbabilityWrapper`) | `ml/tests/test_model.py::test_ca01_shapes_and_probabilities`, `::test_ca01_corn_head` |
| CA-02 | `model.py::corn_probabilities` | `test_model.py::test_ca02_corn_probabilities_of_zero_logits`, `::test_corn_probabilities_never_negative` |
| CA-03 | `ml/src/qc_ml/train.py::compute_loss` | `test_model.py::test_ca03_loss_without_any_grade_is_the_type_ce`, `::test_ca03_mixed_batch_masks_the_grade_term`, `::test_corn_loss_uses_only_graded_rows` |
| CA-04 | `train.py::grade_class_weights` | `ml/tests/test_train_helpers.py::test_ca04_weights_when_a_grade_is_below_60_percent_of_the_mean` |
| CA-05 | `train.py::EarlyStopper` | `test_train_helpers.py::test_ca05_early_stopper` |
| CA-06 | `ml/src/qc_ml/config.py::TrainConfig` (reexportado por `qc_ml.train`) | `ml/tests/test_config.py::test_ca06_epochs_a_out_of_range_needs_smoke`, `::test_ca06_invalid_model_version` |
| CA-07 (slow) | `pipeline.py`, `train.py`, `export.py`, `thresholds.py`, `evaluate.py` | `ml/tests/test_pipeline_slow.py::test_ca07_every_artifact_exists` |
| CA-08 (slow) | `train.py::train` (registro `training_config.json`) | `test_pipeline_slow.py::test_ca08_training_config` |
| CA-09 (slow) | `train.py::set_seeds`, `epoch_generator`, `seed_worker` | `test_pipeline_slow.py::test_ca09_same_seed_same_history` (2ª execução por `python -m qc_ml.pipeline`) |
| CA-10 (slow) | `export.py::export_onnx` | `test_pipeline_slow.py::test_ca10_onnx_model` |
| CA-11 | `artifacts.py::write_model_sha256`/`read_model_sha256` | `ml/tests/test_parity.py::test_ca11_fixture_sha256`, `::test_ca12_local_models_parity`, `ml/tests/test_predict.py::test_sha256_file_format` |
| CA-12 | `ml/src/qc_ml/parity.py::check_parity`, fixture `tiny_model` | `test_parity.py::test_ca12_tiny_fixture_parity`, `::test_ca12_local_models_parity` (skip sem `model.onnx` local) |
| CA-13 | `parity.py::check_parity` | `test_parity.py::test_ca13_perturbed_fixture_fails` |
| CA-14 | `ml/scripts/make_tiny_fixture.py`, `ml/tests/fixtures/tiny_model/` | `test_parity.py::test_ca14_fixture_files_size_and_git` |
| CA-15 | `thresholds.py::choose_thresholds` | `ml/tests/test_thresholds.py::test_ca15_refuses_any_split_but_val` |
| CA-16 | `thresholds.py::_choose_type` | `test_thresholds.py::test_ca16_type_threshold` |
| CA-17 | `thresholds.py::_choose_unusable` | `test_thresholds.py::test_ca17_unusable_threshold`, `::test_unusable_best_recall_when_target_unreachable` |
| CA-18 | `thresholds.py::_choose_review` | `test_thresholds.py::test_ca18_review_threshold` |
| CA-19 | `thresholds.py::run`/`main` | `test_thresholds.py::test_ca19_cli_with_the_tiny_model` |
| CA-20 | `evaluate.py::run` (único `rows_for(..., "test")`), `thresholds.py::run`, `train.py::train` | `ml/tests/test_evaluate.py::test_ca20_test_split_requested_once_after_decision` (CI); `test_pipeline_slow.py::test_ca20_pipeline_requests_test_once` (slow) |
| CA-21 | `evaluate.py::_check_model_dir` | `test_evaluate.py::test_ca21_without_decision_json`, `::test_evaluate_refuses_a_model_that_differs_from_its_sha` |
| CA-22 | `evaluate.py::run`, `compute_metrics`, `split_counts`, `bootstrap_ci`; `plots.py::confusion_png` | `test_evaluate.py::test_ca22_metrics_file` |
| CA-23 | `evaluate.py::grade_metrics`, `quadratic_weighted_kappa` | `test_evaluate.py::test_ca23_grade_metrics`, `::test_qwk_matches_sklearn` |
| CA-24 | `evaluate.py::_rewrite_latency`, `measure_latency` | `test_evaluate.py::test_ca24_latency_only` |
| CA-25 | `report.py::format_metric`, `changelog_entry` | `ml/tests/test_report.py::test_ca25_display_rule_and_status` |
| CA-26 | `ml/notebooks/train_colab.ipynb` | `ml/tests/test_notebook.py::test_notebook_is_clean` |
| CA-27 | `predict`, `decision`, `thresholds`, `evaluate`, `parity`, `report` (nenhum importa torch, sklearn nem scipy) | `ml/tests/test_no_torch.py::test_modules_import_without_torch[spec012]` |
| CA-28 (manual) | `ml/notebooks/train_colab.ipynb`, `ml/README.md` ("Do Colab ao Release") | — (tarefa da dupla) |
| §6, teste cruzado da decisão | `decision.py::apply_decision` × `qc_edge.decision.decide` | `ml/tests/test_decision.py::test_same_result_as_the_edge_decision` (1.000 vetores) |

## Como rodar e verificar

```bash
# CI (sem torch)
uv sync --all-packages --locked
uv run pytest -q ml/tests

# Testes com torch (slow), localmente
uv sync --all-packages --extra train
uv run pytest -q ml/tests
uv sync --all-packages --locked        # volta ao ambiente do CI

# Recriar a fixture mínima (com o extra train)
uv run --package qc-ml python ml/scripts/make_tiny_fixture.py
```

### Resultados

- **Com torch** (`uv sync --all-packages --extra train`; torch 2.14.1, torchvision 0.29.1, timm 1.0.30, onnx 1.23.2, onnxruntime 1.31.0, coral-pytorch 1.4.0, CPU):
  - `uv run pytest -q ml/tests`: **318 passed, 1 skipped**, em 69,78 s. Inclui todos os *slow*: `test_pipeline_slow.py` (7 testes: CA-07, CA-08, CA-09, CA-10, CA-20, `--resume` e falha de paridade) e `test_model.py` (9 testes), além do aceite da SPEC-011. O único skip é o CA-12 para `ml/models/*/` sem `model.onnx` local.
  - Rodando só `test_pipeline_slow.py`: 7 passed em 21,42 s.
- **Sem torch** (`uv sync --all-packages --locked`):
  - `uv run ruff check .`: limpo.
  - `uv run ruff format --check .`: 209 arquivos formatados.
  - `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q`: **4723 passed, 7 skipped**, em 301,59 s. Os skips são os testes que exigem torch, o CA-16 manual da SPEC-008 e o CA-12 sem modelo local.
- O `.venv` ficou **sem** o extra, no estado do CI.

## Decisões tomadas dentro do escopo da SPEC

1. **Módulos internos além da lista do §3.1**, todos sem torch:
   - `config.py`: `TrainConfig`, `load_config`. Fica fora de `train.py` porque `thresholds`, `evaluate` e `pipeline` leem o mesmo JSON no CI;
   - `artifacts.py`: nomes de arquivo, formato do `model.sha256` e `labels.json`;
   - `plots.py`: PNGs com Pillow;
   - `steps.py`: códigos de saída e relato de erros das CLIs.

   `qc_ml.train` reexporta `TrainConfig`, `ConfigError` e `load_config`. Os erros novos (`ConfigError`, `TrainError`, `ModelArtifactError`, `ExportError`, `EvaluationError`) ficam em `qc_ml.errors`.
2. **`qc_ml.train` importa sem torch.** O `import torch` está num `try`, e as funções que precisam dele levantam `TrainError` com a dica do extra. Assim, `grade_class_weights`, `EarlyStopper` e `TrainConfig` (CA-04 a CA-06) rodam no CI importados de `qc_ml.train`. `model.py` e `export.py` importam torch no topo, porque são módulos só de treino.
3. **Nomes não fixados pela SPEC:**
   - `compute_loss(type_logits, grade_logits, type_idx, grade_idx, *, grade_head, label_smoothing, lambda_grade, grade_weights) -> LossParts(total, type_loss, grade_loss)`;
   - `EarlyStopper.step(value) -> bool` (`True` = parar), com `__call__` como sinônimo e os atributos `best_epoch` e `best_value`. As épocas contam a partir de 1;
   - `apply_decision` é vetorizada e devolve `Decisions` (arrays, mais `record(i)` com `None` nos campos de grau);
   - `ParityResult` tem, além de `ok`, `max_abs_diff` e `argmax_equal`, os campos `sha256_match` e `message`, com valores padrão.
4. **`ThresholdResult.decision` é um `Thresholds`:** dataclass imutável que também é um `Mapping` com exatamente as 3 chaves. `result.decision["type_threshold"]` e `result.decision.type_threshold` dão o mesmo valor, e `dict(result.decision)` é o conteúdo do `decision.json`. As notas ficam em `result.report["notes"]` (lista de códigos: `type_target_not_met`, `unusable_target_not_met`, `no_unusable_in_val`, `review_adjusted`).
5. **Limiares, casos que a SPEC não detalha:**
   - as comparações de taxa usam aritmética inteira (`20·count ≤ n` etc.), para não depender de arredondamento de float;
   - val sem nenhum `screw`/`nut`: `type_threshold = 0,50` com a nota `no_screw_nut_in_val`;
   - val vazia: `EvaluationError`;
   - no `grade_review_threshold`, se ainda houver empate depois de "mais próximo de 0,60" (dois `r` à mesma distância), fica o `r` **maior**, que gera mais revisão e por isso é o lado seguro.
6. **QWK e métricas com numpy, sem sklearn nem scipy.** `quadratic_weighted_kappa` usa inteiros até a divisão final. O teste `test_qwk_matches_sklearn` compara com o `cohen_kappa_score` (importado dentro do teste) em 50 casos aleatórios. A nota do §7 sobre o import adiado não chega a se aplicar: nenhum módulo do CA-27 importa sklearn ou scipy.
7. **F1 por grau:** `2·tp / (support + previstos)`, igual a 2PR/(P+R). `recall = null` quando `support = 0`, `precision = null` quando não há previsão daquele grau, e `f1 = null` quando um dos dois é `null`.
8. **Bootstrap (§4.7):**
   - IC por percentis 2,5/97,5, com seed fixa `BOOTSTRAP_SEED = 20261012`;
   - cada reamostragem sorteia peças com reposição e leva todas as imagens de cada peça;
   - as reamostragens em que a métrica fica indefinida (ex.: nenhuma peça `unusable` sorteada) ficam fora do intervalo, e a quantidade vai para `warnings`;
   - métrica indefinida no teste: IC `null` e aviso.
9. **`warnings` do `metrics.json`:**
   - grau com menos de 2 peças no teste;
   - reamostragens indefinidas;
   - métricas indefinidas;
   - o aviso `excluded_previous_image` do `split_v<N>.json`, porque o `docs/dataset-protocol.md` §7 diz que "o relatório de métricas cita o aviso".
10. **`counts`:** `por split → {n_images, n_items, by_class: {tipo → {n_images, n_items, by_grade: {grau → {n_images, n_items}}}}}`. Para `other`, `by_grade = {}`. Para montar `counts.train` e `counts.val`, o `evaluate` também pede `rows_for(..., "train")` e `(..., "val")`, sempre antes do único pedido de `"test"`. O CA-20 permite isso: só exige que `"test"` seja pedido uma vez, pelo `evaluate`.
11. **Latência:** usa as imagens do teste, em ciclo (só para cronometrar, nada é escolhido com elas), nas duas formas de execução. Outros detalhes:
    - o `--latency-only` recusa um `metrics.json` de outro modelo (`model_sha256` diferente);
    - sem `--latency-machine`, grava `unspecified (<SO> <arquitetura>, <n> CPUs)`, sem o nome da máquina.
12. **Treino:**
    - na fase A, o backbone inteiro fica em `eval()`; na fase B, só os módulos ainda congelados ficam assim. Isso congela as estatísticas de BatchNorm do que não treina;
    - o `EarlyStopper` começa do zero na fase B;
    - a ordem de embaralhamento de cada época vem de `torch.Generator().manual_seed(seed·100003 + época)`. Por isso o `--resume` reproduz o mesmo histórico, o que é verificado em `test_resume_gives_the_same_history`;
    - `val_grade_qwk` indefinido vai como `null` no `history` e conta como −1 na escolha da melhor época;
    - os checkpoints são gravados de forma atômica e lidos com `weights_only=True`.
13. **Pesos de classe com CORN:** `grade_class_weights` roda também com CORN, para acusar um grau sem imagens de treino (`TrainError`). O peso não é usado nem gravado, e `grade_class_weights` fica `null` no `training_config.json`.
14. **`deviations_from_defaults`:** lista de `{field, default, value}`, só para os hiperparâmetros com padrão na SPEC. Caminhos, `model_version` e `num_workers` ficam fora.
15. **Export:**
    - usa o exportador TorchScript (`dynamo=False`). O exportador padrão do torch 2.14 (dynamo) exige o `onnxscript`, que não está no `uv.lock`, e o `uv.lock` fica fora do que o ml-engineer pode editar. O aviso de depreciação é silenciado só nessa chamada;
    - o `cumprod` do CORN é escrito como produtos explícitos, que qualquer opset suporta;
    - as 8 entradas da paridade alternam os estratos (tipo, grau) do dataset sintético, em vez de serem as 8 primeiras linhas.
16. **PNGs:** a fonte TrueType é procurada no sistema (DejaVu, Liberation, Noto ou Arial). A fonte embutida no Pillow não tem letras acentuadas. Sem nenhuma delas, os rótulos saem sem acento (`inutilizavel`) em vez de quadrados. A classe `other` aparece como "outro".
17. **CHANGELOG (`report.py`):**
    - a data da entrada vem do `evaluated_at`;
    - além das 6 metas, a tabela mostra as outras métricas e os ICs, com meta e status "—";
    - os `warnings` já entram em "Problemas conhecidos";
    - `--append` acrescenta a entrada no fim do arquivo.
18. **Notebook:**
    - o token é lido de `google.colab.userdata` e passado ao `git` só pelo ambiente do processo (`GIT_CONFIG_COUNT`/`http.extraHeader`). Ele não aparece na URL, no `.git/config` nem numa mensagem de erro;
    - os checkpoints ficam no Drive (link `ml/checkpoints`), para o `--resume` sobreviver a uma desconexão;
    - cada `!comando` é seguido de `assert _exit_code == 0` (com `# noqa: F821`, porque o ruff também lê notebooks);
    - o `pip` do Colab não usa o `uv.lock`, e as versões efetivas ficam no `training_config.json`.

## SPEC_ISSUE (se houver)

Nenhum.

## Observações para o orquestrador

1. **`.onnx` versionado na fixture.** O pedido da rodada diz "nenhum `.onnx` no Git", mas a SPEC-012 §4.10 e o CA-14 exigem que `ml/tests/fixtures/tiny_model/model.onnx` (2.536 bytes, rede mínima, sem pesos reais) esteja no Git e não seja ignorado. Segui a SPEC. Nenhum `.onnx` de modelo real nem checkpoint entrou no Git: `ml/models/**/*.onnx`, os `.pt` e `ml/checkpoints/` continuam no `.gitignore`. Também não foi preciso acrescentar a negação `!ml/tests/fixtures/**/*.onnx` ao `.gitignore`.
2. **Extra `train` × borda:** como avisado, com o extra instalado, 3 testes de `edge/tests/test_publisher_real_api.py` falham (`httpx2` via `huggingface-hub`). Por isso, com torch, rodei só `ml/tests`. A suíte inteira rodou sem o extra.
3. **CA-28 (manual):** os passos estão no `ml/README.md`, em "Do Colab ao Release". O token do Colab precisa ser *fine-grained* e somente leitura, criado pela dupla como segredo `GITHUB_RO_TOKEN`.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (sem torch, na suíte inteira; com torch, em `ml/tests`, incluindo os *slow*)
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nada de `ml/data/` lido, copiado ou commitado; os testes e os *smoke* usam só o dataset sintético em `tmp_path`
