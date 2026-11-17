# Modelos do PartQC — histórico de versões

Uma entrada por versão de modelo (`partqc-<sigla>-v<N>`, skill `ml-pipeline` §8). A entrada é gerada a partir do `metrics.json` da versão, nunca digitada à mão:

```bash
uv run --package qc-ml python -m qc_ml.report changelog \
    --model-dir ml/models/partqc-mnv3-v2 --previous ml/models/partqc-mnv3-v1 \
    --append ml/models/CHANGELOG.md
```

Formato de cada entrada (SPEC-012 §4.8):

- título `## <versão> — AAAA-MM-DD` (data da avaliação, UTC);
- hashes do modelo, do split e do manifest, os limiares do `decision.json` (escolhidos na **validação**) e a máquina da medição de latência;
- tabela métrica × valor × meta do PRD §7 × status, mais a coluna da versão anterior, se houver. Os valores vêm do `metrics.json` (conjunto de **teste**) e são exibidos com 4 casas e vírgula decimal, nunca a favor da meta (`docs/architecture.md` §7, "Exibição das métricas"): corte para baixo quando maior é melhor, arredondamento para cima quando menor é melhor, IC alargado. O status usa o valor bruto;
- "O que mudou" e "Problemas conhecidos", preenchidos pela dupla. Os avisos do `metrics.json` (`warnings`) entram nos problemas conhecidos.

Uma métrica abaixo da meta continua na tabela, com o status `abaixo da meta` (R-11). A primeira entrada vem do treino real da v1 (CA-28 da SPEC-012).

## partqc-mnv3-v1 — 2026-11-05

- `model_sha256`: `7d295bb68643fd8b61bf1980b1ce1692736f1d35bc9848370b6879a00990e420`
- Split: `split_v1.csv` (`split_sha256` `61346ce5612fbbe0cbb8b2c5926d2703c939702fa276eaa60c16070f22fdd5fe`); `manifest_sha256` `e31c5c927f8d87c7e17224457c222f1b541933c9352cbccd8a7d78d4733f2289`
- Limiares (`decision.json`, escolhidos na validação): `{"type_threshold": 0.5, "unusable_threshold": 0.95, "grade_review_threshold": 0.31}`
- Latência medida em: notebook-borda
- Valores do `metrics.json` (teste), exibidos com 4 casas e nunca a favor da meta (`docs/architecture.md` §7); o status usa o valor bruto.

- Tipos do modelo: screw, other, pliers, allen_key, flat_screwdriver, phillips_screwdriver, saw, drill, cordless_screwdriver, hammer, wrench, spirit_level; sem grau: pliers, allen_key, flat_screwdriver, phillips_screwdriver, saw, drill, cordless_screwdriver, hammer, wrench, spirit_level.
- A `type_accuracy` deste modelo não é comparável, como número único, com a de um modelo sem esses tipos (ADR-022): compare pela `type_confusion`.

| Métrica | Valor | Meta (PRD §7) | Status |
|---|---|---|---|
| `type_accuracy` (acurácia de tipo) | 0,5666 | ≥ 0,95 | abaixo da meta |
| `grade_qwk` (QWK do grau) | 0,3979 | ≥ 0,75 | abaixo da meta |
| `grade_qwk_ci95` (IC 95% do QWK, bootstrap por peça) | [-0,0192; 0,7847] | — | — |
| `grade_off_by_one_accuracy` (acurácia do grau com tolerância ±1) | 0,7000 | ≥ 0,90 | abaixo da meta |
| `grade_mae` (erro absoluto médio do grau, em níveis) | 1,3000 | — | — |
| `unusable_recall` (recall de inutilizável) | 0,0000 | ≥ 0,90 | abaixo da meta |
| `unusable_recall_ci95` (IC 95% do recall de inutilizável) | [0,0000; 0,0000] | — | — |
| `unusable_precision` (precisão de inutilizável) | 0,0000 | — | — |
| `defective_recall` (recall de defeituosa: ruim ou inutilizável) | 1,0000 | ≥ 0,90 | atingida |
| `defective_recall_ci95` (IC 95% do recall de defeituosa) | [1,0000; 1,0000] | — | — |
| `defective_precision` (precisão de defeituosa) | 0,3750 | — | — |
| `unknown_rate_on_other` (taxa de desconhecido em outros objetos) | 1,0000 | — | — |
| `false_unknown_rate` (taxa de falso desconhecido) | 0,0000 | — | — |
| `needs_review_rate` (taxa de revisão) | 0,7334 | — | — |
| `latency_ms_p50` (latência p50 em ms) | 19,1863 | — | — |
| `latency_ms_p95` (latência p95 em ms) | 21,3143 | ≤ 300 | atingida |
| `latency_runs` (medições de latência) | 100 | — | — |

