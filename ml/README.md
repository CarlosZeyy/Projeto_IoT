# qc-ml — dados, split, treino e avaliação

Pacote do pipeline de ML do PartQC. A SPEC-011 entrega a parte de **dados**: validação do manifest, overrides, exclusões, relatório de dados, concordância entre rotuladores, split agrupado por peça e augmentations. A SPEC-012 entrega o **modelo**: treino em 2 fases, export ONNX com paridade, limiares escolhidos na validação e avaliação no teste.

Referências: `docs/dataset-protocol.md`, `docs/architecture.md` §7, skill `ml-pipeline`, ADR-004, ADR-005 e ADR-014.

## Instalação

```bash
uv sync --all-packages                 # sem torch: data, split, agreement, augment, synthetic
uv sync --all-packages --extra train   # + torch/timm: qc_ml.dataset (PartsDataset) e o treino
```

`qc_ml.data`, `qc_ml.split`, `qc_ml.agreement`, `qc_ml.augment` e `qc_ml.synthetic` não importam torch. Da SPEC-012, `predict`, `decision`, `thresholds`, `evaluate`, `parity`, `report`, `config` e `pipeline` também não (rodam no CI só com onnxruntime). Exigem o extra `train`: `qc_ml.dataset`, `qc_ml.model`, `qc_ml.export` e o laço de `qc_ml.train` (os auxiliares puros de `qc_ml.train`, como `TrainConfig`, `grade_class_weights` e `EarlyStopper`, importam sem torch).

## Comandos

Todos os comandos rodam a partir da raiz do repositório e saem com `0` em caso de sucesso e `2` em qualquer problema. O `DATASET_DIR` padrão é `ml/data` (fora do Git).

### Validar o dataset

```bash
uv run --package qc-ml python -m qc_ml.data validate --dataset-dir ml/data
```

- Lê `manifest.csv`, aplica `labels_overrides.csv` e `exclusions.csv` (se existirem) e decodifica todas as imagens com `qc_preprocess.load_image`.
- Sem problemas: imprime `manifest ok: <n> images, <m> items, <k> excluded, <j> overridden`.
- Com problemas: imprime um problema por linha (`<arquivo>:<registro>: <código>: <image_path>: <mensagem>`) e, depois, uma linha `count <código>: <n>` por código, em ordem alfabética.
- `too_many_jpeg_scans` indica foto com vídeo anexado ("foto com movimento"): refotografe com o recurso desligado (`docs/dataset-protocol.md` §3). Não corte o arquivo.
- `orphan_image` indica um `.jpg` sob `raw/` sem linha no manifest; `excluded_file_present`, uma foto excluída que ainda está em disco (`docs/dataset-protocol.md` §8.1).

### Relatório de dados

```bash
uv run --package qc-ml python -m qc_ml.data report --dataset-dir ml/data \
    --split ml/splits/split_v1.csv --out ml/reports/data_report.json
```

Contagens por tipo × grau × split, peças por grau, imagens por peça e as combinações abaixo da meta (`below_target`: < 120 imagens ou < 12 peças) e do mínimo (`below_minimum`: < 8 peças). Sem `--split`, as contagens saem só com `total`.

### Split por peça (R-11)

```bash
uv run --package qc-ml python -m qc_ml.split --dataset-dir ml/data --splits-dir ml/splits --seed 42
```

- Sem nenhum `split_v*.csv`: cria `split_v1.csv`, `split_v1.sha256` e `split_v1.json`. Os três vão para o Git.
- Com split existente: usa o de maior N como anterior. As peças antigas mantêm o split, inclusive nas imagens novas delas. As peças novas vão só para treino e validação, porque o teste é congelado. Só grava `split_v{N+1}` se algo mudou; senão imprime `split unchanged: split_v<N>`.
- Uma imagem de teste que sumiu do manifest sem estar em `exclusions.csv` é erro (saída 2, nada gravado). Uma imagem excluída sai do split novo com o aviso `excluded_previous_image`.
- Os erros vão para a saída de erro (stderr).
- `split_v1` só deve ser gerado com os dados reais da S3 (marco "teste final congelado" do `docs/plan.md`).

