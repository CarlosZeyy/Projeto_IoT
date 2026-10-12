# ADR-004: Treinar com PyTorch + timm no Colab e inferir com ONNX Runtime na borda

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-002, ADR-005, ADR-010, ADR-014, SPEC-008, SPEC-011, SPEC-012, R-02, R-11, R-12, N-01 |

## Contexto

O modelo precisa:

- classificar tipo e grau a partir de cerca de 1.200 imagens próprias (ADR-001);
- rodar na CPU do notebook com p95 ≤ 300 ms (RNF-02);
- ser **treinado** pela dupla, porque o treino é parte do trabalho acadêmico.

A borda roda só em CPU (RNF-02). O treino roda no Google Colab, que oferece GPU gratuita, sem garantia de cota, e usa Python 3.12.x no runtime atual da versão gratuita. Fonte: <https://research.google.com/colaboratory/runtime-version-faq.html> (verificado em 2026-10-12).

A v0 previa TensorFlow/Keras. A API e o dashboard não podem depender de bibliotecas de ML (R-12).

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) PyTorch + timm (transfer learning), export para ONNX, `onnxruntime` CPU na borda | timm traz backbones leves pré-treinados (`mobilenetv3_large_100`, `efficientnet_b0`); duas cabeças e losses ordinais (ADR-005) são simples de escrever; o ONNX desacopla a borda do torch; o teste de paridade roda sem torch | Exige o passo de export e o teste de paridade; duas runtimes (torch no treino, onnxruntime na borda) |
| B TensorFlow/Keras (v0) | Material didático abundante; TFLite | Pacote pesado; perdas ordinais e modelos de duas saídas menos práticos; não é o ecossistema do timm |
| C API de LLM com visão (prompt com a foto) | Nenhum treino; aceita objetos novos | Custo por chamada (viola R-01 na prática); não determinístico; não é "treinar um modelo"; a imagem sai da LAN (viola R-02) |
| D Detecção de anomalia (anomalib/PatchCore) | Precisa só de imagens "boas" | Dá um escore de anomalia, não 5 graus; o mapeamento escore → grau seria indireto e arbitrário; não identifica o tipo |

## Decisão

O treino usa **PyTorch + timm**, com backbone padrão `mobilenetv3_large_100` (pré-treinado no ImageNet) e `efficientnet_b0` como alternativa (N-01), executado no Google Colab. O modelo é exportado para **ONNX** (opset ≥ 17, batch dinâmico) e executado na borda com **`onnxruntime` em CPU**. torch, torchvision e timm ficam apenas no extra opcional `train` do pacote `qc-ml`.

## Consequências

- **Positivas:**
  - a borda instala só `onnxruntime`, o que deixa o ambiente leve e rápido de subir;
  - o modelo vira um artefato versionado e trocável via `MODEL_DIR`, e a SPEC-008 pode ser desenvolvida com um ONNX dummy.
- **Negativas / custos aceitos:**
  - o treino depende da cota de GPU gratuita do Colab, que não é garantida;
  - os dados vão ao Colab pelo Google Drive pessoal (`docs/dataset-protocol.md` §8). Isso não fere R-02, que trata da nuvem do projeto, mas deve ser declarado no relatório.
- **O que passa a ser obrigatório:**
  - `parity_fixture.npz` e o teste de paridade no CI (`max |onnx − torch| < 1e-4` e argmax idêntico), rodando só com onnxruntime (SPEC-012);
  - o pré-processamento é o de `qc-preprocess`, idêntico no treino e na borda; os parâmetros ficam em `preprocessing.json`;
  - os artefatos ficam em `ml/models/<versão>/` (`docs/architecture.md` §7); o `.onnx` não vai para o Git (ADR-015);
  - `api/` e `dashboard/` não dependem de torch, timm nem onnxruntime (R-12, ADR-010).

## Quando revisitar

- Se a latência medida (`latency_ms_p95` no `metrics.json`) passar de 300 ms no notebook da demo.
- Se o QWK de validação do baseline v1 ficar abaixo de 0,6 com os dois backbones.
- Se o Colab gratuito deixar de oferecer GPU por mais de uma semana durante a S3–S5.