Peças no teste por grau: perfect: 2, good: 1, fair: 1, poor: 2, unusable: 1.

Peças de teste de cada métrica `atingida` (contagens do `metrics.json`; ADR-025, decisão 7):

- `defective_recall` 1,0000 (`atingida`): **3 peças defeituosas** (2 `poor` e 1 `unusable`, 3 imagens), entre os **7 parafusos** (10 imagens) com grau no teste. O IC [1,0000; 1,0000] é degenerado: com 3 peças, toda reamostragem definida dá 1,0. O modelo previu defeito em 8 das 10 imagens de parafuso (colunas `poor` e `unusable` da `grade_confusion`), daí a `defective_precision` de 0,3750: o recall alto vem, em boa parte, de prever defeito quase sempre.
- `latency_ms_p95` 21,3143 ms (`atingida`): 100 medições, depois de 10 aquecimentos, percorrendo em ciclo as **30 imagens das 15 peças** do teste, no `notebook-borda` (CPU, batch 1). Não depende da qualidade do modelo.

Escopo das métricas abaixo da meta: `type_accuracy` nas 15 peças (30 imagens) do teste; `grade_qwk`, `grade_off_by_one_accuracy` e `unusable_recall` nos 7 parafusos (10 imagens), com 1 peça `unusable`.

### Dados

- Validação e teste: 0 e 0 imagens externas (ADR-020).
- Treino: 0 imagens externas de 164 (0,0000).

### O que mudou

- Primeira versão oficial (SPEC-045, CA-16; ADR-025). Não há versão anterior para comparar; o modelo provisório da SPEC-041 não tem métricas e não entra nesta comparação.
- Dados: as 223 fotos de três colegas (`c01`, `c02`, `c03`), reimportadas com as correções do Anexo A da SPEC-045 (114 peças), e o `split_v1` do PR #77 (seed 42; treino 84 peças/164 imagens, validação 15/29, teste 15/30). Nenhuma imagem externa e nenhuma foto da página `/capture`.
- Modelo: `mobilenetv3_large_100` pré-treinado no ImageNet, cabeça de grau `ce`, padrões da skill `ml-pipeline` sem desvios (`training_config.json`). 12 tipos, sem `nut`, `adjustable_wrench` e `angle_grinder` (sem imagem no treino). Só `screw` é graduado.
- Limiares escolhidos na validação (`ml/reports/partqc-mnv3-v1/thresholds_report.json`), com as notas `type_target_not_met` (nenhum `t` em [0,50; 0,85] deixa o falso desconhecido da validação em até 5%; em 0,50, 0,5000 nas 24 imagens de validação que não são `other`) e `review_adjusted` (com 0,60, 0,9412 das imagens de validação de parafuso e `other` iriam para revisão; 0,31 é o valor da grade mais perto de 10%, e ainda deixa 0,3530 da validação em revisão).
- Latência oficial (RNF-02, CA-16 da SPEC-008) medida no `notebook-borda` com `--latency-only`.

### Limitações (ADR-025, decisão 7)

Nenhuma meta do PRD §7 pode ser afirmada como propriedade do sistema com este teste.

