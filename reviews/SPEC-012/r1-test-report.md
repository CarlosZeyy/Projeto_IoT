# SPEC-012 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-012](../../docs/specs/SPEC-012-ml-treino-export.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `4858b58` |
| **Veredicto** | **PASS** |

O veredicto é PASS por quatro motivos:
- os CAs automatizáveis (CA-01 a CA-27) têm teste de aceite, e todos passam;
- os *slow* rodaram localmente com torch e passam (Definição de pronto, abaixo);
- a suíte inteira passa no ambiente do CI, sem torch;
- o ruff está limpo (`check` e `format --check`).

O CA-28 é manual (treino real no Colab). Ele fica **pendente com a dupla**, porque ainda não há fotos reais. Isso não é falha (§5 e §8 da SPEC).

Não encontrei bug. Há 5 observações de baixa severidade, nenhuma contra um CA (ver "Testes exploratórios").

Arquivo de aceite: `ml/tests/acceptance/test_spec_012.py`, escrito a partir dos CAs antes de ler a implementação, só pela interface pública:
- as CLIs (`python -m qc_ml.pipeline|thresholds|evaluate|report` em subprocesso, ou `main(argv)`);
- as funções e classes que a SPEC nomeia;
- os artefatos em disco.

O arquivo tem 64 casos:
- 30 `test_caNN_*` (o CA-11, o CA-12 e o CA-20 têm 2 testes cada; o CA-28 é manual);
- 28 `test_extra_*`, que dão 34 casos, porque um deles é parametrizado com 7.

Por ambiente:
- **com torch:** 63 passam, e 1 é pulado: o CA-12 para `ml/models/*/`, porque nenhum `model.onnx` local existe neste checkout (comportamento pedido pelo CA);
- **sem torch (CI):** 49 passam, e 15 são pulados (os 14 *slow*, com `importorskip("torch")`, e o mesmo CA-12 local).

Regras seguidas:
- **Dados:** só `make_synthetic_dataset` em `tmp_path`, e nada de `ml/data/` é lido.
- **Escrita:** toda escrita ou remoção passa antes por `_inside(path, tmp_path)`.
- **Rede:** nenhuma (`pretrained=False`, `HF_HUB_OFFLINE=1`, `CUDA_VISIBLE_DEVICES=""` nos subprocessos).
- **Suíte:** nenhum teste roda a suíte em subprocesso.
- **Segredos:** nenhuma credencial literal.

## Cobertura dos critérios de aceite

