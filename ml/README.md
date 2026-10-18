# qc-ml — dados, split, treino e avaliação

Pacote do pipeline de ML do PartQC. A SPEC-011 entrega a parte de **dados**: validação do manifest, overrides, exclusões, relatório de dados, concordância entre rotuladores, split agrupado por peça e augmentations. O treino, os limiares, a avaliação e o export ONNX vêm na SPEC-012.

Referências: `docs/dataset-protocol.md`, `docs/architecture.md` §7, skill `ml-pipeline`, ADR-004, ADR-005 e ADR-014.

## Instalação

```bash
uv sync --all-packages                 # sem torch: data, split, agreement, augment, synthetic
uv sync --all-packages --extra train   # + torch/timm: qc_ml.dataset (PartsDataset) e o treino
```

`qc_ml.data`, `qc_ml.split`, `qc_ml.agreement`, `qc_ml.augment` e `qc_ml.synthetic` não importam torch. Só `qc_ml.dataset` exige o extra `train`.

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

## Dataset sintético (testes)

`qc_ml.synthetic.make_synthetic_dataset(root, items_per_stratum=4, images_per_item=2, include_other=True, seed=0)` cria, em `root`, o layout da SPEC-010 com JPEGs 256×256 gerados pelo Pillow e um `manifest.csv` válido. Os graus de `S-xxx`/`N-xxx` seguem em rodízio: `S-001` é perfect, `S-002` good, `S-003` fair, e assim por diante. `add_synthetic_item(root, item_id, object_type, grade, n_images=2)` acrescenta imagens de uma peça nova ou existente. Os testes usam sempre `tmp_path`: nenhuma foto real entra no Git (R-02, R-14).

## Testes

```bash
uv run pytest -q ml/tests
```

Os testes que precisam de torch (`ml/tests/test_dataset.py`) usam `pytest.importorskip("torch")` e são pulados no CI.