- **Fundo correlacionado com o colega** (`c01` papel branco, `c02` toalha estampada, `c03` concreto ou barril) e, em parte, com o tipo: o modelo pode ter aprendido o fundo, e nada aqui separa esse efeito.
- **1 foto por peça na maioria**, abaixo das 3 do piso do ADR-024, dispensado só neste dataset.
- **Teste de 15 peças** (30 imagens), com 7 parafusos e 1 a 2 peças por grau (`n_items_test_by_grade`): os ICs são largos ou degenerados (ver `warnings`).
- **Nenhuma métrica de porca:** não há porca no dataset; as métricas de grau são só de parafuso.
- **Tipos com 1 ou 2 peças sem nenhuma medida:** `spirit_level`, `allen_key`, `drill`, `saw` e `cordless_screwdriver` ficaram só no treino (0 peças no teste). Eles ainda "roubam" previsões: a `type_confusion` mostra 6 imagens de teste previstas como `saw` (3 de `pliers` e 3 de `phillips_screwdriver`).
- **Tipos e fusões decididos por um agente**, por miniaturas (Anexo A da SPEC-045); as fusões são conservadoras. O grau continua sendo o do Carlos, por imagem.
- **Graus divergentes dentro de peças fundidas** (ex.: `S-509`, com `perfect`, `good` e `fair`): o grau é por foto, e o estrato do split é o grau dominante.
- **Outro domínio de captura:** os colegas usaram outros celulares, outra distância e outra luz; a demo pela página `/capture` pode se comportar diferente.
- **Nenhuma concordância entre rotuladores:** a rotulagem dupla foi dispensada pelo humano (ADR-025, opção 6B); não existe `ml/reports/agreement.json` para este modelo.
- **Escopo do `false_unknown_rate`:** o `type_threshold` é escolhido na validação contando as imagens de **todos os tipos menos `other`** (SPEC-016 §4.8), mas o `false_unknown_rate` do teste conta **só `screw`/`nut`** (SPEC-012 §4.7; a SPEC-016 não mudou a avaliação). Aqui, isso é só os 7 parafusos (10 imagens): o 0,0000 do teste não mede a mesma coisa que o 0,5000 da validação e não inclui, por exemplo, as 3 imagens de teste de `hammer` previstas como `other` na `type_confusion`.
- **Nenhuma ferramenta graduada:** pelo critério da SPEC-016 §4.6 (≥ 60 imagens de ≥ 5 peças em cada grau), as 4 ferramentas manuais com imagens ficaram em `ungraded_object_types`. Os graus delas no manifest não entram na loss, a borda não dá grau a elas e `tool_grade_metrics` é `{}`, como a SPEC-016 §4.8 manda.

### Problemas conhecidos

- unusable_recall_ci95: unusable_recall was undefined in 347 of 1000 bootstrap resamples, left out of the interval
- defective_recall_ci95: defective_recall was undefined in 11 of 1000 bootstrap resamples, left out of the interval
- grade good has 1 item(s) in the test split (< 2): its metrics are very uncertain
- grade fair has 1 item(s) in the test split (< 2): its metrics are very uncertain
- grade unusable has 1 item(s) in the test split (< 2): its metrics are very uncertain
- few test items for pliers: 1
- few test items for allen_key: 0
- few test items for flat_screwdriver: 1
- few test items for phillips_screwdriver: 1
- few test items for saw: 0
- few test items for drill: 0
- few test items for cordless_screwdriver: 0
- few test items for hammer: 1
- few test items for wrench: 1
- few test items for spirit_level: 0
- Ver também a seção "Limitações" acima (ADR-025, decisão 7).

## partqc-mnv3-v2 — 2026-11-17

- `model_sha256`: `2ed32f21a69c70b65287df3b347648e55c9c91f67e0c006a927251064ca27803`
- Split: `split_v2.csv` (`split_sha256` `0437dbc05d8710be826a52aefadb8278650e6fedd116ab3e5dcb55f5c957f440`); `manifest_sha256` `598991b508a770c2921e9e9a19b448f196a101b23b287dcc15528a498795878d`
- Limiares (`decision.json`, escolhidos na validação): `{"type_threshold": 0.5, "unusable_threshold": 0.95, "grade_review_threshold": 0.3}`
- Latência medida em: notebook-borda
- Valores do `metrics.json` (teste), exibidos com 4 casas e nunca a favor da meta (`docs/architecture.md` §7); o status usa o valor bruto.

- Tipos do modelo: screw, other, pliers, allen_key, flat_screwdriver, phillips_screwdriver, saw, drill, cordless_screwdriver, hammer, wrench, spirit_level; sem grau: pliers, allen_key, flat_screwdriver, phillips_screwdriver, saw, drill, cordless_screwdriver, hammer, wrench, spirit_level.
- A `type_accuracy` deste modelo não é comparável, como número único, com a de um modelo sem esses tipos (ADR-022): compare pela `type_confusion`.