| Critério | Teste de aceite (`ml/tests/acceptance/test_spec_012.py::`) | Resultado |
|---|---|---|
| CA-01 (torch) | `test_ca01_model_shapes_and_probabilities` | ✅ (com torch) |
| CA-02 (torch) | `test_ca02_corn_zero_logits_to_probabilities` (cabeça CORN zerada, passando pelo `ProbabilityWrapper`) | ✅ (com torch) |
| CA-03 (torch) | `test_ca03_masked_grade_loss` (comparado com `F.cross_entropy`) | ✅ (com torch) |
| CA-04 | `test_ca04_grade_class_weights` | ✅ |
| CA-05 | `test_ca05_early_stopper` | ✅ |
| CA-06 | `test_ca06_config_validation` (pelo `load_config` de um JSON e pelo `TrainConfig`) | ✅ |
| CA-07 (slow) | `test_ca07_pipeline_smoke_writes_every_artifact` | ✅ (com torch) |
| CA-08 (slow) | `test_ca08_training_config_contents` | ✅ (com torch) |
| CA-09 (slow) | `test_ca09_same_seed_same_history` (2 execuções de `python -m qc_ml.pipeline` em CPU) | ✅ (com torch) |
| CA-10 (slow) | `test_ca10_onnx_model_contract` | ✅ (com torch) |
| CA-11 | `test_ca11_model_sha256_matches_onnx` (fixture e `ml/models/*/` locais); `test_ca11_smoke_model_sha256` (slow, modelo do *smoke*) | ✅ |
| CA-12 | `test_ca12_parity_of_tiny_fixture`; `test_ca12_parity_of_local_models` (skip sem `model.onnx` local) | ✅ / skip |
| CA-13 | `test_ca13_perturbed_fixture_fails_parity` (`max_abs_diff = 0,0010000058 ≥ 1e-3`) | ✅ |
| CA-14 | `test_ca14_tiny_fixture_files_size_and_git` (852.546 bytes; `git check-ignore --no-index` e `git ls-files`) | ✅ |
| CA-15 (R-11) | `test_ca15_thresholds_refuse_test_and_train` | ✅ |
| CA-16 | `test_ca16_type_threshold_max_with_false_unknown_at_most_5pct` | ✅ |
| CA-17 | `test_ca17_unusable_threshold_for_recall_90pct` | ✅ |
| CA-18 | `test_ca18_review_threshold_targets_10pct` | ✅ |
| CA-19 | `test_ca19_thresholds_cli_writes_decision_and_report` | ✅ |
| CA-20 (R-11) | `test_ca20_test_split_requested_once_by_evaluate` (CI, fixture); `test_ca20_pipeline_requests_test_once_from_evaluate` (slow, pipeline) | ✅ |
| CA-21 | `test_ca21_evaluate_without_decision_json` | ✅ |
| CA-22 | `test_ca22_metrics_json_contents` | ✅ |
| CA-23 | `test_ca23_grade_metrics_example` | ✅ |
| CA-24 | `test_ca24_latency_only_rewrites_only_latency` | ✅ |
| CA-25 | `test_ca25_changelog_display_rule` | ✅ |
| CA-26 (R-03) | `test_ca26_notebook_is_clean` | ✅ |
| CA-27 | `test_ca27_modules_import_without_torch` | ✅ |
| CA-28 (manual) | — (Colab com o dataset real) | ⏳ pendente com a dupla |

Notas sobre como alguns CAs foram verificados:
- **CA-17 e CA-18:** a parte "recall de `unusable` na val é 0,9" e a parte "a fração `needs_review` resultante é 10%" são recalculadas com `qc_ml.decision.apply_decision` e os limiares escolhidos. Não dependem do formato interno do relatório.
- **CA-20:** o espião troca o atributo `qc_ml.split.rows_for`. Para cada chamada, registra o `which`, o módulo chamador (pelo `__name__` do frame) e se o `decision.json` já existe. Resultado:
  - `"test"` é pedido uma única vez, pelo `qc_ml.evaluate`, com o `decision.json` já gravado;
  - `qc_ml.train` e `qc_ml.thresholds` só pedem `train`/`val`.
- **CA-22:** a soma da `grade_confusion` é comparada com uma contagem independente, feita lendo o `manifest.csv` e o `split_v1.csv` com `csv`, sem usar `rows_for`.
- **CA-25:** cada linha da tabela é localizada pelo valor exibido. O teste também confere que `0,9313` e `120,0000` não aparecem em lugar nenhum.

## Definição de pronto: *slow* com torch

Ambiente com o extra, criado com `uv sync --all-packages --extra train`:
- torch 2.14.1+cu130, sem CUDA disponível (CPU);
- timm 1.0.30, onnx 1.23.2, onnxruntime 1.31.0, coral-pytorch 1.4.0.

Seguindo o pedido, rodei só `ml/tests` neste ambiente. Com o extra, 3 testes de `edge/tests/test_publisher_real_api.py` falham por causa do `httpx2`, um motivo alheio a esta SPEC.

```text
$ uv run pytest -q ml/tests/acceptance/test_spec_012.py -rs
60 passed, 1 skipped in 37.29s              (antes dos 3 slow exploratórios do fim do arquivo)
$ uv run pytest -q ml/tests/acceptance/test_spec_012.py -k "extra_training_config or corn_smoke or resume"
3 passed, 61 deselected in 43.56s
$ uv run pytest -q ml/tests -rs
381 passed, 2 skipped in 111.80s
SKIPPED ml/tests/acceptance/test_spec_012.py: no ml/models/*/model.onnx in this checkout
SKIPPED ml/tests/test_parity.py:53: no local ml/models/*/model.onnx (the real model is not in Git)
```

