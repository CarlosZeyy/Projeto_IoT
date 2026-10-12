---
name: ml-pipeline
description: Convenções obrigatórias do pipeline de ML do PartQC — manifest, split agrupado por item_id, augmentations, modelo de duas saídas, métricas exigidas, escolha de limiares na validação, artefatos em ml/models/<versão>/, export ONNX e teste de paridade. Use ao implementar ou revisar qualquer coisa em ml/ ou ao avaliar um modelo.
---

# Pipeline de ML

Referências: `docs/dataset-protocol.md` (dados), `docs/architecture.md` §7 (artefatos), ADR-004, ADR-005 e ADR-014.

## 1. Dados

- Entrada: `DATASET_DIR/manifest.csv`, mais `labels_overrides.csv` (opcional), aplicado por cima.
- Validações que **falham** o pipeline:
  - arquivo de imagem inexistente;
  - `item_id` com dois `object_type` diferentes;
  - grade preenchido em `other` ou vazio em `screw`/`nut`;
  - imagem ilegível.
- Relatório de dados (`ml/reports/data_report.json`): contagem por tipo × grau × split, peças por grau e imagens por peça.

## 2. Split (R-11)

- Agrupado por `item_id`, 70/15/15, estratificado por (tipo, grau dominante da peça), com a seed fixada.
- Salve `ml/splits/split_v<N>.csv` (`image_path,split`) e o seu hash SHA-256. O split é **versionado no Git** (é pequeno e garante reprodutibilidade).
- O teste é congelado a partir do `split_v1`. Novas peças vão só para treino e validação, salvo ADR.
- Teste automático obrigatório: a interseção de `item_id` entre os splits é vazia.

## 3. Pré-processamento e augmentations

- Validação, teste e inferência: **somente** `qc_preprocess.preprocess`. Os parâmetros ficam em `preprocessing.json`.
- Treino:
  - augmentations no PIL **antes** do pré-processamento compartilhado: `RandomResizedCrop` (escala 0,7–1,0), flip horizontal e vertical, rotação de ±20°, `ColorJitter` (brilho e contraste 0,3; saturação 0,2; matiz 0,02), blur leve ocasional;
  - não use augmentations que mudem o grau, como alterações fortes de matiz que "apaguem" ferrugem.

## 4. Modelo

- Backbone timm (padrão `mobilenetv3_large_100`, pré-treinado no ImageNet) com duas cabeças lineares:
  - `type`: T classes, incluindo `other`;
  - `grade`: 5 classes; na ablação CORN, 4 logits.
- **Loss:** `CE(type) + λ·CE_masked(grade)`, com λ = 1 e label smoothing de 0,1 **nas duas cabeças** (na ablação CORN, o smoothing vale só para a cabeça de tipo). A loss de grau é mascarada quando o rótulo de grau não existe (`other`, ferramentas sem grau).
- **Treino em 2 fases:**
  - (A) backbone congelado, lr 1e-3, de 5 a 10 épocas;
  - (B) descongelar as últimas camadas, lr 1e-4, early stopping pelo **QWK de validação**.
- Pesos de classe se algum grau tiver menos de 60% da média.
- Seeds fixas (`torch`, `numpy`, `random`); registre a versão de cada lib em `training_config.json`.

## 5. Métricas (todas no `metrics.json`, calculadas no **teste**)

| Métrica | Escopo |
|---|---|
| `type_accuracy`, `type_confusion` | todos |
| `grade_qwk` (kappa ponderado quadrático) | `screw`/`nut` com grau |
| `grade_mae` (em níveis) | idem |
| `grade_off_by_one_accuracy` | idem |
| `grade_confusion` (5×5) e precisão/recall/F1 por grau | idem |
| `unusable_recall`, `unusable_precision` | idem |
| `defective_recall`, `defective_precision` (poor+unusable vs. resto) | idem |
| `unknown_rate_on_other` e `false_unknown_rate` (com os limiares do `decision.json`) | todos |
| `latency_ms_p50/p95` (onnxruntime CPU, batch 1, máquina indicada) | — |
| `n_images`, `n_items` por split e por classe | — |

Também salve as matrizes de confusão em PNG (`ml/reports/<versão>/`).

**Teste pequeno = incerteza grande.** Para `grade_qwk`, `unusable_recall` e `defective_recall`, reporte também o **IC 95% por bootstrap reamostrando peças (`item_id`)**, com 1.000 reamostragens e seed fixa. Registre `n_items_test` por grau. Se algum grau tiver menos de 2 peças no teste, sinalize em `metrics.json` (`warnings`).

## 6. Limiares (`decision.json`) — escolhidos na **validação**

- `type_threshold`: o **maior** valor, em [0,50; 0,85], que mantém `false_unknown_rate ≤ 5%` em `screw`/`nut` na validação. O teto de 0,85 evita que `needs_review` (confiança < limiar + 0,10) marque quase tudo.
- `unusable_threshold`: o maior valor que garante `unusable_recall ≥ 0,90` na validação. Se for impossível, use o que maximiza o recall e registre isso.
- `grade_review_threshold`: padrão 0,60, ou um ajuste para que cerca de 10% das inspeções da validação fiquem `needs_review`.

## 7. Export e paridade

- `torch.onnx.export` com opset ≥ 17, eixo de batch dinâmico, entrada `image` e saídas `type_probs` e `grade_probs`. A conversão para probabilidades (softmax, ou CORN → probabilidades por classe) fica **dentro** do grafo.
- Rode `onnx.checker`. Grave `model.sha256`.
- `parity_fixture.npz`: 8 entradas pré-processadas mais as saídas do torch. Teste no CI (só onnxruntime): `max |onnx − torch| < 1e-4` e argmax idêntico.

## 8. Versionamento

- Nome: `partqc-<backbone curto>-v<N>` (ex.: `partqc-mnv3-v1`).
- Diretório: `ml/models/<versão>/` com todos os arquivos de `architecture.md` §7.
- O `.onnx` não vai para o Git: publique como anexo de um GitHub Release `model-<versão>`.
- Toda versão nova tem uma entrada em `ml/models/CHANGELOG.md`: o que mudou, as métricas principais e a comparação com a anterior.