| Métrica | Valor | Meta (PRD §7) | Status | Anterior (partqc-mnv3-v1) |
|---|---|---|---|---|
| `type_accuracy` (acurácia de tipo) | 0,6000 | ≥ 0,95 | abaixo da meta | 0,5666 |
| `grade_qwk` (QWK do grau) | 0,3908 | ≥ 0,75 | abaixo da meta | 0,3979 |
| `grade_qwk_ci95` (IC 95% do QWK, bootstrap por peça) | [-0,0372; 0,7962] | — | — | [-0,0192; 0,7847] |
| `grade_off_by_one_accuracy` (acurácia do grau com tolerância ±1) | 0,5000 | ≥ 0,90 | abaixo da meta | 0,7000 |
| `grade_mae` (erro absoluto médio do grau, em níveis) | 1,4000 | — | — | 1,3000 |
| `unusable_recall` (recall de inutilizável) | 0,0000 | ≥ 0,90 | abaixo da meta | 0,0000 |
| `unusable_recall_ci95` (IC 95% do recall de inutilizável) | [0,0000; 0,0000] | — | — | [0,0000; 0,0000] |
| `unusable_precision` (precisão de inutilizável) | 0,0000 | — | — | 0,0000 |
| `defective_recall` (recall de defeituosa: ruim ou inutilizável) | 0,6666 | ≥ 0,90 | abaixo da meta | 1,0000 |
| `defective_recall_ci95` (IC 95% do recall de defeituosa) | [0,0000; 1,0000] | — | — | [1,0000; 1,0000] |
| `defective_precision` (precisão de defeituosa) | 0,6666 | — | — | 0,3750 |
| `unknown_rate_on_other` (taxa de desconhecido em outros objetos) | 1,0000 | — | — | 1,0000 |
| `false_unknown_rate` (taxa de falso desconhecido) | 0,0000 | — | — | 0,0000 |
| `needs_review_rate` (taxa de revisão) | 0,6667 | — | — | 0,7334 |
| `latency_ms_p50` (latência p50 em ms) | 19,5088 | — | — | 19,1863 |
| `latency_ms_p95` (latência p95 em ms) | 28,2480 | ≤ 300 | atingida | 21,3143 |
| `latency_runs` (medições de latência) | 100 | — | — | 100 |

Peças no teste por grau: perfect: 2, good: 1, fair: 1, poor: 2, unusable: 1.

Peças de teste de cada métrica `atingida` (contagens do `metrics.json`; ADR-025, decisão 7):

- `latency_ms_p95` 28,2480 ms (`atingida`): 100 medições, depois de 10 aquecimentos, percorrendo em ciclo as **30 imagens das 15 peças** do teste, no `notebook-borda` (CPU, batch 1). Não depende da qualidade do modelo. A arquitetura e o tamanho do ONNX são os mesmos do v1, então a diferença para os 21,3143 ms do v1 vem, provavelmente, da carga da máquina em cada medição, não do modelo.

Nenhuma outra métrica com meta foi atingida. O `defective_recall`, `atingida` no v1, ficou abaixo da meta no v2: 0,6666 nas **3 peças defeituosas** (2 `poor` e 1 `unusable`, 3 imagens), entre os **7 parafusos** (10 imagens) com grau no teste. O v2 previu `unusable` para as 2 imagens `poor` (acerto, porque as duas são defeituosas) e `fair` para a imagem `unusable` (erro).

Escopo das métricas abaixo da meta: `type_accuracy` nas 15 peças (30 imagens) do teste; `grade_qwk`, `grade_off_by_one_accuracy`, `unusable_recall` e `defective_recall` nos 7 parafusos (10 imagens), com 1 peça `unusable` e 3 peças defeituosas.

### Comparação com o v1 (mesma validação, mesmo teste)