No código, as linhas de um split só se obtêm com `qc_ml.split.rows_for(df, split_df, "train" | "val" | "test")`. O `load_split` confere o `.sha256`: um split editado à mão é recusado.

### Concordância entre rotuladores

```bash
uv run --package qc-ml python -m qc_ml.agreement --first ml/data/manifest.csv \
    --second ml/data/labels_second.csv --out ml/reports/agreement.json
```

O primeiro rótulo é o grau **original** do manifest, e as overrides não se aplicam. As imagens de `exclusions.csv` (no diretório do `--first`) saem dos dois arquivos. O JSON traz o QWK (`sklearn`, pesos quadráticos), as concordâncias exata e ±1, a matriz 5×5 e `meets_minimum` (≥ 0,6) e `meets_desired` (≥ 0,8). Com algum problema ou sem nenhum par, sai com 2 e não grava nada.

## Modelo (SPEC-012)

Uma versão do modelo é descrita por um JSON em `ml/configs/<versão>.json` (`TrainConfig`). O nome segue `partqc-<sigla>-v<N>` (`mnv3` = `mobilenetv3_large_100`, `effb0` = `efficientnet_b0`). Valores diferentes dos padrões da skill `ml-pipeline` são permitidos e ficam listados em `deviations_from_defaults` no `training_config.json`.

### Pipeline completo

```bash
uv run --package qc-ml python -m qc_ml.pipeline --config ml/configs/partqc-mnv3-v1.json [--resume]
```

Encadeia os passos abaixo e para no primeiro erro (saída 2). Cada passo também tem CLI própria:

| Passo | Comando | Split usado | Grava |
|---|---|---|---|
| Treino (torch) | `python -m qc_ml.train --config <json> [--resume]` | train, val | `ml/checkpoints/<v>/last.pt` e `best.pt`; `ml/models/<v>/training_config.json` |
| Export (torch) | `python -m qc_ml.export --config <json>` | nenhum (entradas sintéticas) | `model.onnx`, `model.sha256`, `labels.json`, `preprocessing.json`, `parity_fixture.npz` |
| Limiares | `python -m qc_ml.thresholds --config <json>` | **val** | `ml/models/<v>/decision.json`, `ml/reports/<v>/thresholds_report.json` |
| Avaliação | `python -m qc_ml.evaluate --config <json> [--latency-machine "<texto>"]` | **test** (uma vez, depois do `decision.json`) | `ml/models/<v>/metrics.json`, `ml/reports/<v>/type_confusion.png` e `grade_confusion.png` |

- **R-11:** os limiares saem só da validação (`choose_thresholds` recusa outro split) e só o `evaluate` pede `rows_for(..., "test")`. O `evaluate` sai com 2 se faltar o `decision.json` (`run qc_ml.thresholds first`) ou se o `model.onnx` não bater com o `model.sha256`.
- **`metrics.json`:** valores brutos, com `null` para métrica indefinida. Traz IC 95% por bootstrap reamostrando peças (`grade_qwk_ci95`, `unusable_recall_ci95`, `defective_recall_ci95`), peças de teste por grau e `warnings` (grau com menos de 2 peças no teste, reamostragens indefinidas, imagens excluídas do split).
- **Treino:** fase A com o backbone congelado; fase B com os 2 últimos estágios de `blocks` e o `conv_head` descongelados, com early stopping pelo QWK de grau da validação. O melhor checkpoint é o de maior QWK de validação (empate: menor `val_loss`, depois a época mais antiga). Desconexão no Colab: rode de novo com `--resume` (a configuração precisa ser a mesma).
- **Paridade:** `python -m qc_ml.parity --model-dir ml/models/<v>` compara o ONNX (onnxruntime) com as saídas do torch gravadas no `parity_fixture.npz` (`max |onnx − torch| < 1e-4`, argmax idêntico, mesmo `model_sha256`). O export apaga o `model.onnx` se a paridade falhar.
- **Latência oficial (RNF-02):** no notebook da borda, `python -m qc_ml.evaluate --config <json> --latency-only --latency-machine "notebook-borda"` reescreve só `latency_ms_p50`, `latency_ms_p95`, `latency_machine` e `latency_runs` (100 medições depois de 10 aquecimentos; `load_image` + `preprocess` + `run`, batch 1).