Os 14 *slow* do arquivo de aceite são:
- CA-01, CA-02, CA-03, CA-07, CA-08, CA-09, CA-10;
- CA-11 do *smoke*;
- CA-20 do pipeline;
- 5 `test_extra_*`: execução em processo igual às execuções em subprocesso, `metrics.json` completo do *smoke*, datas UTC do `training_config.json`, pipeline CORN de ponta a ponta e `--resume`.

Os três pipelines *smoke* do fixture de módulo levam cerca de 17 s no total, com `mobilenetv3_small_050`, `pretrained=false`, 1 época por fase e `num_workers=0`.

## Suíte completa (ambiente do CI, sem torch)

Depois dos *slow*, voltei o ambiente com `uv sync --all-packages --locked`. Conferi que `import torch` dá `ModuleNotFoundError`.

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q -rs
4772 passed, 22 skipped, 1 warning in 316.24s (0:05:16)
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
210 files already formatted
```

- **Os 22 skips:**
  - os 15 deste arquivo (14 *slow* e o CA-12 local);
  - `ml/tests/test_dataset.py`, `test_model.py` e `test_pipeline_slow.py` (torch);
  - os 2 *slow* do aceite da SPEC-011 (torch);
  - o CA-12 local do autor;
  - o CA-16 manual da SPEC-008 (`QC_REAL_MODEL_DIR`).
- **O aviso:** é o `StarletteDeprecationWarning` do `fastapi/testclient.py` ("install `httpx2` instead"), alheio à SPEC-012.
- **Contagem:** 4772 = 4723 do dev-report + os 49 casos deste arquivo que rodam sem torch.

O `.venv` ficou no estado do CI, **sem** o extra.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Automatizados no arquivo (`test_extra_*`, todos passam):

| Caso | Resultado |
|---|---|
| `model.onnx` alterado (sha divergente) e `model.onnx` ausente | `evaluate` sai com 2 e nada é gravado; `OnnxModel` recusa ✅ |
| `model.sha256` em maiúsculas | `evaluate` sai com 2 e nenhum `metrics.json` ✅ |
| `--latency-only` sem `metrics.json` | sai com 2 e nada é gravado ✅ |
| Duas avaliações seguidas | só `evaluated_at` e `latency_*` mudam (bootstrap de seed fixa) ✅ |
| `counts`, hashes e `n_items_test_by_grade` do `metrics.json` | iguais aos recontados do manifest e do split; `evaluated_at` com fuso ✅ |
| Split feito à mão, sem nenhum `unusable` no teste | `support = 0`, `recall`, `unusable_recall` e `unusable_recall_ci95` são `null` (não omitidos) e `warnings` não está vazio ✅ |
| `split_v1.csv` editado depois do `.sha256` | `thresholds` sai com 2, sem `decision.json` nem relatório ✅ |
| Caminhos com acento e espaço (`Área de dados ç`) | `thresholds` funciona ✅ |
| `model_version` com maiúsculas, sem `-vN`, com mais de 40 caracteres ou com espaço no fim; `epochs_a = 4` sem `smoke`; backbone fora da N-01; chave desconhecida | `ConfigError` ✅ |
| `epochs_a` 5 e 10 com `efficientnet_b0`; `ml/configs/partqc-mnv3-v1.json` | carregam ✅ |
| `grade_class_weights` com um grau ausente, e com contagens iguais | `TrainError`; `None` ✅ |
| `EarlyStopper`: melhora menor que `min_delta`; QWK indefinido (`None`) | não zera a paciência; conta como −1 ✅ |
| Exemplos da regra de decisão (`unusable` pelo limiar, `other`, abaixo do `type_threshold`, margem de +0,10) | conforme a §6.2 da arquitetura ✅ |
| `qc_ml.decision` × `qc_edge.decision` em 500 vetores aleatórios | mesmo tipo, grau, revisão e confiança (±1e-9) ✅ |
| Validação sem `unusable` | `unusable_threshold = 0,50` e nota `no_unusable_in_val` ✅ |
| Fixture de paridade com `model_sha256` de outro modelo | `ok = False` ✅ |
| Formato da `parity_fixture.npz` | `inputs` float32 `[8,3,224,224]`, saídas `[8,3]`/`[8,5]`, sha igual ao `model.sha256` ✅ |
| CHANGELOG com `--previous` e `--append`; métrica `null`; `grade_mae = 0.12341` | coluna da versão anterior; `n/d`; `0,1235` (para cima); acrescenta sem apagar o cabeçalho ✅ |
| IC exibido (`[0.61239, 0.81231]`) | `0,6123` e `0,8124` (alargado) ✅ |
| Notebook | confere Python 3.12, lê o token de `google.colab.userdata`, roda `qc_ml.data validate`; sem token literal em nenhuma célula ✅ |
| `ml/README.md` (Definição de pronto) | documenta `gh release create/download`, `sha256sum`, `--latency-only` e `qc_ml.report changelog` ✅ |
| `grade_metrics` vazio e regra de defeito | `null`; igual a `qc_contracts.is_defective` ✅ |
| *slow:* datas do `training_config.json` | UTC; fase A antes da B ✅ |
| *slow:* pipeline CORN de ponta a ponta | exit 0, paridade ok, `grade_probs` não negativas e somando 1 no ONNX ✅ |
| *slow:* `--resume` | com a mesma config, o histórico é o mesmo; com `lr_b` alterado, sai com 2 (`ConfigError`) ✅ |
| *slow:* terceira execução em processo | mesmo `history` das execuções em subprocesso ✅ |

Sondagens manuais (script no scratchpad, fora do Git):

| Caso | Resultado |
|---|---|
| `decision.json` com chave extra, sem uma chave, valor 1,7, valor em string ou JSON inválido | `evaluate` sai com 2 e não grava `metrics.json` ✅ |
| `labels.json` sem `other` | `evaluate` sai com 2 ✅ |
| `report changelog` sem `metrics.json` | sai com 2 ✅ |
| `Predictions(split="validation")` | `ValueError` ✅ |

Observações de baixa severidade, nenhuma contra um CA e nenhuma bloqueante:
- **O-01:** `choose_thresholds` aceita, sem reclamar, `type_probs` com `NaN`, valores negativos ou soma ≠ 1, e índices verdadeiros fora de `labels`. Com `NaN`, por exemplo, sai `type_threshold = 0,85`, porque `NaN < t` é falso.
  - A SPEC não pede essa validação, e o caminho real (`OnnxModel.predict`) só produz entradas válidas.
  - Uma validação em `Predictions` evitaria limiares silenciosamente errados vindos de um modelo quebrado.
- **O-02:** a nota `review_adjusted` aparece mesmo quando o `r` escolhido é 0,60. Isso acontece quando nenhum `r` da grade chega à faixa e todos empatam. Segue a SPEC ao pé da letra ("Fora → … e nota `review_adjusted`"); fica só o registro.
- **O-03:** `report.format_metric` exibe `True` e `nan` como texto. Um `metrics.json` válido nunca contém esses valores (o JSON não tem `NaN`, e as métricas não são booleanas).
- **O-04:** `0.1 + 0.2` numa métrica em que menor é melhor é exibido como `0,3001`, porque `Decimal(repr(...))` vê `0.30000000000000004`. É exatamente a regra de `docs/architecture.md` §7 (nunca a favor da meta).
- **O-05:** com o extra `train`, a suíte inteira não fica verde (3 testes da borda, por causa do `httpx2`), como o pedido da rodada já previa. Não tem relação com o código da SPEC-012.

## Testes de aceite de SPECs anteriores

Nenhum ajuste. A SPEC-012 não muda comportamento verificado por outro arquivo de aceite.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