- **Validação e teste idênticos aos do v1:** as linhas `val` (15 peças, 29 imagens) e `test` (15 peças, 30 imagens) do `split_v2.csv` são exatamente as do `split_v1.csv`. Nenhuma linha mudou de split; o `split_v2` só acrescenta as 19 linhas novas, todas `train` (`split_v2.json`, `parent` `split_v1`).
- **As diferenças estão dentro dos IC** nas métricas que têm IC no `metrics.json`:
  - `grade_qwk`: 0,3908 (v2) e 0,3979 (v1), cada valor dentro dos dois IC ([-0,0372; 0,7962] e [-0,0192; 0,7847]);
  - `defective_recall`: 0,6666 e 1,0000, uma imagem de diferença (a `unusable`). O 1,0000 do v1 está dentro do IC do v2, [0,0000; 1,0000]; o IC do v1, [1,0000; 1,0000], é degenerado (3 peças) e não serve para a comparação;
  - `unusable_recall`: 0,0000 nas duas versões.
- **Métricas sem IC no `metrics.json`:** `type_accuracy` 0,6000 e 0,5666 (18 e 17 acertos em 30 imagens); `grade_off_by_one_accuracy` 0,5000 e 0,7000 (5 e 7 em 10 imagens); `grade_mae` 1,4000 e 1,3000. São diferenças de 1 ou 2 imagens, sem bootstrap, em 15 peças (7 parafusos): não indicam que uma versão seja melhor que a outra.
- **Nenhum número deste arquivo mostra o v2 melhor ou pior que o v1.**
- **O que mudou nas matrizes (fatos, sem causa demonstrada):**
  - `type_confusion`: o v2 prevê `screw` para 8 imagens de teste que não são parafuso (4 de `pliers`, 3 de `phillips_screwdriver` e 1 de `wrench`); o v1 previa para 2 (1 de `pliers` e 1 de `wrench`). As 6 previsões de `saw` do v1 sumiram (0 no v2) e 1 imagem de `phillips_screwdriver` foi prevista como `drill`. As 3 imagens de `other` são `other` no v2 (2 de 3 no v1). As 19 fotos novas, todas de parafuso, são uma explicação possível para o desvio para `screw`, mas nada aqui a demonstra. Na borda, uma ferramenta prevista como `screw` recebe grau.
  - `grade_confusion`: o v2 previu `perfect` para 3 das 4 imagens da peça `fair` (o v1 previa `poor` para 3 delas).
- **Validação:** melhor QWK de grau da validação 0,3556 (época 12) no v2 e 0,4259 (época 6) no v1 (`training_config.json`). Os limiares repetem as notas `type_target_not_met` (falso desconhecido da validação 0,4583 em 0,50, nas 24 imagens que não são `other`; 0,5000 no v1) e `review_adjusted` (com 0,60, 0,8824 das 17 imagens de validação de parafuso e `other` iriam para revisão; 0,30 deixa 0,1765). O `unusable_threshold` continua 0,95 (1 peça `unusable` na validação).

### Dados

- Validação e teste: 0 e 0 imagens externas (ADR-020).
- Treino: 0 imagens externas de 183 (0,0000).

### O que mudou

- Segunda versão oficial (SPEC-045, ADR-025). **A escolha do v2 foi do humano, por teste ao vivo na borda** (17/11/2026), que o aprovou para a apresentação. Não foi uma escolha por métrica: nenhum número do `metrics.json` mostra o v2 melhor que o v1 (ver "Comparação com o v1"), e o conjunto de teste não foi usado para escolher época, limiar ou hiperparâmetro (R-11).
- Dados: **19 fotos novas, de 3 parafusos do próprio grupo**, tiradas pela página `/capture` (origem `capture`): `S-001` `poor` (9 imagens), `S-002` `good` (5) e `S-003` `perfect` (5). **Estão só no treino.** Treino: 84 → 87 peças e 164 → 183 imagens (parafusos: 33 → 36 peças, 62 → 81 imagens). Validação e teste sem mudança. Nenhuma imagem externa.
- Modelo: a configuração (`ml/configs/partqc-mnv3-v2.json`) é a do v1, mudando só `model_version` e `split_file`; sem desvios dos padrões da skill `ml-pipeline`. Mesmos `labels.json` (12 tipos, só `screw` graduado) e `preprocessing.json` do v1. Os pesos de classe do grau foram recalculados pela nova distribuição do treino. Treino em CPU, com o código do commit `8d07355` (os diretórios `ml/src` e `packages/preprocess` são idênticos aos da `main`); melhor época 12, com early stopping.
- Limiares escolhidos na validação (`ml/reports/partqc-mnv3-v2/thresholds_report.json`): `type_threshold` 0,50 e `unusable_threshold` 0,95, como no v1; `grade_review_threshold` 0,30 (0,31 no v1).
- Latência medida no `notebook-borda`.