### Do Colab ao Release (CA-28, tarefa da dupla)

1. No Colab, abra `ml/notebooks/train_colab.ipynb` (runtime com GPU e o segredo `GITHUB_RO_TOKEN`, token *fine-grained* somente leitura) e rode todas as células. O notebook valida o dataset, roda o pipeline e copia `ml/models/<v>/` e `ml/reports/<v>/` para o Drive. **Não** salve o notebook com saídas no repositório.
2. Confira que o pipeline terminou com saída 0.
3. Copie os artefatos do Drive para `ml/models/partqc-mnv3-v1/` e `ml/reports/partqc-mnv3-v1/` no repositório local.
4. No notebook da borda: `uv run --package qc-ml python -m qc_ml.evaluate --config ml/configs/partqc-mnv3-v1.json --latency-only --latency-machine "notebook-borda"`.
5. Gere a entrada do CHANGELOG e confira cada número com o `metrics.json`:
   `uv run --package qc-ml python -m qc_ml.report changelog --model-dir ml/models/partqc-mnv3-v1 --append ml/models/CHANGELOG.md`. Preencha "O que mudou" e "Problemas conhecidos".
6. Paridade com o modelo real: `uv run pytest -q ml/tests/test_parity.py` (o teste roda para cada `ml/models/*/` com `model.onnx` local).
7. Publique o Release com a conta CarlosZeyy (prefixo `GH_TOKEN="$(gh auth token --user CarlosZeyy)"`, como no `CLAUDE.md`):
   `gh release create model-partqc-mnv3-v1 ml/models/partqc-mnv3-v1/model.onnx --title "Modelo partqc-mnv3-v1" --notes "sha256: $(cat ml/models/partqc-mnv3-v1/model.sha256)"`.
   Na borda: `gh release download model-partqc-mnv3-v1 -p model.onnx -D ml/models/partqc-mnv3-v1` e `sha256sum ml/models/partqc-mnv3-v1/model.onnx`.

Vão para o Git: os JSONs, o `parity_fixture.npz`, o `model.sha256`, os PNGs de `ml/reports/` e o `ml/models/CHANGELOG.md`. **Não** vão: `model.onnx` e os checkpoints (`.gitignore`).

### Fixture mínima do CI

`ml/tests/fixtures/tiny_model/` é um diretório de modelo completo (rede mínima: conv 3→8, pooling global, duas cabeças) exportado pelo mesmo `ProbabilityWrapper` e `export_onnx`, com `decision.json` 0,70 / 0,50 / 0,60 e menos de 1 MB. As entradas da paridade são sintéticas. Para recriá-la (com o extra `train`):

```bash
uv run --package qc-ml python ml/scripts/make_tiny_fixture.py
```

## Dataset sintético (testes)

`qc_ml.synthetic.make_synthetic_dataset(root, items_per_stratum=4, images_per_item=2, include_other=True, seed=0)` cria, em `root`, o layout da SPEC-010 com JPEGs 256×256 gerados pelo Pillow e um `manifest.csv` válido. Os graus de `S-xxx`/`N-xxx` seguem em rodízio: `S-001` é perfect, `S-002` good, `S-003` fair, e assim por diante. `add_synthetic_item(root, item_id, object_type, grade, n_images=2)` acrescenta imagens de uma peça nova ou existente. Os testes usam sempre `tmp_path`: nenhuma foto real entra no Git (R-02, R-14).

## Testes

```bash
uv run pytest -q ml/tests
```

Os testes que precisam de torch (`test_dataset.py`, `test_model.py` e os *slow* de `test_pipeline_slow.py`) usam `pytest.importorskip("torch")` e são pulados no CI. Para rodá-los localmente: `uv sync --all-packages --extra train` e `uv run pytest -q ml/tests`. Depois, volte ao ambiente do CI com `uv sync --all-packages --locked`.