### Limitações (ADR-025, decisão 7)

Nenhuma meta do PRD §7 pode ser afirmada como propriedade do sistema com este teste. **Todas as limitações do v1 continuam valendo**, porque a validação e o teste são os mesmos:

- **Fundo correlacionado com o colega** (`c01` papel branco, `c02` toalha estampada, `c03` concreto ou barril) e, em parte, com o tipo: o modelo pode ter aprendido o fundo, e nada aqui separa esse efeito.
- **1 foto por peça na maioria** das peças dos colegas, abaixo das 3 do piso do ADR-024, dispensado só neste dataset.
- **Teste de 15 peças** (30 imagens), com 7 parafusos e 1 a 2 peças por grau (`n_items_test_by_grade`): os IC são largos ou degenerados (ver `warnings`).
- **Nenhuma métrica de porca:** não há porca no dataset; as métricas de grau são só de parafuso.
- **Tipos com 1 ou 2 peças sem nenhuma medida:** `spirit_level`, `allen_key`, `drill`, `saw` e `cordless_screwdriver` ficaram só no treino (0 peças no teste).
- **Tipos e fusões decididos por um agente**, por miniaturas (Anexo A da SPEC-045); o grau continua sendo o do Carlos, por imagem.
- **Graus divergentes dentro de peças fundidas** (ex.: `S-509`): o grau é por foto, e o estrato do split é o grau dominante.
- **Nenhuma concordância entre rotuladores** (ADR-025, opção 6B): não existe `ml/reports/agreement.json` para este modelo.
- **Escopo do `false_unknown_rate`:** o limiar é escolhido na validação com todos os tipos menos `other`; o teste conta só `screw`/`nut` (7 parafusos, 10 imagens). O 0,0000 do teste não mede a mesma coisa que o 0,4583 da validação e não inclui as 3 imagens de `hammer` previstas como `other` nem as 8 ferramentas previstas como `screw`.
- **Nenhuma ferramenta graduada** (SPEC-016 §4.6): `tool_grade_metrics` é `{}`.

Novas no v2:

- **Nenhuma métrica mede o fundo, a luz e o celular do humano:** as 19 fotos dele estão só no treino; a validação e o teste não têm nenhuma foto dele (`counts.val.by_origin.capture` e `counts.test.by_origin.capture` são 0). O efeito delas na demo pela página `/capture` não aparece em nenhum número deste arquivo.
- **Só 3 parafusos novos, um por grau** (`poor`, `good`, `perfect`), fotografados pelo humano: o modelo pode associar o fundo, a luz e o celular dele a `screw` e a esses três graus, e nada aqui mede isso.
- **A escolha por teste ao vivo não é reprodutível nem medida:** ela vale para as peças, o fundo e a luz do teste do humano, não é uma métrica e não entra no `metrics.json`.

### Problemas conhecidos

- unusable_recall_ci95: unusable_recall was undefined in 347 of 1000 bootstrap resamples, left out of the interval
- defective_recall_ci95: defective_recall was undefined in 11 of 1000 bootstrap resamples, left out of the interval
- grade good has 1 item(s) in the test split (< 2): its metrics are very uncertain
- grade fair has 1 item(s) in the test split (< 2): its metrics are very uncertain
- grade unusable has 1 item(s) in the test split (< 2): its metrics are very uncertain
- few test items for pliers: 1
- few test items for allen_key: 0
- few test items for flat_screwdriver: 1
- few test items for phillips_screwdriver: 1
- few test items for saw: 0
- few test items for drill: 0
- few test items for cordless_screwdriver: 0
- few test items for hammer: 1
- few test items for wrench: 1
- few test items for spirit_level: 0
- Ver também as seções "Comparação com o v1" e "Limitações" acima (ADR-025, decisão 7).
